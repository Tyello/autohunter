import random
import time
import requests


DEFAULT_HEADERS = {
    "User-Agent": "AutoHunterBot/0.1 (+https://example.local)",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def fetch_html(url: str, timeout: int = 20) -> str:
    # jitter mínimo para não martelar
    time.sleep(random.uniform(0.3, 0.9))

    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text
