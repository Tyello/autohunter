from __future__ import annotations

import random
import time
import threading
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class FetchBlocked(Exception):
    def __init__(self, status_code: int, url: str, *, reason: str | None = None):
        msg = f"Blocked ({status_code}) for url={url}"
        if reason:
            msg += f" reason={reason}"
        super().__init__(msg)
        self.status_code = status_code
        self.url = url
        self.reason = reason


# Reutiliza sessão para manter cookies. Isso ajuda bastante em sites tipo OLX.
_sessions: dict[str, requests.Session] = {}
_sessions_lock = threading.Lock()


def _get_session(proxy: Optional[str], session_key: Optional[str] = None) -> requests.Session:
    sk = (session_key or "__global__").strip().lower() or "__global__"
    key = f"{sk}::{proxy or '__default__'}"
    with _sessions_lock:
        sess = _sessions.get(key)
        if sess is None:
            sess = _init_session(requests.Session())
            _sessions[key] = sess
        return sess


def get_session_stats() -> dict:
    with _sessions_lock:
        return {"sessions": len(_sessions), "keys": list(_sessions.keys())[:10]}


retries = Retry(
    total=2,
    connect=2,
    read=1,
    status=2,
    backoff_factor=0.6,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET", "HEAD"],
    raise_on_status=False,
    respect_retry_after_header=True,
)

# Pool smaller to save RAM on Raspberry Pi; block instead of spawning sockets.
adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10, pool_block=True)


def _init_session(sess: requests.Session) -> requests.Session:
    # Retry + connection pooling
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess

_DEFAULT_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def _ensure_session_fingerprint(sess: requests.Session) -> None:
    """Ensure a stable, browser-like fingerprint per Session.

    Some sites (notably OLX) are very sensitive to stateless traffic patterns.
    Rotating User-Agent on every request is a strong bot signal. We keep a
    consistent UA (and a few related headers) attached to the Session.
    """
    if not sess.headers.get("User-Agent"):
        sess.headers["User-Agent"] = random.choice(_DEFAULT_UAS)

    # Keep these stable too (requests will merge per-request headers on top).
    sess.headers.setdefault(
        "Accept",
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    )
    sess.headers.setdefault("Accept-Language", "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7")
    sess.headers.setdefault("Connection", "keep-alive")


def _looks_like_bot_challenge(html: str) -> bool:
    """Heuristic bot-challenge detection.

    Important: avoid false positives.
    Some legit pages contain the word "captcha" in scripts or footer.
    We only treat it as a challenge when paired with stronger markers.
    """
    h = (html or "").lower()

    cloudflare = (
        "cloudflare" in h and ("just a moment" in h or "cf-chl" in h or "checking your browser" in h)
    )
    incapsula = "incapsula" in h
    datadome = "datadome" in h and ("captcha" in h or "geetest" in h or "challenge" in h)
    perimeterx = "perimeterx" in h and ("captcha" in h or "px-captcha" in h or "challenge" in h)

    # Captcha-only markers (more specific than plain "captcha")
    captcha = (
        "hcaptcha" in h
        or "g-recaptcha" in h
        or ("recaptcha" in h and ("sitekey" in h or "data-sitekey" in h))
        or "data-sitekey" in h
    )

    access_denied = "access denied" in h
    verify = "verify you are" in h or "are you human" in h

    return bool(cloudflare or incapsula or datadome or perimeterx or captcha or access_denied or verify)

def _resolve_proxy(proxy: Optional[str], ctx: Optional[object]) -> Optional[str]:
    if proxy:
        return proxy
    if ctx is None:
        return None
    return getattr(ctx, 'proxy_server', None)

def _resolve_session_key(ctx: Optional[object]) -> Optional[str]:
    if ctx is None:
        return None
    src = getattr(ctx, 'source', None)
    return str(src).strip().lower() if src else None

def _resolve_delay(min_delay_ms: int, max_delay_ms: int, ctx: Optional[object]) -> tuple[int, int]:
    if ctx is None:
        return min_delay_ms, max_delay_ms
    mn = getattr(ctx, 'http_min_delay_ms', None)
    mx = getattr(ctx, 'http_max_delay_ms', None)
    try:
        mn_i = int(mn) if mn is not None else None
    except Exception:
        mn_i = None
    try:
        mx_i = int(mx) if mx is not None else None
    except Exception:
        mx_i = None
    return (mn_i if mn_i is not None else min_delay_ms, mx_i if mx_i is not None else max_delay_ms)

