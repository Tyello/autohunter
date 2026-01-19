from __future__ import annotations

import random
import time
from dataclasses import dataclass

from app.scrapers.base import FetchBlocked
from app.services.playwright_pool import get_playwright_pool
from app.sources.types import ScrapeContext


@dataclass
class BrowserFetchResult:
    html: str
    final_url: str


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
    ctx: ScrapeContext,

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
