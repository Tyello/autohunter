from bs4 import BeautifulSoup
from typing import List, Dict, Any
from urllib.parse import urlparse

from app.scrapers.base import fetch_html
from app.scrapers.parsing import parse_brl_price


def _extract_external_id_from_url(url: str) -> str:
    # OLX costuma ter um ID no final do path (varia)
    path = urlparse(url).path.strip("/")
    if not path:
        return url
    return path.split("-")[-1] if "-" in path else path


def scrape_olx(search_url: str) -> List[Dict[str, Any]]:
    html = fetch_html(search_url)
    soup = BeautifulSoup(html, "lxml")

    items: List[Dict[str, Any]] = []

    # tentativa: anchors de card
    cards = soup.select("a[data-lurker-detail='list_id']") or soup.select("a")

    seen = set()
    for a in cards:
        href = a.get("href")
        if not href or "http" not in href:
            continue

        url = href.split("#")[0]
        if url in seen:
            continue
        seen.add(url)

        # tente extrair título e preço dentro do card
        title_el = a.select_one("h2") or a.select_one("h3")
        title = title_el.get_text(strip=True) if title_el else None

        price_el = a.find(string=lambda s: isinstance(s, str) and "R$" in s)
        price = parse_brl_price(price_el) if price_el else None

        img = a.select_one("img")
        thumb = img.get("data-src") or img.get("src") if img else None

        items.append({
            "source": "olx",
            "external_id": _extract_external_id_from_url(url),
            "title": title,
            "url": url,
            "thumbnail_url": thumb,
            "price": price,
            "currency": "BRL",
            "location": None,
        })

        if len(items) >= 50:
            break

    return items