def _resolve_timeout(timeout: int | float | tuple[float, float], ctx: Optional[object]) -> tuple[float, float]:
    # ctx overrides
    if ctx is not None:
        ct = getattr(ctx, 'http_connect_timeout_s', None)
        rt = getattr(ctx, 'http_read_timeout_s', None)
        tt = getattr(ctx, 'http_timeout_s', None)
        try:
            if ct is not None or rt is not None:
                c = float(ct) if ct is not None else 5.0
                r = float(rt) if rt is not None else (float(tt) if tt is not None else 20.0)
                return (max(1.0, c), max(1.0, r))
            if tt is not None:
                t = float(tt)
                c = min(5.0, t) if t >= 5.0 else t
                return (max(1.0, c), max(1.0, t))
        except Exception:
            pass

    # Back-compat: int timeout means read timeout; connect is capped.
    if isinstance(timeout, (int, float)):
        t = float(timeout)
        c = min(5.0, t) if t >= 5.0 else t
        return (max(1.0, c), max(1.0, t))
    # already a tuple
    return (float(timeout[0]), float(timeout[1]))



def fetch_html(
    url: str,
    *,
    timeout: int | float | tuple[float, float] = 25,
    ctx: Optional[object] = None,
    headers: Optional[dict] = None,
    referer: Optional[str] = None,
    proxy: Optional[str] = None,
    min_delay_ms: int = 150,
    max_delay_ms: int = 450,
) -> str:
    """Fetch HTML with basic anti-block hardening.

    - Reuses a global Session (cookies)
    - Adds more browser-like headers
    - Adds small randomized delay
    - Detects bot challenges in body

    Proxies:
    - If proxy is provided, it will be used for both HTTP and HTTPS.
    - Requests also respects HTTP(S)_PROXY env vars automatically.
    """

    base_headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        # Sec-CH (não garante, mas ajuda parecer navegador moderno)
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    if referer:
        base_headers["Referer"] = referer

    if headers:
        base_headers.update(headers)

    resp = fetch_response(
        url,
        timeout=timeout,
        ctx=ctx,
        headers=base_headers,
        proxy=proxy,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
    )
    return resp.text


def fetch_response(
    url: str,
    *,
    timeout: int | float | tuple[float, float] = 25,
    ctx: Optional[object] = None,
    headers: Optional[dict] = None,
    referer: Optional[str] = None,
    proxy: Optional[str] = None,
    min_delay_ms: int = 150,
    max_delay_ms: int = 450,
    allow_redirects: bool = True,
    _skip_delay: bool = False,
) -> requests.Response:
    """Low-level GET that returns the Response.

    Why it exists:
    - Some sources are JS-heavy but expose JSON/XHR endpoints.
    - We want the same session/cookie stickiness + jitter + retry/backoff.

    Notes:
    - Keep requests stateless at the *process* level, but stateful at the *Session* level.
    - Retry/backoff is handled by the Session adapter (urllib3 Retry).
    """

    if not _skip_delay:
        mn, mx = _resolve_delay(min_delay_ms, max_delay_ms, ctx)
        delay = random.randint(mn, mx) / 1000.0
        time.sleep(delay)

    proxy = _resolve_proxy(proxy, ctx)
    sess = _get_session(proxy, _resolve_session_key(ctx))
    _ensure_session_fingerprint(sess)

    base_headers = {}
    if referer:
        base_headers["Referer"] = referer
    if headers:
        base_headers.update(headers)

    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    req_timeout = _resolve_timeout(timeout, ctx)

    resp = sess.get(
        url,
        headers=base_headers,
        timeout=req_timeout,
        allow_redirects=allow_redirects,
        proxies=proxies,
    )

    # Bloqueio explícito
    if resp.status_code in (403, 429):
        raise FetchBlocked(resp.status_code, url, reason="http_status")

    # Pode vir 200 com challenge no corpo
    if resp.status_code == 200 and _looks_like_bot_challenge(resp.text):
        raise FetchBlocked(200, url, reason="bot_challenge")

    resp.raise_for_status()
    return resp


def fetch_json(
    url: str,
    *,
    timeout: int | float | tuple[float, float] = 25,
    ctx: Optional[object] = None,
    headers: Optional[dict] = None,
    referer: Optional[str] = None,
    proxy: Optional[str] = None,
    min_delay_ms: int = 150,
    max_delay_ms: int = 450,
):
    """Fetch JSON from an XHR/internal endpoint.

    - Reuses the same cookie-sticky Session as fetch_html.
    - Adds browser-like headers for XHR.
    - Uses Retry(backoff) from the mounted adapter.
    """

    base_headers = {
        "Accept": "application/json, text/plain, */*",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        # XHR-ish
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    if referer:
        base_headers["Referer"] = referer
    if headers:
        base_headers.update(headers)

    resp = fetch_response(
        url,
        timeout=timeout,
        ctx=ctx,
        headers=base_headers,
        proxy=proxy,
        min_delay_ms=min_delay_ms,
        max_delay_ms=max_delay_ms,
    )

    try:
        return resp.json()
    except Exception:
        # Fallback para JSON em string
        import json as _json

        return _json.loads(resp.text)


