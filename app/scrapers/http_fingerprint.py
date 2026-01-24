from __future__ import annotations

from typing import Optional, Tuple, Dict

from app.scrapers.base import FetchBlocked

try:
    # curl_cffi gives us a much more browser-like TLS fingerprint than requests.
    from curl_cffi import requests as crequests  # type: ignore
except Exception:  # pragma: no cover
    crequests = None


def _looks_like_bot_challenge(html: str) -> bool:
    h = (html or "").lower()
    return (
        "captcha" in h
        or "verify you are" in h
        or "cloudflare" in h
        or "attention required" in h
        or "incapsula" in h
        or "datadome" in h
        or "perimeterx" in h
        or "access denied" in h
    )


def fetch_html_impersonate(
    url: str,
    *,
    timeout: int = 25,
    referer: Optional[str] = None,
    proxy: Optional[str] = None,
    cookies: Optional[Dict[str, str]] = None,
    min_delay_ms: int = 150,
    max_delay_ms: int = 450,
    impersonate: str = "chrome120",
) -> str:
    """HTTP fetch with browser-like TLS fingerprint.

    Uses curl_cffi when available. Falls back to raising FetchBlocked if not.
    (Callers can then fall back to Playwright.)
    """
    if crequests is None:
        raise FetchBlocked(0, url, reason="curl_cffi_not_installed")

    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    if referer:
        headers["Referer"] = referer

    # small jitter to reduce patterns
    import random, time
    time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

    s = crequests.Session()
    s.headers.update(headers)

    if proxy:
        # curl_cffi uses 'proxies' mapping like requests
        s.proxies = {"http": proxy, "https": proxy}
    if cookies:
        s.cookies.update(cookies)

    r = s.get(url, timeout=timeout, allow_redirects=True, impersonate=impersonate)
    text = r.text or ""

    if r.status_code in (403, 429) or (r.status_code == 200 and _looks_like_bot_challenge(text)):
        raise FetchBlocked(r.status_code or 0, url, reason="cf_block_or_challenge")

    return text
