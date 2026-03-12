from __future__ import annotations

from typing import Optional

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_html
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_BLOCKED_HTTP_CODES = {403, 429}


def _is_blocked_error(exc: Exception) -> bool:
    if isinstance(exc, FetchBlocked):
        if exc.status_code in _BLOCKED_HTTP_CODES:
            return True
        return (exc.reason or "") in {"bot_challenge", "http_status"}
    msg = str(exc).lower()
    return any(k in msg for k in ("captcha", "cloudflare", "challenge", "access denied"))




def _set_ctx_diag(ctx: ScrapeContext, **values: object) -> None:
    for k, v in values.items():
        try:
            object.__setattr__(ctx, k, v)
        except Exception:
            pass

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
    """Hybrid fetch: HTTP first, browser warmup only on block, then HTTP retry once.

    Last resort returns browser HTML only when retry HTTP still fails.
    """

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

    _set_ctx_diag(ctx, _hybrid_browser_used=False, _hybrid_blocked=False, _hybrid_blocked_status=None)

    if settings.enable_playwright and getattr(ctx, "force_browser", False):
        _set_ctx_diag(ctx, _hybrid_browser_used=True)
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
    except Exception as first_exc:
        if not (settings.enable_playwright and allow_browser_fallback):
            raise
        if not _is_blocked_error(first_exc):
            raise

        _set_ctx_diag(ctx, _hybrid_blocked=True)

        # 1) Browser warmup to refresh storage_state/cookies.
        try:
            browser_html = _fetch_browser()
        except FetchBlocked as warm_exc:
            _set_ctx_diag(ctx, _hybrid_browser_used=True, _hybrid_blocked_status=warm_exc.status_code)
            raise FetchBlocked(warm_exc.status_code, url, reason="blocked_after_browser_warmup") from warm_exc

        _set_ctx_diag(ctx, _hybrid_browser_used=True)

        # 2) Retry HTTP once (base.fetch_html now injects storage_state cookies automatically).
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
        except Exception as second_exc:
            if not _is_blocked_error(second_exc):
                raise
            # 3) Last resort: return browser HTML.
            _set_ctx_diag(ctx, _hybrid_browser_used=True, _hybrid_blocked_status=getattr(second_exc, "status_code", None))
            return browser_html
