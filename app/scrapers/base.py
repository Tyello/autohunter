from __future__ import annotations

import random
from typing import Optional
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

import requests


class FetchBlocked(Exception):
    def __init__(self, status_code: int, url: str):
        super().__init__(f"Blocked ({status_code}) for url={url}")
        self.status_code = status_code
        self.url = url


_session = requests.Session()

# Retry só para falhas transitórias. 403 normalmente NÃO é transitório, mas
# vale para 429/5xx.
retries = Retry(
    total=2,
    backoff_factor=0.8,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False,
)

adapter = HTTPAdapter(max_retries=retries)
_session.mount("https://", adapter)
_session.mount("http://", adapter)


_DEFAULT_UAS = [
    # UAs reais (básico). Você pode adicionar mais.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def fetch_html(url: str, *, timeout: int = 25, headers: Optional[dict] = None) -> str:
    ua = random.choice(_DEFAULT_UAS)
    base_headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if headers:
        base_headers.update(headers)

    # session simples (ajuda cookies básicos)
    with requests.Session() as s:
        resp = s.get(url, headers=base_headers, timeout=timeout, allow_redirects=True)

    if resp.status_code in (403, 429):
        raise FetchBlocked(f"Blocked ({resp.status_code}) for url={url}")

    resp.raise_for_status()
    return resp.text
