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


_RE_NOISE_TOKENS = re.compile(
    r"\b(comparar|ver\s*detalhes|financiamento|simular|parcelas|0\s*km|a\s*\d+\s*km)\b",
    re.IGNORECASE,
)


def _clean_title_blob(text: str) -> str:
    t = _clean_text(text)
    if not t:
        return ""
    # remove UI noise
    t = _RE_NOISE_TOKENS.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    # trim very long blobs (cards sometimes include multiple fields)
    return t[:140].strip()


def _pick_best_image(doc) -> Optional[str]:
    """Pick the most likely car photo url from a DOM.

    Mobiauto mixes logos/score icons with the actual photo.
    This heuristic favors jpg/webp/http urls and ignores obvious icons.
    """

    def _candidate_urls(img) -> list[str]:
        urls: list[str] = []
        for attr in ("src", "data-src", "data-lazy", "data-original"):
            v = img.get(attr)
            if v:
                urls.append(v)
        # srcset: take the last (usually highest-res)
        ss = img.get("srcset") or ""
        if ss:
            parts = [p.strip().split(" ")[0] for p in ss.split(",") if p.strip()]
            if parts:
                urls.append(parts[-1])
        return urls

    best: tuple[int, str] | None = None
    for img in doc.xpath("//img"):
        alt = _clean_text(img.get("alt") or "").lower()
        for u in _candidate_urls(img):
            url = (u or "").strip()
            if not url or not url.startswith("http"):
                continue
            low = url.lower()
            score = 0
            if any(ext in low for ext in (".jpg", ".jpeg", ".png", ".webp")):
                score += 3
            if any(k in low for k in ("cdn", "cloudfront", "images", "img", "photo", "fotos")):
                score += 2
            if alt and any(k in alt for k in ("logo", "fipe", "ícone", "icone")):
                score -= 6
            if any(k in low for k in ("logo", "icon", "sprite", "favicon")):
                score -= 6
            if best is None or score > best[0]:
                best = (score, url)

    # background-image urls (some cards use div style)
    for el in doc.xpath("//*[@style]"):
        st = (el.get("style") or "")
        m = re.search(r"background-image\s*:\s*url\(['\"]?(.*?)['\"]?\)", st, re.I)
        if not m:
            continue
        url = (m.group(1) or "").strip()
        if not url.startswith("http"):
            continue
        low = url.lower()
        score = 2
        if any(ext in low for ext in (".jpg", ".jpeg", ".png", ".webp")):
            score += 2
        if any(k in low for k in ("logo", "icon", "sprite", "favicon")):
            score -= 6
        if best is None or score > best[0]:
            best = (score, url)

    if best is None:
        return None
    return best[1]


def _enrich_from_detail(url: str, *, ctx: ScrapeContext) -> dict:
    """Fetch detail page and pull better title/thumbnail/location (cheap SSR when available)."""

    try:
        html = fetch_html(url, ctx=ctx, proxy=ctx.proxy_server, timeout=30, referer=_MOBIAUTO_BASE + "/")
    except FetchBlocked:
        if not settings.enable_playwright:
            raise
        html = fetch_html_browser(url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded").html

    doc = lxml_html.fromstring(html)
    doc.make_links_absolute(url)

    # Title: h1/h2 are usually clean
    h1 = _clean_text(" ".join([t for t in doc.xpath("//h1//text()") if t and t.strip()]))
    h2 = _clean_text(" ".join([t for t in doc.xpath("//h2//text()") if t and t.strip()]))
    title = _clean_title_blob(" ".join([h1, h2]).strip())
    if not title:
        tt = doc.xpath("//title/text()")
        if tt:
            title = _clean_title_blob(tt[0])

    # Price: first plausible BRL price in the HTML
    price = parse_brl_price(html)

    # Location: best-effort around the "Cidade" label
    location = None
    try:
        city_nodes = doc.xpath("//*[normalize-space()='Cidade']/following::*[1]//text()")
        city = _clean_text(" ".join(city_nodes))
        if city:
            location = city
    except Exception:
        location = None

    thumb = _pick_best_image(doc)
    return {"title": title or None, "price": price, "thumbnail_url": thumb, "location": location}


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
        try:
            # prefer image inside the anchor/card
            img_el = a.xpath(".//img[1]")
            if img_el:
                thumb = _pick_best_image(img_el[0].getparent() or a)  # parent tends to have srcset
        except Exception:
            thumb = None

        cur = by_url.get(url) or {
            "source": "mobiauto",
            "external_id": external_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
            "currency": "BRL",
        }

        # Title heuristic: non-price, reasonable length
        if not cur.get("title") and text and (price is None):
            cand = _clean_title_blob(text)
            # if the anchor text is a full card blob, only accept if it looks like a title
            if 6 <= len(cand) <= 140 and "comparar" not in cand.lower():
                cur["title"] = cand

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
                "currency": "BRL",
            }

    # Detail enrichment budget: fixes missing thumbnail / noisy titles.
    budget = 8
    out = []
    for item in by_url.values():
        if budget > 0 and (not item.get("thumbnail_url") or not item.get("title") or "comparar" in str(item.get("title") or "").lower()):
            try:
                d = _enrich_from_detail(item["url"], ctx=ctx)
                budget -= 1
                if d.get("title"):
                    item["title"] = d["title"]
                if item.get("price") is None and d.get("price") is not None:
                    item["price"] = d["price"]
                if not item.get("thumbnail_url") and d.get("thumbnail_url"):
                    item["thumbnail_url"] = d["thumbnail_url"]
                if not item.get("location") and d.get("location"):
                    item["location"] = d["location"]
            except Exception:
                budget -= 1
        out.append(item)

    return out
