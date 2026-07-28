"""Make the component's modules importable without executing its package __init__.

`hisense_unified_ac/__init__.py` is the integration's setup entry point, so it imports
homeassistant. Importing even const.py through the real package would therefore need HA
installed, which would drag the pure-logic tests into needing a full HA environment.

Installing a stub package module with `__path__` set lets the submodules import normally
and lets their relative imports (`from .const import ...`) resolve, while __init__.py is
never run. Modules that genuinely need homeassistant still fail on their own import, which
is what the test tiers key off.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

PACKAGE = "hisense_unified_ac"
COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / PACKAGE


def install() -> None:
    """Register the stub package. Safe to call from every test module."""
    existing = sys.modules.get(PACKAGE)
    if existing is not None and getattr(existing, "__path__", None):
        return
    stub = types.ModuleType(PACKAGE)
    stub.__path__ = [str(COMPONENT)]  # type: ignore[attr-defined]
    sys.modules[PACKAGE] = stub
    sys.path.insert(0, str(Path(__file__).resolve().parent))
