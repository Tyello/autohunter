from __future__ import annotations

import os
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


def _get_session(proxy: Optional[str]) -> requests.Session:
    key = proxy or "__default__"
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
    backoff_factor=0.8,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False,
)

adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)


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


def _looks_like_bot_challenge(html: str) -> bool:
    h = html.lower()
    # Marcadores comuns de challenge / captcha.
    return (
        "captcha" in h
        or "verify you are" in h
        or "cloudflare" in h
        or "incapsula" in h
        or "datadome" in h
        or "perimeterx" in h
        or "access denied" in h
    )


def fetch_html(
    url: str,
    *,
    timeout: int = 25,
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

    # Pequeno delay randômico para reduzir padrão.
    delay = random.randint(min_delay_ms, max_delay_ms) / 1000.0
    time.sleep(delay)

    ua = random.choice(_DEFAULT_UAS)
    base_headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
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

    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    sess = _get_session(proxy)
    resp = sess.get(
        url,
        headers=base_headers,
        timeout=timeout,
        allow_redirects=True,
        proxies=proxies,
    )

    # Bloqueio explícito
    if resp.status_code in (403, 429):
        raise FetchBlocked(resp.status_code, url, reason="http_status")

    # Pode vir 200 com challenge no corpo
    if resp.status_code == 200 and _looks_like_bot_challenge(resp.text):
        raise FetchBlocked(200, url, reason="bot_challenge")

    resp.raise_for_status()
    return resp.text
