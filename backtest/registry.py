"""Component registries for universe filters, triggers, and exits.

Subpackage __init__.py modules register concrete implementations explicitly
(no decorator magic). Registries are plain module-level dicts keyed by name.
"""
from __future__ import annotations

from typing import Callable, Dict

UNIVERSE_FILTERS: Dict[str, Callable] = {}
TRIGGERS: Dict[str, Callable] = {}
EXITS: Dict[str, Callable] = {}

UNIVERSE_FILTER_SCHEMAS: Dict[str, list] = {}
TRIGGER_SCHEMAS: Dict[str, list] = {}
EXIT_SCHEMAS: Dict[str, list] = {}
