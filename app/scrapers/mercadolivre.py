from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_html
from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_VEH_HOST = "carro.mercadolivre.com.br"


def _is_vehicle_url(url: str) -> bool:
    try:
        h = urlparse(url).netloc.lower()
        return h.startswith(_VEH_HOST)
    except Exception:
        return False


def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    return u


def _looks_blocked(html: str) -> bool:
    h = (html or "").lower()
    if "access denied" in h:
        return True
    if "just a moment" in h and "cloudflare" in h:
        return True
    if "captcha" in h and ("datadome" in h or "hcaptcha" in h or "recaptcha" in h):
        return True
    if "are you human" in h or "verify you are" in h:
        return True
    if "robot" in h and "mercado" in h:
        return True
    return False


def _extract_external_id(url: str) -> str:
    # MLB123456 or MLB-123456 sometimes present
    m = re.search(r"\bMLB-?\d+\b", url or "", flags=re.I)
    if m:
        return m.group(0).upper().replace("MLB-", "MLB")
    # fallback: last path segment
    try:
        p = urlparse(url).path.rstrip("/")
        tail = p.split("/")[-1]
        return (tail or url)[:80]
    except Exception:
        return (url or "")[:80]


def _parse_cards(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")

    # ML changes a lot. We go for resilient anchors and then walk up.
    anchors = soup.select(
        "a.ui-search-link, a.ui-search-item__group__element, a.polycard__link, a[href*='mercadolivre.com.br']"
    )
    seen = set()
    out: List[Dict[str, Any]] = []

    for a in anchors:
        href = _normalize_url(a.get("href") or "")
        if not href or href in seen:
            continue
        seen.add(href)

        # Find a reasonable card root
        card = a
        for _ in range(6):
            if card is None:
                break
            cls = " ".join(card.get("class") or [])
            if "ui-search" in cls or "polycard" in cls or card.name in ("li", "article", "div"):
                # keep walking until we hit a likely container
                pass
            parent = card.parent
            if parent is None:
                break
            card = parent

        # Title
        title_el = None
        if card is not None:
            title_el = card.select_one(
                "h2.ui-search-item__title, h2.polycard__title, h2, span.ui-search-item__title"
            )
        title = (title_el.get_text(" ", strip=True) if title_el else "").strip() or None

        # Thumbnail
        thumb_el = card.select_one("img.ui-search-result-image__element, img.polycard__image, img") if card else None
        thumb = ""
        if thumb_el is not None:
            thumb = (thumb_el.get("data-src") or thumb_el.get("src") or "").strip()
        thumb = thumb or None

        # Price
        price = None
        if card is not None:
            price_el = card.select_one(
                "span.andes-money-amount__fraction, span.price-tag-fraction, span.ui-search-price__part .andes-money-amount__fraction"
            )
            if price_el is not None:
                price = parse_brl_price(price_el.get_text(" ", strip=True))

        out.append({"url": href, "title": title, "thumbnail_url": thumb, "price": price})

    return out


def _build_listing(*, source: str, external_id: str, url: str, title: Optional[str], thumbnail_url: Optional[str], price: Any) -> Dict[str, Any]:
    # Keep compatibility with the rest of the project (shape used elsewhere).
    return {
        "source": source,
        "external_id": external_id,
        "title": title,
        "url": url,
        "thumbnail_url": thumbnail_url,
        "price": price,
        "currency": "BRL",
        "location": None,
    }


def _dedupe(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Simple dedupe by (source, external_id) then by canonical url.
    seen = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        src = (it.get("source") or "").strip().lower()
        ext = (it.get("external_id") or "").strip()
        url = (it.get("url") or "").strip()
        key = (src, ext) if src and ext else (src, url)
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _fetch_html_ml(url: str, ctx: ScrapeContext, timeout: int = 25) -> str:
    """Hybrid ideal:

    1) Try HTTP (cheap)
    2) If blocked, run Playwright once to warm storage_state (cookies/session)
    3) Retry HTTP (now with cookies automatically injected by fetch_response)
    4) If still blocked, fall back to browser HTML (best-effort)
    """

    proxy = getattr(ctx, "proxy_server", None)

    # 0) If forced via DB, just use browser.
    if settings.enable_playwright and getattr(ctx, "force_browser", False):
        res = fetch_html_browser(
            url,
            ctx=ctx,
            timeout_ms=timeout * 1000,
            wait_until="domcontentloaded",
            min_delay_ms=250,
            max_delay_ms=900,
        )
        return res.html

    # 1) HTTP attempt
    try:
        return fetch_html(
            url,
            ctx=ctx,
            timeout=timeout,
            referer=f"https://{_VEH_HOST}/",
            proxy=proxy,
            min_delay_ms=250,
            max_delay_ms=900,
        )
    except FetchBlocked:
        pass
    except Exception:
        # Only warm on hard failures if fallback is enabled
        if not (settings.enable_playwright and getattr(ctx, "browser_fallback_enabled", False)):
            raise

    if not (settings.enable_playwright and getattr(ctx, "browser_fallback_enabled", False)):
        return ""

    # 2) Warm session via browser. Use ML homepage first, then the target URL.
    # Any browser fetch will persist storage_state in the Playwright pool.
    try:
        fetch_html_browser(
            f"https://www.mercadolivre.com.br/",
            ctx=ctx,
            timeout_ms=30000,
            wait_until="domcontentloaded",
            min_delay_ms=250,
            max_delay_ms=900,
        )
    except Exception:
        pass

    browser_html = ""
    try:
        r = fetch_html_browser(
            url,
            ctx=ctx,
            timeout_ms=timeout * 1000,
            wait_until="domcontentloaded",
            min_delay_ms=250,
            max_delay_ms=900,
        )
        browser_html = r.html or ""
    except Exception:
        browser_html = ""

    # 3) Retry HTTP once (now cookie-injected from storage_state)
    try:
        html2 = fetch_html(
            url,
            ctx=ctx,
            timeout=timeout,
            referer=f"https://{_VEH_HOST}/",
            proxy=proxy,
            min_delay_ms=120,
            max_delay_ms=420,
        )
        if html2 and not _looks_blocked(html2):
            return html2
    except Exception:
        pass

    # 4) Fallback: use browser HTML if it looks usable
    if browser_html and not _looks_blocked(browser_html):
        return browser_html
    return ""


def scrape_mercadolivre(search_url: str, ctx: ScrapeContext) -> List[Dict[str, Any]]:
    html = _fetch_html_ml(search_url, ctx=ctx, timeout=25)
    if not html:
        return []

    # ML occasionally returns JSON embedded; keep this as a best-effort
    if "__PRELOADED_STATE__" in html and "polycards" in html:
        try:
            m = re.search(r"__PRELOADED_STATE__\s*=\s*(\{.*?\});", html, flags=re.S)
            if m:
                state = json.loads(m.group(1))
                # fallback parsing is too unstable; ignore for now
        except Exception:
            pass

    raw = _parse_cards(html)
    items: List[Dict[str, Any]] = []
    nonveh = 0
    for r in raw:
        url = _normalize_url(r.get("url") or "")
        if not url:
            continue
        if not _is_vehicle_url(url):
            nonveh += 1
            continue

        external_id = _extract_external_id(url)
        items.append(
            _build_listing(
                source="mercadolivre",
                external_id=external_id,
                url=url,
                title=r.get("title"),
                thumbnail_url=r.get("thumbnail_url"),
                price=r.get("price"),
            )
        )

    return _dedupe(items)
