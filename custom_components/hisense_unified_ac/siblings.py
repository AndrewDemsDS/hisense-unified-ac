"""Pure matching of an A/C's native Matter entities to the roles this integration uses.

No Home Assistant imports, so the rules are testable on a bare interpreter. `discovery.py`
reads the entity registry and hands the rows here.

Two ways in, in order (the table and the reasoning are in const.py, SIBLING_RULES): the
endpoint label Home Assistant puts in the entity name, then the endpoint, cluster and
attribute encoded in the Matter unique id. The label goes first because it is what the
firmware actually promises; the position is the fallback for a Home Assistant that does
not apply the label and names everything "Switch (3)".
"""

from __future__ import annotations

import re
from typing import NamedTuple

from .const import (
    CLUSTER_MODE_SELECT,
    CONF_CURRENT,
    CONF_FAN,
    CONF_POWER,
    CONF_SLEEP,
    CONF_VOLTAGE,
    SIBLING_RULES,
)


class Candidate(NamedTuple):
    """One entity that shares the base climate's device."""

    entity_id: str
    name: str  # the integration-given name ("Switch (Eco)"), never the user's rename
    unique_id: str


# Home Assistant's Matter unique id ends "-<endpoint>-<description key>-<cluster>-<attr>".
_POSITION = re.compile(r"-(\d+)-[^-]+-(\d+)-(\d+)$")
# The same id starts "<compressed fabric id>-<node id>-", both 16 hex digits.
_NODE = re.compile(r"^[0-9A-Fa-f]{16}-([0-9A-Fa-f]{16})-")
# What the electrical sensors are called when the unique id cannot be read.
_PLAIN_NAMES = {"power": CONF_POWER, "voltage": CONF_VOLTAGE, "current": CONF_CURRENT}


def position(unique_id: str) -> tuple[int, int, int] | None:
    """(endpoint, cluster, attribute) from a Matter unique id, or None."""
    match = _POSITION.search(unique_id or "")
    return tuple(int(g) for g in match.groups()) if match else None  # type: ignore[return-value]


def node_id_from_unique_id(unique_id: str) -> int | None:
    """The Matter node id encoded in a Matter entity's unique id, or None."""
    match = _NODE.match(unique_id or "")
    return int(match.group(1), 16) if match else None


def _has_word(name: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", name) for w in words)


def match_siblings(candidates: list[Candidate]) -> dict[str, str]:
    """Role key -> entity id, for every role some candidate fills."""
    # Sorted by entity id, so the answer does not depend on the registry's order.
    rows = sorted(candidates)
    out: dict[str, str] = {}
    taken: set[str] = set()

    def claim(key: str, entity_id: str) -> None:
        if key not in out and entity_id not in taken:
            out[key] = entity_id
            taken.add(entity_id)

    for row in rows:
        domain = row.entity_id.split(".", 1)[0]
        if domain == "fan":
            claim(CONF_FAN, row.entity_id)
        elif domain == "select" and "sleep" in row.name.lower():
            claim(CONF_SLEEP, row.entity_id)
    for row in rows:
        # The sleep profiles are the node's only ModeSelect, so the cluster alone
        # identifies the select when its name does not say "sleep".
        pos = position(row.unique_id)
        if (
            row.entity_id.startswith("select.")
            and pos
            and pos[1] == CLUSTER_MODE_SELECT
        ):
            claim(CONF_SLEEP, row.entity_id)

    def in_scope(row: Candidate, key: str) -> tuple[int, int, int] | None | bool:
        """False if this row cannot be `key`; else its position (None if unreadable)."""
        domain, _words, where, _endpoint = SIBLING_RULES[key]
        if row.entity_id.split(".", 1)[0] != domain:
            return False
        pos = position(row.unique_id)
        if pos is not None and pos[1:] != where:
            return False
        return pos

    # Pass 1: the endpoint label in the name.
    for key, (_domain, words, _where, _endpoint) in SIBLING_RULES.items():
        for row in rows:
            if in_scope(row, key) is False:
                continue
            if words and _has_word(row.name.lower(), words):
                claim(key, row.entity_id)

    # Pass 2: where it sits on the node.
    for key, (_domain, words, _where, endpoint) in SIBLING_RULES.items():
        for row in rows:
            pos = in_scope(row, key)
            if pos is False:
                continue
            if pos is None:
                # Unreadable unique id: the old "(3)" endpoint postfix, or the bare name
                # of a sensor that is alone on its cluster.
                if endpoint is not None and f"({endpoint})" in row.name:
                    claim(key, row.entity_id)
                elif _PLAIN_NAMES.get(row.name.lower()) == key:
                    claim(key, row.entity_id)
            elif endpoint is not None and pos[0] == endpoint:
                claim(key, row.entity_id)
            elif endpoint is None and not words:
                claim(key, row.entity_id)
    return out
