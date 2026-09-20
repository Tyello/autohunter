from __future__ import annotations

import json
import random
import threading
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


_DISPATCH_LOCK = threading.Lock()
_DISPATCH_SEMAPHORE: Optional[threading.Semaphore] = None
_DISPATCH_SEMAPHORE_SIZE: Optional[int] = None


def _get_dispatch_semaphore() -> threading.Semaphore:
    """Global gate on concurrent Playwright fetch/fetch_json dispatches.

    Multiple scraper groups/sources can call fetch_html_browser concurrently
    (source_group_max_workers, multiple parallel sources), but the pool has a
    single worker thread. Without this gate, every caller submits at once and
    queues invisibly inside the pool, each racing its own hard-timeout against
    however many others are ahead of it. Serializing dispatch here makes the
    wait explicit (and cheap: no ctx/page created yet) and keeps each fetch's
    own timeout meaningful again.
    """
    global _DISPATCH_SEMAPHORE, _DISPATCH_SEMAPHORE_SIZE
    size = max(1, int(getattr(settings, "playwright_max_inflight_dispatches", 1) or 1))
    with _DISPATCH_LOCK:
        if _DISPATCH_SEMAPHORE is None or _DISPATCH_SEMAPHORE_SIZE != size:
            _DISPATCH_SEMAPHORE = threading.Semaphore(size)
            _DISPATCH_SEMAPHORE_SIZE = size
        return _DISPATCH_SEMAPHORE


def _should_reset_after_failure(backend, err: Exception) -> bool:
    """Decide whether a fetch failure warrants tearing down the whole pool.

    - target_closed errors mean the browser/context actually died: always worth resetting.
    - timeout errors are ambiguous: they can mean a genuinely wedged worker, but with
      dispatch now serialized (see _get_dispatch_semaphore) they usually just mean the one
      in-flight call was slow. The proactive heartbeat watchdog
      (browser_watchdog_job.job_browser_worker_heartbeat_watchdog) already resets a
      genuinely wedged worker within browser_worker_wedge_threshold_seconds independently
      of any caller, so only reset here if the worker is *currently* wedged past that same
      threshold -- otherwise this reactive path just adds a redundant, disruptive reset
      (killing every source's contexts) on top of an ordinary slow fetch.
    """
    if _is_target_closed_error(err):
        return True
    if not _is_timeout_error(err):
        return False
    if not hasattr(backend, "check_wedged"):
        return True  # can't tell (e.g. external browser_service client): fail safe
    try:
        threshold = float(getattr(settings, "browser_worker_wedge_threshold_seconds", 150) or 150)
        return bool(backend.check_wedged(threshold_seconds=threshold).get("wedged"))
    except Exception:
        return True


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
    if s == "chavesnamao":
        # networkidle raramente é atingido em 25s (scripts de ads/analytics
        # mantêm requisições em background); 40s reduz falso-positivo de
        # timeout sem mudar wait_until (cards hidratam client-side).
        return max(int(timeout_ms or 0), 40000)
    return int(timeout_ms or 0)


def _resolve_block_resources(ctx: "ScrapeContext", block_resources: Optional[bool]) -> bool:
    if block_resources is not None:
        return bool(block_resources)
    if getattr(ctx, "browser_block_resources", None) is not None:
        return bool(ctx.browser_block_resources)
    return True




def reset_browser_state_for_source(
    source: str,
    ctx: "ScrapeContext",
    *,
    block_resources: Optional[bool] = None,
    clear_storage: bool = False,
) -> None:
    backend = _get_backend()
    source_name = (source or getattr(ctx, "source", "") or "").strip().lower()
    proxy_server = getattr(ctx, "proxy_server", None)
    should_block = _resolve_block_resources(ctx, block_resources)

    if hasattr(backend, "invalidate_contexts"):
        backend.invalidate_contexts(
            source=source_name,
            proxy_server=proxy_server,
            block_resources=should_block,
            clear_storage=clear_storage,
        )

def fetch_html_browser(
        url: str,
        *,
        ctx: "ScrapeContext",
        timeout_ms: int = 30000,
        wait_until: str = "networkidle",
        min_delay_ms: int = 250,
        max_delay_ms: int = 900,
        block_resources: Optional[bool] = None,
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
    dispatch_timeout_s = max(10.0, (timeout_ms / 1000.0) + 20.0)
    sem = _get_dispatch_semaphore()
    # One retry on timeout helps unstable sources (e.g., Webmotors) without burning Pi resources.
    for attempt in range(2):
        if not sem.acquire(timeout=dispatch_timeout_s):
            last_exc = TimeoutError(
                f"Playwright dispatch semaphore timed out waiting for a free slot (source={ctx.source})."
            )
            if diag is not None:
                diag.inc("br_err")
                diag.note("br_last_error", type(last_exc).__name__)
            if attempt == 0:
                continue
            raise last_exc
        try:
            r = backend.fetch(
                url,
                source=ctx.source,
                proxy_server=ctx.proxy_server,
                timeout_ms=timeout_ms,
                wait_until=wait_until,
                min_delay_ms=min_delay_ms,
                max_delay_ms=max_delay_ms,
                block_resources=_resolve_block_resources(ctx, block_resources),
            )
            break
        except Exception as e:  # pragma: no cover
            last_exc = e
            if diag is not None:
                diag.inc("br_err")
                diag.note("br_last_error", type(e).__name__)
            if _should_reset_after_failure(backend, e) and hasattr(backend, 'reset'):
                try:
                    backend.reset()
                except Exception:
                    pass
            if attempt == 0 and (_is_target_closed_error(e) or _is_timeout_error(e)):
                if _is_timeout_error(e):
                    time.sleep(0.35 + random.random() * 0.65)
                continue
            raise
        finally:
            sem.release()

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
        block_resources: Optional[bool] = None,
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
    dispatch_timeout_s = max(10.0, (timeout_ms / 1000.0) + 20.0)
    sem = _get_dispatch_semaphore()
    for attempt in range(2):
        if not sem.acquire(timeout=dispatch_timeout_s):
            last_exc = TimeoutError(
                f"Playwright dispatch semaphore timed out waiting for a free slot (source={ctx.source})."
            )
            if diag is not None:
                diag.inc("br_err")
                diag.note("br_last_error", type(last_exc).__name__)
            if attempt == 0:
                continue
            raise last_exc
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
                block_resources=_resolve_block_resources(ctx, block_resources),
            )
            break
        except Exception as e:  # pragma: no cover
            last_exc = e
            if diag is not None:
                diag.inc("br_err")
                diag.note("br_last_error", type(e).__name__)
            if _should_reset_after_failure(backend, e) and hasattr(backend, 'reset'):
                try:
                    backend.reset()
                except Exception:
                    pass
            if attempt == 0 and (_is_target_closed_error(e) or _is_timeout_error(e)):
                if _is_timeout_error(e):
                    time.sleep(0.35 + random.random() * 0.65)
                continue
            raise
        finally:
            sem.release()

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
