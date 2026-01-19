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


def scrape_gogarage(search_url: str, ctx: ScrapeContext) -> list[dict]:
    res = fetch_html_browser(search_url, ctx=ctx)
    soup = BeautifulSoup(res.html, "html.parser")

    items: list[dict] = []
    seen: set[str] = set()

    def normalize_location(text: str):
        t = " ".join((text or "").split())
        if not t:
            return None
        m = re.search(r"([A-Za-zÀ-ÿ\s\.]+)\s*[-,]\s*([A-Z]{2})\b", t)
        if m:
            city = " ".join(m.group(1).split())
            uf = m.group(2)
            return f"{city}-{uf}" if city else uf
        return None

    # Prefer listing anchors patterns
    anchors = soup.select('a[href*="/carro/"]') or soup.select('a[href*="/veiculo/"]') or soup.select('a[href*="/anuncio/"]')

    for a in anchors:
        href = a.get("href") or ""
        full = href if "gogarage.com.br" in href else urljoin("https://gogarage.com.br", href)

        if "gogarage.com.br" not in full:
            continue

        m = re.search(r"(\d{6,})", full)
        external_id = m.group(1) if m else full
        if external_id in seen:
            continue
        seen.add(external_id)

        # Walk up to get a card container
        card = a
        for _ in range(5):
            if card is None:
                break
            if getattr(card, "name", None) in ("article", "li", "section", "div"):
                # stop early if the card seems rich enough
                if hasattr(card, "select_one") and card.select_one("img"):
                    break
            card = card.parent
        if card is None:
            card = a.parent or a

        txt = card.get_text(" ", strip=True) if hasattr(card, "get_text") else ""

        title = (a.get("aria-label") or a.get_text(" ", strip=True) or "").strip()
        if not title or len(title) < 6:
            # fallback to first chunk of text
            title = " ".join(txt.split()[:10])
        if not title:
            continue

        pm = re.search(r"R\$\s*[0-9\.]+(\,[0-9]{2})?", txt)
        price = _parse_brl_price_to_decimal(pm.group(0)) if pm else None

        thumb = None
        img = card.select_one("img") if hasattr(card, "select_one") else None
        if img:
            thumb = img.get("src") or img.get("data-src") or img.get("data-lazy")
            if thumb and thumb.startswith("//"):
                thumb = "https:" + thumb

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
                "source": "gogarage",
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
