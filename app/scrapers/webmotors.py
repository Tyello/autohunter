from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


def _parse_brl_price_to_decimal(text: str) -> Optional[Decimal]:
    if not text:
        return None
    t = text.strip().replace('R$', '').strip()
    t = t.replace('.', '').replace(',', '.')
    try:
        return Decimal(t)
    except Exception:
        return None


def scrape_webmotors(search_url: str, ctx: ScrapeContext) -> list[dict]:
    # JS-heavy: render with Playwright
    res = fetch_html_browser(search_url, ctx=ctx)
    soup = BeautifulSoup(res.html, "html.parser")

    items: list[dict] = []
    seen: set[str] = set()

    def normalize_location(text: str) -> Optional[str]:
        t = " ".join((text or "").split())
        if not t:
            return None
        # patterns like "Indaiatuba - SP" / "Sao Paulo, SP"
        m = re.search(r"([A-Za-zÀ-ÿ\s\.]+)\s*[-,]\s*([A-Z]{2})\b", t)
        if m:
            city = " ".join(m.group(1).split())
            uf = m.group(2)
            return f"{city}-{uf}" if city else uf
        return None

    # Prefer card-like structures: anchor inside an article/div container
    anchors = soup.select('a[href*="/comprar/"]')
    if not anchors:
        anchors = soup.select('a[href*="/anuncio/"]')

    for a in anchors:
        href = a.get("href") or ""
        full = href if "webmotors.com.br" in href else urljoin("https://www.webmotors.com.br", href)
        if "webmotors.com.br" not in full:
            continue

        m = re.search(r"(\d{6,})", full)
        external_id = m.group(1) if m else full
        if external_id in seen:
            continue
        seen.add(external_id)

        card = a
        for _ in range(4):
            if card is None:
                break
            if getattr(card, "name", None) in ("article", "li", "section"):
                break
            card = card.parent
        if card is None:
            card = a.parent or a

        title = (
            (a.get("aria-label") or "").strip()
            or (card.get_text(" ", strip=True) or "").strip()
        )
        if not title or len(title) < 6:
            continue
        title = re.sub(r"\s+", " ", title)

        # Price (try common patterns)
        txt = card.get_text(" ", strip=True) if hasattr(card, "get_text") else ""
        pm = re.search(r"R\$\s*[0-9\.]+(\,[0-9]{2})?", txt)
        price = _parse_brl_price_to_decimal(pm.group(0)) if pm else None

        # Thumbnail
        thumb = None
        img = card.select_one("img")
        if img:
            thumb = img.get("src") or img.get("data-src") or img.get("data-lazy")
            if thumb and thumb.startswith("//"):
                thumb = "https:" + thumb

        # Location (try explicit spans first)
        location = None
        for sel in (
            '[data-testid*="location"]',
            'span[class*="Location"]',
            'p[class*="Location"]',
        ):
            try:
                el = card.select_one(sel)
            except Exception:
                el = None
            if el:
                location = normalize_location(el.get_text(" ", strip=True))
                if location:
                    break
        if not location:
            location = normalize_location(txt)

        items.append(
            {
                "source": "webmotors",
                "external_id": str(external_id),
                "title": title,
                "url": full,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": location,
            }
        )

        if len(items) >= 60:
            break

    return items
