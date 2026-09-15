"""Metric auto-discovery.

Any module dropped in this folder is imported on startup, so adding a file is
all it takes to register new metrics.
"""

from __future__ import annotations

import importlib
import pkgutil

_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{module.name}")
