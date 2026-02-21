"""TurboClass scraper (BaseScraper).

Fonte SSR leve e barata.

Observações de design (Raspberry Pi):
- 1 request por query (lista) + enrichment opcional e limitado para thumbs.
- Sem Playwright por padrão (ctx.http), mas com fallback habilitável via DB.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from app.scrapers.scraper_base import BaseScraper
from app.scrapers.parsing import parse_brl_price
from app.scrapers.utils import normalize_asset_url, pick_from_srcset


class TurboClassScraper(BaseScraper):
    BASE_URL = "https://turboclass.com.br"

    _RE_DETAIL = re.compile(r"(?:^|/)anuncio/(?:detalhe|vendido)/([^/?#]+)", re.I)
    _RE_TC_ID = re.compile(r"\b(tc-[a-z0-9]+)\b", re.I)
    _RE_YEARS = re.compile(r"\bANO\s*/\s*MODELO\s*(19\d{2}|20\d{2})\s*/\s*(19\d{2}|20\d{2})\b", re.I)
    _RE_LOCATION = re.compile(r"\bLOCALIDADE\s+(.+?)\s+detalhes\b", re.I)

    def __init__(self):
        super().__init__(source_name="turboclass")

    def build_search_url(self, query: str, **kwargs) -> str:
        q = quote_plus((query or "").strip())
        return f"{self.BASE_URL}/anuncio-lista.php?o=&pg=1&q={q}"

    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        soup = BeautifulSoup(raw_content, "lxml")
        items: list[dict] = []

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            if not self._RE_DETAIL.search(href):
                continue

            text = (a.get_text(" ", strip=True) or "").strip()
            if not text:
                continue

            if "R$" not in text and "VALOR" not in text.upper():
                continue

            url = href
            if not url.startswith("http"):
                url = urljoin(self.BASE_URL + "/", url)

            items.append({
                "url": url,
                "text": text,
                "thumbnail": self._extract_thumb_from_anchor(a),
            })

        return items

    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = (raw_data.get("url") or "").strip()
        if not url or not url.startswith("http"):
            return None

        external_id = self._extract_external_id(url)
        if not external_id:
            return None

        text = (raw_data.get("text") or "").strip()
        title = self._parse_title(text)
        price: Optional[Decimal] = parse_brl_price(text)
        year = self._parse_year(text)
        location = self._parse_location(text)

        thumb = raw_data.get("thumbnail") or None
        if thumb:
            thumb = normalize_asset_url(str(thumb), self.BASE_URL)

        make, model = self._extract_make_model(title or "")

        return {
            "external_id": str(external_id),
            "title": title or text,
            "url": url,
            "thumbnail_url": thumb,
            "price": price,
            "currency": "BRL",
            "location": location,
            "year": year,
            "make": make,
            "model": model,
            "extractor_version": "turboclass_v1",
            "raw_payload": raw_data,
        }

    # ----------------- helpers -----------------

    def _extract_external_id(self, url: str) -> str:
        m = self._RE_DETAIL.search(url)
        slug = m.group(1) if m else ""
        if not slug:
            return ""
        m2 = self._RE_TC_ID.search(slug)
        return (m2.group(1).lower() if m2 else slug)

    def _extract_thumb_from_anchor(self, a) -> Optional[str]:
        img = a.select_one("img")
        if img:
            cand = (
                img.get("data-src")
                or img.get("data-original")
                or img.get("data-lazy-src")
                or img.get("src")
            )
            if not cand:
                cand = pick_from_srcset(img.get("data-srcset") or img.get("srcset") or "", prefer_last=True)
            if cand:
                return normalize_asset_url(cand, self.BASE_URL)

        src = a.select_one("source[srcset]")
        if src:
            cand = pick_from_srcset(src.get("srcset") or "", prefer_last=True)
            if cand:
                return normalize_asset_url(cand, self.BASE_URL)

        el = a.select_one("[style*='background-image']")
        if el:
            style = el.get("style") or ""
            m = re.search(r"background-image\s*:\s*url\((['\"]?)([^'\")]+)\1\)", style, re.I)
            if m:
                return normalize_asset_url(m.group(2), self.BASE_URL)

        return None

    def _parse_year(self, text: str) -> Optional[int]:
        if not text:
            return None
        m = self._RE_YEARS.search(text)
        if m:
            try:
                y = int(m.group(1))
                return y if 1960 <= y <= 2035 else None
            except Exception:
                return None
        m2 = re.search(r"\b(19\d{2}|20\d{2})\b", text)
        if m2:
            try:
                y = int(m2.group(1))
                return y if 1960 <= y <= 2035 else None
            except Exception:
                return None
        return None

    def _parse_location(self, text: str) -> Optional[str]:
        if not text:
            return None
        m = self._RE_LOCATION.search(text)
        if m:
            loc = " ".join((m.group(1) or "").replace("\xa0", " ").split())
            return loc.strip() or None
        matches = list(re.finditer(r"([A-Za-zÀ-ÿ0-9\s\-\.]+\/[A-Z]{2})\b", text))
        if matches:
            loc = " ".join(matches[-1].group(1).split())
            return loc.strip() or None
        return None

    def _parse_title(self, text: str) -> Optional[str]:
        if not text:
            return None
        head = text
        if "VALOR" in head.upper():
            head = re.split(r"\bVALOR\b", head, maxsplit=1, flags=re.I)[0]
        head = re.split(r"\bMotoriz", head, maxsplit=1, flags=re.I)[0].strip()
        head = " ".join(head.replace("\xa0", " ").split())
        return head or None

    def _extract_make_model(self, title: str) -> tuple[Optional[str], Optional[str]]:
        t = (title or "").strip()
        if not t:
            return None, None

        # Heurística simples: primeiras 2 palavras, com suporte a marcas compostas.
        multi = {
            "Alfa Romeo": "Alfa Romeo",
            "Land Rover": "Land Rover",
            "Mercedes-Benz": "Mercedes-Benz",
            "Harley-Davidson": "Harley-Davidson",
        }
        for k in multi:
            if t.lower().startswith(k.lower() + " "):
                rest = t[len(k):].strip().split()
                return multi[k], (rest[0] if rest else None)

        parts = t.split()
        if len(parts) >= 2:
            return parts[0], parts[1]
        return parts[0], None
