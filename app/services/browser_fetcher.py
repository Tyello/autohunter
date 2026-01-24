from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from app.scrapers.base import FetchBlocked
from app.services.playwright_pool import get_playwright_pool

if TYPE_CHECKING:
    from app.sources.types import ScrapeContext


@dataclass
class BrowserFetchResult:
    html: str
    final_url: str


@dataclass
class BrowserJsonFetchResult:
    data: dict
    final_url: str
    data_url: str


def _looks_like_bot_challenge(html: str) -> bool:
    h = html.lower()
    return (
        "captcha" in h
        or "verify you are" in h
        or "cloudflare" in h
        or "incapsula" in h
        or "datadome" in h
        or "perimeterx" in h
        or "access denied" in h
    )


def fetch_html_browser(
    url: str,
    *,
    ctx: "ScrapeContext",
    timeout_ms: int = 30000,
    wait_until: str = "networkidle",
    min_delay_ms: int = 250,
    max_delay_ms: int = 900,
) -> BrowserFetchResult:
    """Render a page in a real browser (Playwright) and return the resulting HTML.

    This is the escape hatch for SPA/JS-heavy sources (Webmotors/GoGarage) and
    for sources that frequently block simple HTTP clients (OLX).

    Requirements:
    - pip install playwright
    - playwright install chromium

    Env:
    - PLAYWRIGHT_HEADLESS=true|false (default true)
    """

    # small random delay to reduce patterns
    time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

    pool = get_playwright_pool()
    r = pool.fetch(
        url,
        source=ctx.source,
        proxy_server=ctx.proxy_server,
        timeout_ms=timeout_ms,
        wait_until=wait_until,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
    )
    html = r.html
    final_url = r.final_url

    if _looks_like_bot_challenge(html):
        raise FetchBlocked(200, url, reason="bot_challenge")

    return BrowserFetchResult(html=html, final_url=final_url)


def fetch_json_browser(
    url: str,
    *,
    ctx: "ScrapeContext",
    timeout_ms: int = 30000,
    wait_until: str = "domcontentloaded",
    json_url_predicate: Optional[Callable[[str, dict, int], bool]] = None,
    min_delay_ms: int = 250,
    max_delay_ms: int = 900,
) -> BrowserJsonFetchResult:
    """Navigate in a real browser and capture a JSON response.

    Use this when HTTP clients are blocked (e.g., Cloudflare) but the data is
    available as an internal XHR/JSON response (e.g., Next.js _next/data).
    """

    time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

    pool = get_playwright_pool()
    r = pool.fetch_json(
        url,
        source=ctx.source,
        proxy_server=ctx.proxy_server,
        timeout_ms=timeout_ms,
        wait_until=wait_until,
        json_url_predicate=json_url_predicate,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
    )

    # If the captured JSON is actually an HTML bot-challenge serialized or similar,
    # treat as blocked. In practice, we rely on content-type filtering, but keep a guard.
    as_text = ""  # only used for heuristic checks
    try:
        as_text = json.dumps(r.data)[:2000].lower()
    except Exception:
        pass
    if as_text and _looks_like_bot_challenge(as_text):
        raise FetchBlocked(200, url, reason="bot_challenge")

    return BrowserJsonFetchResult(data=r.data, final_url=r.final_url, data_url=r.data_url)
