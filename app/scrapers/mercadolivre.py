from bs4 import BeautifulSoup
from typing import List, Dict, Any
from urllib.parse import urlparse, parse_qs

from app.scrapers.base import fetch_html
from app.scrapers.parsing import parse_brl_price


def _extract_external_id_from_url(url: str) -> str:
    # ML costuma ter ID no path (ex: /MLB-1234567890-...)
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    for p in parts:
        if "MLB-" in p:
            return p.split("-")[0] if p.startswith("MLB-") else p
    # fallback: tenta query params
    qs = parse_qs(urlparse(url).query)
    return (qs.get("item_id") or [""])[0] or url


def scrape_mercadolivre(search_url: str) -> List[Dict[str, Any]]:
    """
    search_url deve ser uma URL de busca do Mercado Livre (HTML público).
    Retorna lista de dicts normalizados para car_listings.
    """
    html = fetch_html(search_url)
    soup = BeautifulSoup(html, "lxml")

    items: List[Dict[str, Any]] = []

    # tenta capturar cards comuns
    # dependendo do layout, pode ser "li.ui-search-layout__item"
    cards = soup.select("li.ui-search-layout__item")
    if not cards:
        # fallback
        cards = soup.select("div.ui-search-result__wrapper")

    for c in cards[:50]:
        a = c.select_one("a.ui-search-link") or c.select_one("a")
        if not a or not a.get("href"):
            continue

        url = a["href"].split("#")[0]
        title_el = c.select_one("h2.ui-search-item__title") or c.select_one("h2") or c.select_one("span")
        title = title_el.get_text(strip=True) if title_el else None

        img = c.select_one("img")
        thumb = img.get("data-src") or img.get("src") if img else None

        price_el = c.select_one("span.andes-money-amount__fraction") or c.select_one("span.price-tag-fraction")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = parse_brl_price(price_text)

        items.append({
            "source": "mercadolivre",
            "external_id": _extract_external_id_from_url(url),
            "title": title,
            "url": url,
            "thumbnail_url": thumb,
            "price": price,
            "currency": "BRL",
            "location": None,
        })

    return items
