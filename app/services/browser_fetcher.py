from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from app.scrapers.base import FetchBlocked
from app.services.source_audit_capture_service import source_audit_capture_service
from app.scrapers.diagnostics import current_diagnostics
from app.core.settings import settings
from app.services.challenge_fingerprint import fingerprint_from_html


def _allowed_playwright_sources() -> set[str]:
    raw = (getattr(settings, "playwright_sources", "") or "").strip().lower()
    # Empty means "no restriction" (DB/runtime flags decide whether to use the browser).
    if not raw:
        return {"*"}
    if raw in ("*", "all", "any"):
        return {"*"}
    if raw in ("none", "off", "false", "0"):
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def _playwright_allowed_for(source: str) -> bool:
    allowed = _allowed_playwright_sources()
    if "*" in allowed:
        return True
    return (source or "").strip().lower() in allowed
def _get_backend():
    # If configured, use external browser service. Otherwise, use in-process pool.
    if getattr(settings, 'playwright_endpoint', None):
        from app.services.playwright_client import get_playwright_client
        return get_playwright_client()
    from app.services.playwright_pool import get_playwright_pool
    return get_playwright_pool()


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
    """Heuristic bot-challenge detection (browser).

    Keep it conservative to avoid false positives.
    """
    h = (html or "").lower()

    cloudflare = (
        "cloudflare" in h and ("just a moment" in h or "cf-chl" in h or "checking your browser" in h)
    )
    incapsula = "incapsula" in h
    datadome = "datadome" in h and ("captcha" in h or "geetest" in h or "challenge" in h)
    perimeterx = "perimeterx" in h and ("captcha" in h or "px-captcha" in h or "challenge" in h)
    captcha = (
        "hcaptcha" in h
        or "g-recaptcha" in h
        or ("recaptcha" in h and ("sitekey" in h or "data-sitekey" in h))
        or "data-sitekey" in h
    )
    access_denied = "access denied" in h
    verify = "verify you are" in h or "are you human" in h

    return bool(cloudflare or incapsula or datadome or perimeterx or captcha or access_denied or verify)


def _is_target_closed_error(err: Exception) -> bool:
    msg = str(err).lower()
    return (
            "target page, context or browser has been closed" in msg
            or ("browsercontext.new_page" in msg and "has been closed" in msg)
            or "target closed" in msg
            or "browser has been closed" in msg
    )


def _is_timeout_error(err: Exception) -> bool:
    """Best-effort timeout detection for both Playwright and network layers."""
    if isinstance(err, TimeoutError):
        return True
    msg = str(err).lower()
    return (
        "timed out" in msg
        or "timeout" in msg
        or "err_timed_out" in msg
        or "navigation timeout" in msg
        or "playwright worker timed out" in msg
        or "net::err_timed_out" in msg
    )


def _effective_timeout_ms(source: str, timeout_ms: int) -> int:
    """Source-specific bump for slow/hostile sites."""
    s = (source or "").strip().lower()
    if s == "webmotors":
        return max(int(timeout_ms or 0), 60000)
    return int(timeout_ms or 0)


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

    diag = current_diagnostics()
    if diag is not None:
        diag.inc("br_req")
        diag.flag("browser_used", True)
        if url:
            diag.note("last_browser_url", url)

    # small random delay to reduce patterns

    if not _playwright_allowed_for(ctx.source):
        if diag is not None:
            diag.inc("br_err")
            diag.note("br_last_error", "PlaywrightSourcesRestricted")
        raise RuntimeError(f"Playwright disabled for source='{ctx.source}'. Set PLAYWRIGHT_SOURCES to enable.")

    timeout_ms = _effective_timeout_ms(ctx.source, timeout_ms)

    time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

    backend = _get_backend()

    last_exc: Optional[Exception] = None
    # One retry on timeout helps unstable sources (e.g., Webmotors) without burning Pi resources.
    for attempt in range(2):
        try:
            r = backend.fetch(
                url,
                source=ctx.source,
                proxy_server=ctx.proxy_server,
                timeout_ms=timeout_ms,
                wait_until=wait_until,
                min_delay_ms=min_delay_ms,
                max_delay_ms=max_delay_ms,
            )
            break
        except Exception as e:  # pragma: no cover
            last_exc = e
            if diag is not None:
                diag.inc("br_err")
                diag.note("br_last_error", type(e).__name__)
            if _is_target_closed_error(e) and hasattr(backend, 'reset'):
                try:
                    backend.reset()
                except Exception:
                    pass
                continue
            if attempt == 0 and _is_timeout_error(e):
                time.sleep(0.35 + random.random() * 0.65)
                continue
            raise

    if last_exc is not None and 'r' not in locals():
        raise last_exc
    html = r.html
    final_url = r.final_url

    if _looks_like_bot_challenge(html):
        if diag is not None:
            diag.flag("blocked", True)
            diag.inc("blocked_browser")
            diag.note("blocked_reason", "bot_challenge")
        fp = fingerprint_from_html(html, final_url=url)
        if fp:
            raise FetchBlocked(
                200,
                url,
                reason=(
                    "bot_challenge_fingerprint"
                    f" provider={fp.provider}"
                    f" title={fp.title}"
                    f" final_url={fp.final_url}"
                    f" snippet={fp.snippet[:160]}"
                ),
            )
        raise FetchBlocked(200, url, reason="bot_challenge")

    if diag is not None:
        diag.inc("br_ok")

    try:
        source_audit_capture_service.register_runtime_fetch_sample(
            ctx=ctx,
            source=ctx.source,
            kind="detail" if ("/item/" in (url or "") or "anuncio" in (url or "")) else "listing",
            url=url,
            payload=html,
            content_type="text/html",
            stage="browser_fetch_html",
        )
    except Exception:
        pass

    return BrowserFetchResult(html=html, final_url=final_url)


