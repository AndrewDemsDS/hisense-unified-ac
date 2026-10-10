"""Reads W41H1 diagnostics raw from python-matter-server's WebSocket API.

HA's native Matter integration will not render a self-assigned custom cluster, but
matter-server stores every device-reported attribute at a plain numeric path
"<endpoint>/<cluster_id>/<attribute_id>". We open our own WS connection, read the three
mfg-cluster diagnostic attributes for one node, and build our own entities (docs/14).

The bus counters are newer than that and not on every firmware, so they are handled
differently: one `get_node` returns the node's whole attribute cache, and a counter is
reported only if its path is in it. That costs the device nothing (the cache is filled
by matter-server's own subscription), and it is what lets the sensor platform create a
counter entity only on a node that has the attribute.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_COMPRESSOR_HZ,
    ATTR_FAULTS1,
    ATTR_FEATURES1,
    BUS_COUNTER_ATTRS,
    DIAG_SCAN_INTERVAL,
    MFG_CLUSTER,
)

_LOGGER = logging.getLogger(__name__)

# coordinator.data key -> mfg-cluster attribute id
_ATTRS: dict[str, int] = {
    "compressor_hz": ATTR_COMPRESSOR_HZ,
    "features1": ATTR_FEATURES1,
    "faults1": ATTR_FAULTS1,
}


def attribute_path(attr: int) -> str:
    """matter-server's key for one mfg-cluster attribute on the A/C endpoint."""
    return f"1/{MFG_CLUSTER}/{attr}"


def counters_from_node(node: object) -> dict[str, int | None]:
    """The bus counters present in a `get_node` result, by coordinator key.

    A key is in the result only when the node has the attribute at all, which is the
    signal the sensor platform creates entities from. Present but not a number (a null
    the firmware has not filled yet) is kept as None: the entity exists, state unknown.
    """
    attributes = node.get("attributes") if isinstance(node, dict) else None
    if not isinstance(attributes, dict):
        return {}
    out: dict[str, int | None] = {}
    for key, (attr, _name, _icon) in BUS_COUNTER_ATTRS.items():
        path = attribute_path(attr)
        if path in attributes:
            value = attributes[path]
            is_count = isinstance(value, int) and not isinstance(value, bool)
            out[key] = value if is_count else None
    return out


class HisenseDiagCoordinator(DataUpdateCoordinator[dict[str, int | None]]):
    """Polls matter-server for one node's raw mfg-cluster diagnostic attributes."""

    def __init__(self, hass: HomeAssistant, url: str, node_id: int, name: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{name} diagnostics",
            update_interval=timedelta(seconds=DIAG_SCAN_INTERVAL),
        )
        self._url = url
        self._node_id = node_id
        self._session = async_get_clientsession(hass)

    async def _read(self, ws: aiohttp.ClientWebSocketResponse, attr: int) -> int | None:
        """One read_attribute round-trip; returns the raw value or None."""
        path = attribute_path(attr)
        result = await self._call(
            ws,
            f"diag-{attr}",
            "read_attribute",
            {"node_id": self._node_id, "attribute_path": path},
            path,
        )
        if isinstance(result, dict):
            return result.get(path)
        return result

    async def _call(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        mid: str,
        command: str,
        args: dict,
        what: str,
    ) -> object:
        """One command round-trip; returns its result, or None on an error reply."""
        await ws.send_json({"message_id": mid, "command": command, "args": args})
        # Bound the TOTAL wait per attribute (not per message): interleaved traffic on the
        # socket must not be able to extend it indefinitely. Treat a peer-initiated CLOSE as
        # terminal too (aiohttp returns CLOSE, then CLOSED, for a graceful server close).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise UpdateFailed(f"timed out waiting for {what}")
            msg = await ws.receive(timeout=remaining)
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.ERROR,
            ):
                raise UpdateFailed(f"ws closed while reading {what}")
            if msg.type is not aiohttp.WSMsgType.TEXT:
                continue
            data = msg.json()
            if data.get("message_id") != mid:
                continue  # skip unrelated pushes (attribute_updated events, etc.)
            if data.get("error_code") is not None:
                return None
            return data.get("result")

    async def _read_counters(
        self, ws: aiohttp.ClientWebSocketResponse
    ) -> dict[str, int | None]:
        """The optional bus counters. Never fails the update: they are an extra."""
        try:
            node = await self._call(
                ws, "diag-node", "get_node", {"node_id": self._node_id}, "the node"
            )
        except (UpdateFailed, asyncio.TimeoutError) as err:
            _LOGGER.debug("%s: no node snapshot, counters skipped: %s", self.name, err)
            return {}
        return counters_from_node(node)

    async def _async_update_data(self) -> dict[str, int | None]:
        out: dict[str, int | None] = {}
        try:
            async with self._session.ws_connect(self._url, heartbeat=30) as ws:
                await ws.receive(timeout=10)  # consume the server-info greeting
                for key, attr in _ATTRS.items():
                    out[key] = await self._read(ws, attr)
                out.update(await self._read_counters(ws))
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise UpdateFailed(f"matter-server read failed: {err}") from err
        return out
