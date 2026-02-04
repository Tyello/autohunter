from __future__ import annotations

from typing import Optional

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_html
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


def fetch_html_with_browser_fallback(
    url: str,
    *,
    ctx: ScrapeContext,
    timeout: int | float = 25,
    referer: Optional[str] = None,
    proxy: Optional[str] = None,
    min_delay_ms: int = 150,
    max_delay_ms: int = 450,
    wait_until: str = "domcontentloaded",
    timeout_ms: Optional[int] = None,
    browser_min_delay_ms: Optional[int] = None,
    browser_max_delay_ms: Optional[int] = None,
    allow_browser_fallback: bool = True,
) -> str:
    """Fetch HTML via HTTP and fallback to Playwright when available."""

    def _fetch_browser() -> str:
        res = fetch_html_browser(
            url,
            ctx=ctx,
            timeout_ms=timeout_ms or int(timeout * 1000),
            wait_until=wait_until,
            min_delay_ms=browser_min_delay_ms or 250,
            max_delay_ms=browser_max_delay_ms or 900,
        )
        return res.html

    if settings.enable_playwright and getattr(ctx, "force_browser", False):
        return _fetch_browser()

    try:
        return fetch_html(
            url,
            ctx=ctx,
            timeout=timeout,
            referer=referer,
            proxy=proxy,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
        )
    except FetchBlocked:
        if not (settings.enable_playwright and allow_browser_fallback):
            raise
    except Exception:
        if not (settings.enable_playwright and allow_browser_fallback):
            raise

    return _fetch_browser()
