from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from lxml import html as lxml_html

from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_KAVAK_BASE = "https://www.kavak.com"


def _clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def _external_id_from_url(url: str) -> str:
    # Kavak URLs are often stable slugs, ex: /br/venda/honda-civic-20_ex_cvt-sedan-2018
    m = re.search(r"/br/venda/([^/?#]+)", url)
    if m:
        return m.group(1)
    # fallback: last path segment
    return (url.split("?")[0].rstrip("/").split("/")[-1] or url)


def scrape_kavak(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Kavak scraper (Playwright-first).

    Kavak frequently blocks HTTP clients. We render with Playwright and then
    extract card links to /br/venda/...
    """
    # networkidle can hang forever on modern apps; domcontentloaded is more stable.
    res = fetch_html_browser(search_url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded")
    html_text = res.html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(res.final_url or search_url)

    by_url: dict[str, dict] = {}

    for a in doc.xpath("//a[contains(@href, '/br/venda/')]"):
        href = a.get("href") or ""
        if not href:
            continue
        url = urljoin(res.final_url or search_url, href)
        if "/br/venda/" not in url:
            continue

        external_id = _external_id_from_url(url)
        text = _clean_text(a.text_content())

        # Basic price extraction
        price = None
        if "R$" in text:
            price = parse_brl_price(text)

        # Thumbnail attempt
        thumb = None
        img = a.xpath(".//img[1]/@src")
        if img:
            thumb = img[0]

        cur = by_url.get(url) or {
            "source": "kavak",
            "external_id": external_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        # Title heuristic: keep a short-ish text that isn't only price
        if not cur.get("title") and text and (price is None) and len(text) >= 6 and len(text) <= 120:
            cur["title"] = text

        if cur.get("price") is None and price is not None:
            cur["price"] = price
        if cur.get("thumbnail_url") is None and thumb:
            cur["thumbnail_url"] = thumb

        by_url[url] = cur

    # Fallback: regex extraction
    if not by_url:
        for m in re.finditer(r"https?://www\.kavak\.com/br/venda/[^\"\']+", html_text):
            url = m.group(0).split('"')[0].split("'")[0]
            by_url[url] = {
                "source": "kavak",
                "external_id": _external_id_from_url(url),
                "url": url,
                "title": None,
                "price": None,
                "thumbnail_url": None,
                "location": None,
            }

    return list(by_url.values())
