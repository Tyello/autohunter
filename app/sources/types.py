from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any


ScrapeFn = Callable[[str], List[Dict[str, Any]]]
BuildUrlFn = Callable[[str], str]


@dataclass(frozen=True)
class SourcePlugin:
    """Defines a listing source.

    Notes:
    - `scrape` may be None for SPA/JS-heavy sources not implemented yet.
    - Settings are wired by attribute name (strings) to keep plugins declarative.
    """

    name: str
    build_url: BuildUrlFn
    scrape: Optional[ScrapeFn] = None

    # Wiring to settings.py (attribute names)
    enabled_setting: Optional[str] = None
    sched_minutes_setting: Optional[str] = None
    cooldown_minutes_setting: Optional[str] = None

    # Behavior flags
    supports_manual_search: bool = True
    supports_wishlist_monitoring: bool = True
