from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any, Literal


@dataclass(frozen=True, slots=True)
class ScrapeContext:
    """Runtime context passed to scrapers.

    This is the *operational* configuration for a source at runtime, sourced
    from the DB table `source_configs`.

    - source: source name (e.g. 'olx', 'webmotors'). Used for session/browser stickiness.
    - proxy_server: full proxy URL (http://... or socks5://...). Optional.
    - browser_fallback_enabled: allow HTTP -> Playwright fallback on failures/blocks.
    - force_browser: force Playwright first (no HTTP attempt).
    """

    source: str
    proxy_server: Optional[str] = None
    browser_fallback_enabled: bool = False
    force_browser: bool = False


ScrapeFn = Callable[[str, ScrapeContext], List[Dict[str, Any]]]
BuildUrlFn = Callable[[str], str]
FetchMode = Literal["http", "browser"]


@dataclass(frozen=True, slots=True)
class SourcePlugin:
    """Defines a listing source.

    Plugins are declarative. The DB (`source_configs`) is the source of truth for
    runtime config (enabled/schedule/cooldown/rate-limit/proxy/browser flags).

    The `default_*` fields are only used as SEED values when a row is missing.
    """

    name: str
    build_url: BuildUrlFn
    scrape: Optional[ScrapeFn] = None

    # Behavior flags
    supports_manual_search: bool = True
    supports_wishlist_monitoring: bool = True

    # Ops hint
    fetch_mode: FetchMode = "http"

    # Defaults used only for DB seed
    default_enabled: bool = True
    default_sched_minutes: int = 60
    default_cooldown_minutes: int = 0
    default_rate_limit_seconds: int = 0
    default_proxy_server: Optional[str] = None
    default_browser_fallback_enabled: bool = False
    default_force_browser: bool = False
    default_extra: Optional[Dict[str, Any]] = None

    # Legacy wiring (kept for backward-compatibility; no longer used)
    enabled_setting: Optional[str] = None
    sched_minutes_setting: Optional[str] = None
    cooldown_minutes_setting: Optional[str] = None
    rate_limit_seconds_setting: Optional[str] = None
