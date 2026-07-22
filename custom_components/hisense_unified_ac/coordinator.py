"""Reads W41H1 diagnostics raw from python-matter-server's WebSocket API.

HA's native Matter integration will not render a self-assigned custom cluster, but
matter-server stores every device-reported attribute at a plain numeric path
"<endpoint>/<cluster_id>/<attribute_id>". We open our own WS connection, read the three
mfg-cluster diagnostic attributes for one node, and build our own entities (docs/14).
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
        path = f"1/{MFG_CLUSTER}/{attr}"
        mid = f"diag-{attr}"
        await ws.send_json(
            {
                "message_id": mid,
                "command": "read_attribute",
                "args": {"node_id": self._node_id, "attribute_path": path},
            }
        )
        # Bound the TOTAL wait per attribute (not per message): interleaved traffic on the
        # socket must not be able to extend it indefinitely. Treat a peer-initiated CLOSE as
        # terminal too (aiohttp returns CLOSE, then CLOSED, for a graceful server close).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise UpdateFailed(f"timed out waiting for {path}")
            msg = await ws.receive(timeout=remaining)
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.ERROR,
            ):
                raise UpdateFailed(f"ws closed while reading {path}")
            if msg.type is not aiohttp.WSMsgType.TEXT:
                continue
            data = msg.json()
            if data.get("message_id") != mid:
                continue  # skip unrelated pushes (attribute_updated events, etc.)
            if data.get("error_code") is not None:
                return None
            result = data.get("result")
            if isinstance(result, dict):
                return result.get(path)
            return result

    async def _async_update_data(self) -> dict[str, int | None]:
        out: dict[str, int | None] = {}
        try:
            async with self._session.ws_connect(self._url, heartbeat=30) as ws:
                await ws.receive(timeout=10)  # consume the server-info greeting
                for key, attr in _ATTRS.items():
                    out[key] = await self._read(ws, attr)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise UpdateFailed(f"matter-server read failed: {err}") from err
        return out