def fetch_json_browser(
        url: str,
        *,
        ctx: "ScrapeContext",
        timeout_ms: int = 30000,
        wait_until: str = "domcontentloaded",
        capture_mode: str = "any_json",
        json_url_predicate: Optional[Callable[[str, dict, int], bool]] = None,
        min_delay_ms: int = 250,
        max_delay_ms: int = 900,
) -> BrowserJsonFetchResult:
    """Navigate in a real browser and capture a JSON response.

    Use this when HTTP clients are blocked (e.g., Cloudflare) but the data is
    available as an internal XHR/JSON response (e.g., Next.js _next/data).
    """


    diag = current_diagnostics()
    if diag is not None:
        diag.inc("br_req")
        diag.flag("browser_used", True)
        if url:
            diag.note("last_browser_url", url)

    if not _playwright_allowed_for(ctx.source):
        if diag is not None:
            diag.inc("br_err")
            diag.note("br_last_error", "PlaywrightSourcesRestricted")
        raise RuntimeError(f"Playwright disabled for source='{ctx.source}'. Set PLAYWRIGHT_SOURCES to enable.")

    timeout_ms = _effective_timeout_ms(ctx.source, timeout_ms)

    time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

    backend = _get_backend()
    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            r = backend.fetch_json(
                url,
                source=ctx.source,
                proxy_server=ctx.proxy_server,
                timeout_ms=timeout_ms,
                wait_until=wait_until,
                capture_mode=capture_mode,
                # json_url_predicate is only supported in-process; prefer capture_mode.
                json_url_predicate=json_url_predicate,
                min_delay_ms=min_delay_ms,
                max_delay_ms=max_delay_ms,
            )
            break
        except Exception as e:  # pragma: no cover
            last_exc = e
            if diag is not None:
                diag.inc("br_err")
                diag.note("br_last_error", type(e).__name__)
            if _is_target_closed_error(e) and hasattr(backend, 'reset'):
                try:
                    backend.reset()
                except Exception:
                    pass
                continue
            if attempt == 0 and _is_timeout_error(e):
                time.sleep(0.35 + random.random() * 0.65)
                continue
            raise

    if last_exc is not None and 'r' not in locals():
        raise last_exc

    # If the captured JSON is actually an HTML bot-challenge serialized or similar,
    # treat as blocked. In practice, we rely on content-type filtering, but keep a guard.
    as_text = ""  # only used for heuristic checks
    try:
        as_text = json.dumps(r.data)[:2000].lower()
    except Exception:
        pass
    if as_text and _looks_like_bot_challenge(as_text):
        if diag is not None:
            diag.flag("blocked", True)
            diag.inc("blocked_browser")
            diag.note("blocked_reason", "bot_challenge")
        raise FetchBlocked(200, url, reason="bot_challenge")

    if diag is not None:
        diag.inc("br_ok")

    return BrowserJsonFetchResult(data=r.data, final_url=r.final_url, data_url=r.data_url)
