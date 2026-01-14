import random
import time
import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

class FetchBlocked(Exception):
    pass


def fetch_html(url: str, timeout: int = 20) -> str:
    time.sleep(random.uniform(0.3, 0.9))

    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)

    # OLX frequentemente retorna 403 se detectar automação
    if resp.status_code in (403, 429):
        raise FetchBlocked(f"Blocked ({resp.status_code}) for url={url}")

    resp.raise_for_status()
    return resp.text
