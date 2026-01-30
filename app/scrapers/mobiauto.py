from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from lxml import html as lxml_html

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_html
from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_MOBIAUTO_BASE = "https://www.mobiauto.com.br"


def _extract_external_id(url: str) -> Optional[str]:
    m = re.search(r"/detalhes/(\d+)", url)
    if m:
        return m.group(1)
    # fallback: digits anywhere
    m = re.search(r"(\d{6,})", url)
    if m:
        return m.group(1)
    return None


def _clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def scrape_mobiauto(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Mobiauto scraper.

    Strategy:
    - HTTP-first (Mobiauto is often SSR-friendly)
    - If blocked/JS-only, fallback to Playwright when enabled
    - Extracts listing URL + title + price + thumbnail when possible
    """

    html_text: str

    # If ops decided to force browser (DB flag), skip the HTTP attempt.
    if bool(getattr(ctx, "force_browser", False)):
        html_text = fetch_html_browser(search_url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded").html
    else:
        try:
            html_text = fetch_html(search_url, ctx=ctx, proxy=ctx.proxy_server, timeout=25)
        except FetchBlocked:
            if not settings.enable_playwright:
                raise
            html_text = fetch_html_browser(search_url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded").html
        except Exception:
            if not settings.enable_playwright:
                raise
            html_text = fetch_html_browser(search_url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded").html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(search_url)

    by_url: dict[str, dict] = {}

    # Mobiauto listing cards usually link to /detalhes/<id>
    for a in doc.xpath("//a[contains(@href, '/detalhes/')]"):
        href = a.get("href") or ""
        if not href:
            continue
        url = urljoin(search_url, href)
        if "/detalhes/" not in url:
            continue

        external_id = _extract_external_id(url)
        if not external_id:
            continue

        text = _clean_text(a.text_content())
        if not text or text.lower() in ("enviar mensagem", "ver detalhes", "detalhes"):
            text = ""

        price = None
        if "R$" in text or re.search(r"\d\.\d{3}", text):
            price = parse_brl_price(text)

        # thumbnail (best-effort)
        thumb = None
        img = a.xpath(".//img[1]/@src")
        if img:
            thumb = img[0]

        cur = by_url.get(url) or {
            "source": "mobiauto",
            "external_id": external_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        # Title heuristic: non-price, reasonable length
        if not cur.get("title") and text and (price is None) and len(text) >= 6 and len(text) <= 120:
            cur["title"] = text

        if cur.get("price") is None and price is not None:
            cur["price"] = price

        if cur.get("thumbnail_url") is None and thumb:
            cur["thumbnail_url"] = thumb

        by_url[url] = cur

    # Fallback: try to pull URLs from raw HTML if DOM changes
    if not by_url:
        for m in re.finditer(r"https?://www\.mobiauto\.com\.br/[^\"\']+/detalhes/(\d+)", html_text):
            url = m.group(0)
            external_id = m.group(1)
            by_url[url] = {
                "source": "mobiauto",
                "external_id": external_id,
                "url": url,
                "title": None,
                "price": None,
                "thumbnail_url": None,
                "location": None,
            }

    return list(by_url.values())
