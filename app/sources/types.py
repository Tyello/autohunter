from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any, Literal


ScrapeFn = Callable[[str], List[Dict[str, Any]]]
BuildUrlFn = Callable[[str], str]
FetchMode = Literal["http", "browser"]


@dataclass(frozen=True)
class SourcePlugin:
    """Defines a listing source.

    - `build_url(query)` returns a URL that, when opened, shows a list of listings.
    - `scrape(url)` returns a list of normalized listing dicts.

    Plugins are declarative: they wire into Settings by attribute-name strings.

    `fetch_mode` is informational (used for logging / ops); scraping may still
    use either http or browser under the hood.
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

    # Ops hint
    fetch_mode: FetchMode = "http"
