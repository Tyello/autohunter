from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin

from lxml import html as lxml_html

from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_ICARROS_BASE = "https://www.icarros.com.br"


def _clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def _external_id(url: str) -> Optional[str]:
    """
    Prefer the canonical iCarros pattern '/d<digits>' (detail pages), then fallback
    to any 6+ digit group.
    """
    m = re.search(r"/d(\d{6,})\b", url)
    if m:
        return m.group(1)
    m = re.search(r"(\d{6,})", url)
    if m:
        return m.group(1)
    return None


def _is_detail_url(url: str) -> bool:
    # Keep it strict to avoid dealer/stock pages like /ache/estoque.jsp?id=...
    # iCarros detail links typically are under /comprar/.../d<id>
    return "icarros.com.br" in url and "/comprar/" in url and re.search(r"/d\d{6,}\b", url) is not None


def _find_card_root(a) -> Any:
    """
    Walk up a few levels trying to find a "card-like" container that contains a price marker.
    This improves price extraction because iCarros usually doesn't put the price in the <a> text.
    """
    node = a
    for _ in range(7):
        parent = node.getparent()
        if parent is None:
            break
        node = parent
        # Avoid scanning the whole page if we climbed too far
        txt = (node.text_content() or "")
        if "R$" in txt and len(txt) < 6000:
            return node
    p = a.getparent()
    return p if p is not None else a


def _title_from_card(card, fallback_text: str) -> Optional[str]:
    # Prefer headings inside the card
    for xp in (".//h2//text()", ".//h3//text()", ".//*[@data-testid='card-title']//text()"):
        parts = [_clean_text(x) for x in card.xpath(xp)]
        parts = [p for p in parts if p]
        if parts:
            title = _clean_text(" ".join(parts))
            if 6 <= len(title) <= 160:
                return title

    # Common fallback: image alt
    alts = [_clean_text(x) for x in card.xpath(".//img[1]/@alt")]
    alts = [a for a in alts if a]
    if alts:
        title = alts[0]
        if 6 <= len(title) <= 160:
            return title

    # Last resort: anchor text
    t = _clean_text(fallback_text)
    if 6 <= len(t) <= 160:
        return t
    return None


def _thumb_from_card(card) -> Optional[str]:
    for xp in (".//img[1]/@src", ".//img[1]/@data-src"):
        img = card.xpath(xp)
        if img and img[0]:
            return img[0]
    return None


def _extract_candidates_from_next_data(doc, base_url: str) -> list[dict]:
    """
    Try extracting listing data from Next.js payload (if present). This is typically the
    most stable way to get price/title without depending on DOM classes.
    """
    scripts = doc.xpath("//script[@id='__NEXT_DATA__' and @type='application/json']/text()")
    if not scripts:
        return []

    try:
        data = json.loads(scripts[0])
    except Exception:
        return []

    out: dict[str, dict] = {}

    PRICE_KEYS = ("price", "preco", "valor", "salePrice", "listingPrice", "value")
    TITLE_KEYS = ("title", "name", "nome", "model", "modelo", "version", "versao")
    URL_KEYS = ("url", "href", "link", "permalink")

    def coerce_price(v: Any) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            if v <= 0:
                return None
            # assume BRL cents sometimes appear; keep as-is (ingest will sanitize extremes)
            return float(v)
        if isinstance(v, str):
            if "R$" in v:
                p = parse_brl_price(v)
                return float(p) if p is not None else None
            # sometimes it's only digits with separators
            if re.search(r"\d", v):
                p = parse_brl_price("R$ " + v)
                return float(p) if p is not None else None
        return None

    def best_title(d: dict) -> Optional[str]:
        for k in TITLE_KEYS:
            v = d.get(k)
            if isinstance(v, str) and 4 <= len(v) <= 160:
                return _clean_text(v)
        # compose if we have pieces
        make = d.get("make") or d.get("marca")
        model = d.get("model") or d.get("modelo")
        ver = d.get("version") or d.get("versao")
        parts = [_clean_text(x) for x in (make, model, ver) if isinstance(x, str) and x.strip()]
        if parts:
            t = _clean_text(" ".join(parts))
            if 6 <= len(t) <= 160:
                return t
        return None

    def best_url(d: dict) -> Optional[str]:
        for k in URL_KEYS:
            v = d.get(k)
            if isinstance(v, str) and "/comprar/" in v:
                return v
        return None

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            u = best_url(obj)
            if isinstance(u, str):
                url = u if u.startswith("http") else urljoin(base_url, u)
                if _is_detail_url(url):
                    ext = _external_id(url)
                    if ext:
                        price = None
                        for pk in PRICE_KEYS:
                            if pk in obj:
                                price = coerce_price(obj.get(pk))
                                if price is not None:
                                    break
                        cur = out.get(url) or {
                            "source": "icarros",
                            "external_id": ext,
                            "url": url,
                            "title": None,
                            "price": None,
                            "thumbnail_url": None,
                            "location": None,
                        }
                        t = best_title(obj)
                        if cur.get("title") is None and t:
                            cur["title"] = t
                        if cur.get("price") is None and price is not None:
                            cur["price"] = price
                        out[url] = cur

            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return list(out.values())


def scrape_icarros(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """iCarros scraper (Playwright-first).

    iCarros often blocks plain HTTP clients; rely on Playwright.
    This scraper is defensive: filters only detail URLs and tries __NEXT_DATA__ first,
    then falls back to DOM-based extraction.
    """
    res = fetch_html_browser(search_url, ctx=ctx, timeout_ms=45000, wait_until="domcontentloaded")
    html_text = res.html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(res.final_url or search_url)

    base_url = res.final_url or search_url

    # 1) Best effort: Next.js payload
    listings = _extract_candidates_from_next_data(doc, base_url=base_url)
    if listings:
        return listings

    # 2) DOM-based extraction
    by_url: dict[str, dict] = {}
    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        if not href:
            continue

        url = urljoin(base_url, href)
        if not _is_detail_url(url):
            continue

        ext = _external_id(url)
        if not ext:
            continue

        card = _find_card_root(a)
        card_text = _clean_text(card.text_content())
        price = parse_brl_price(card_text) if "R$" in card_text else None

        title = _title_from_card(card, a.text_content())
        thumb = _thumb_from_card(card)

        cur = by_url.get(url) or {
            "source": "icarros",
            "external_id": ext,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        if cur.get("title") is None and title:
            cur["title"] = title
        if cur.get("price") is None and price is not None:
            cur["price"] = price
        if cur.get("thumbnail_url") is None and thumb:
            cur["thumbnail_url"] = thumb

        by_url[url] = cur

    # 3) Last fallback: regex URLs (still filtered to detail pages)
    if not by_url:
        for m in re.finditer(r"https?://www\.icarros\.com\.br/[^\"\'\s<>]*", html_text):
            url = m.group(0)
            if not _is_detail_url(url):
                continue
            ext = _external_id(url)
            if not ext:
                continue
            by_url[url] = {
                "source": "icarros",
                "external_id": ext,
                "url": url,
                "title": None,
                "price": None,
                "thumbnail_url": None,
                "location": None,
            }

    return list(by_url.values())
