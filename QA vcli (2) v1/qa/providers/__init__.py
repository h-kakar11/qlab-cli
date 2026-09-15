"""Provider auto-discovery.

Every module in this folder is imported on first use, so a new provider is
live as soon as the file exists — no registration list to update.
"""

from __future__ import annotations

import importlib
import pkgutil

from .base import (  # noqa: F401  (re-exported for convenience)
    CachedProvider,
    Provider,
    all_providers,
    collect,
    collect_series,
    get_provider,
    provider,
)

_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in pkgutil.iter_modules(__path__):
        if module.name.startswith("_") or module.name == "base":
            continue
        importlib.import_module(f"{__name__}.{module.name}")
