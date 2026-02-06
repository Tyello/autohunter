from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_html
from app.scrapers.diagnostics import current_diagnostics
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


@dataclass
class FetchPage:
    html: str
    final_url: str


def _ctx_http_timeout_s(ctx: ScrapeContext, default_s: int | float) -> float:
    # base.fetch_html already resolves connect/read using ctx.http_* fields.
    # Here we only need a single number for callers that want "seconds".
    t = getattr(ctx, "http_timeout_s", None)
    if t is None:
        return float(default_s)
    try:
        return float(t)
    except Exception:
        return float(default_s)


def fetch_page(
    url: str,
    *,
    ctx: ScrapeContext,
    timeout_s: int | float = 25,
    referer: Optional[str] = None,
    proxy: Optional[str] = None,
    allow_browser_fallback: bool = True,
    wait_until: Optional[str] = None,
    timeout_ms: Optional[int] = None,
) -> FetchPage:
    """Fetch a page via HTTP and optionally fallback to Playwright.

    Rules:
    - If ctx.force_browser: browser first.
    - Else: HTTP first, then (optionally) browser on blocked/errors.

    All jitter/timeout overrides come from ScrapeContext (DB-driven).
    """

    diag = current_diagnostics()

    def _fetch_browser(*, fallback: bool = False) -> FetchPage:
        if diag is not None:
            if fallback:
                diag.flag("browser_fallback", True)
            diag.flag("browser_used", True)
        _wait = wait_until or getattr(ctx, "browser_wait_until", None) or "domcontentloaded"
        _timeout_ms = int(timeout_ms or getattr(ctx, "browser_timeout_ms", None) or (timeout_s * 1000))
        min_delay_ms = int(getattr(ctx, "browser_min_delay_ms", None) or 250)
        max_delay_ms = int(getattr(ctx, "browser_max_delay_ms", None) or 900)
        res = fetch_html_browser(
            url,
            ctx=ctx,
            timeout_ms=_timeout_ms,
            wait_until=_wait,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
        )
        return FetchPage(html=res.html, final_url=res.final_url)

    if settings.enable_playwright and bool(getattr(ctx, "force_browser", False)):
        if diag is not None:
            diag.flag("browser_forced", True)
        return _fetch_browser(fallback=False)

    try:
        html = fetch_html(
            url,
            ctx=ctx,
            timeout=_ctx_http_timeout_s(ctx, timeout_s),
            referer=referer,
            proxy=proxy,
        )
        return FetchPage(html=html, final_url=url)
    except FetchBlocked:
        if not (settings.enable_playwright and allow_browser_fallback and bool(getattr(ctx, "browser_fallback_enabled", False))):
            raise
        # blocked -> browser fallback
        return _fetch_browser(fallback=True)
    except Exception:
        if not (settings.enable_playwright and allow_browser_fallback and bool(getattr(ctx, "browser_fallback_enabled", False))):
            raise
        return _fetch_browser(fallback=True)

    return _fetch_browser(fallback=True)


# Backwards compatible alias (used by older scrapers)

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
    # Map legacy args into ctx overrides only for this call.
    # We do NOT mutate ctx (frozen dataclass).

    # If the caller explicitly provides browser delays, use them.
    # Otherwise use ctx defaults.
    effective_timeout_s = float(timeout)
    effective_wait_until = wait_until
    effective_timeout_ms = timeout_ms

    # For HTTP min/max delay: base.fetch_html already reads from ctx.http_min_delay_ms/http_max_delay_ms.
    # Legacy scrapers could pass custom values; we preserve them by using fetch_html directly.

    diag = current_diagnostics()

    def _fetch_browser(*, fallback: bool = False) -> str:
        if diag is not None:
            if fallback:
                diag.flag("browser_fallback", True)
            diag.flag("browser_used", True)
        res = fetch_html_browser(
            url,
            ctx=ctx,
            timeout_ms=int(effective_timeout_ms or int(effective_timeout_s * 1000)),
            wait_until=effective_wait_until,
            min_delay_ms=int(browser_min_delay_ms or 250),
            max_delay_ms=int(browser_max_delay_ms or 900),
        )
        return res.html

    if settings.enable_playwright and bool(getattr(ctx, "force_browser", False)):
        if diag is not None:
            diag.flag("browser_forced", True)
        return _fetch_browser(fallback=False)

    try:
        return fetch_html(
            url,
            ctx=ctx,
            timeout=effective_timeout_s,
            referer=referer,
            proxy=proxy,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
        )
    except FetchBlocked:
        if not (settings.enable_playwright and allow_browser_fallback and bool(getattr(ctx, "browser_fallback_enabled", False))):
            raise
    except Exception:
        if not (settings.enable_playwright and allow_browser_fallback and bool(getattr(ctx, "browser_fallback_enabled", False))):
            raise

    return _fetch_browser(fallback=True)
