from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from lxml import html as lxml_html

from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_ICARROS_BASE = "https://www.icarros.com.br"


def _clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def _external_id(url: str) -> Optional[str]:
    # Try common patterns
    m = re.search(r"(\d{6,})", url)
    if m:
        return m.group(1)
    return None


def scrape_icarros(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """iCarros scraper (Playwright-first).

    iCarros often returns 403 to HTTP clients; rely on Playwright.
    """
    res = fetch_html_browser(search_url, ctx=ctx, timeout_ms=45000, wait_until="networkidle")
    html_text = res.html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(res.final_url or search_url)

    by_url: dict[str, dict] = {}

    # heuristic: car detail links tend to contain '/comprar/' and an id, but iCarros changes a lot.
    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        if not href:
            continue
        url = urljoin(res.final_url or search_url, href)
        if "icarros.com.br" not in url:
            continue

        ext = _external_id(url)
        if not ext:
            continue

        text = _clean_text(a.text_content())
        price = parse_brl_price(text) if "R$" in text else None

        thumb = None
        img = a.xpath(".//img[1]/@src")
        if img:
            thumb = img[0]

        cur = by_url.get(url) or {
            "source": "icarros",
            "external_id": ext,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        if not cur.get("title") and text and (price is None) and len(text) >= 6 and len(text) <= 120:
            cur["title"] = text
        if cur.get("price") is None and price is not None:
            cur["price"] = price
        if cur.get("thumbnail_url") is None and thumb:
            cur["thumbnail_url"] = thumb

        by_url[url] = cur

    # fallback: regex (more permissive)
    if not by_url:
        for m in re.finditer(r"https?://www\.icarros\.com\.br/[^\"\']*(\d{6,})[^\"\']*", html_text):
            url = m.group(0).split('"')[0].split("'")[0]
            ext = m.group(1)
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
