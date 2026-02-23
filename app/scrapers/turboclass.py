from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html
from app.scrapers.contract import finalize_listings
from app.scrapers.parsing import parse_brl_price
from app.sources.types import ScrapeContext


_BASE = "https://turboclass.com.br/"

_RE_BG_URL = re.compile(r"url\((?:'|\")?(.*?)(?:'|\")?\)", re.I)


def _clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def _canonical_url(url: str) -> str:
    """Drop query/fragment to reduce duplicates."""
    try:
        sp = urlsplit(url)
        return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))
    except Exception:
        return url


def _abs_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    # TurboClass uses relative hrefs like "anuncio/detalhe/..." (without leading slash)
    return urljoin(_BASE, href)


def _extract_external_id(href: str) -> Optional[str]:
    href = (href or "").strip().lstrip("/")
    m = re.search(r"\banuncio/detalhe/(tc-[a-z0-9]+)", href, re.I)
    return m.group(1) if m else None


def _extract_bg_image(style: str) -> Optional[str]:
    if not style:
        return None
    m = _RE_BG_URL.search(style)
    if not m:
        return None
    raw = (m.group(1) or "").strip()
    if not raw or raw.startswith("data:"):
        return None
    return urljoin(_BASE, raw)


def _find_row_value(card: BeautifulSoup, key: str) -> str:
    """Find table row where first cell contains `key` and return the value cell text."""
    key = (key or "").strip().lower()
    if not key:
        return ""
    for tr in card.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        k = _clean_text(tds[0].get_text(" ", strip=True)).lower()
        if k == key:
            return _clean_text(tds[1].get_text(" ", strip=True))
    return ""


def _parse_year(year_model_text: str) -> Optional[int]:
    """Parse '2009/2010' -> 2010 (prefer model year)."""
    t = (year_model_text or "").strip()
    if not t:
        return None
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", t)
    if not years:
        return None
    try:
        y = int(years[-1])  # prefer model year when present
        if 1900 <= y <= 2100:
            return y
    except Exception:
        return None
    return None


def _build_title(make: str, model: str, anchor_title: str, spec: str, year: Optional[int]) -> str:
    make = _clean_text(make)
    model = _clean_text(model)
    at = _clean_text(anchor_title)
    spec = _clean_text(spec)

    base = " ".join([make, model]).strip()

    # Prefer anchor title because it contains tokens like "SI", "K24", etc.
    if at:
        low = at.lower()
        if make and low.startswith(make.lower()):
            title = at
        elif base and low.startswith(base.lower()):
            title = at
        elif make:
            title = f"{make} {at}".strip()
        else:
            title = at
    else:
        title = base

    # Add spec (Original/Turbo/etc) only if it isn't already there.
    if spec and spec.lower() not in title.lower():
        title = f"{title} {spec}".strip()

    # Put year in title to keep year filters working even in legacy schema.
    if year and str(year) not in title:
        title = f"{title} {year}".strip()

    return title


def scrape_turboclass(search_url: str, ctx: ScrapeContext | None = None, limit: int = 80) -> list[dict]:
    """HTTP-first TurboClass scraper.

    Gotchas:
    - card hrefs are relative like "anuncio/detalhe/..." (no leading slash)
    - images are in inline styles (background-image)
    """

    html = fetch_html(search_url, ctx=ctx)
    soup = BeautifulSoup(html or "", "html.parser")

    out: list[dict] = []

    anchors = soup.select('a.car-link[href*="anuncio/detalhe/"]')
    if not anchors:
        anchors = soup.select('a[href*="anuncio/detalhe/"]')

    is_sold_mode = ("/vendidos" in (search_url or "")) or ("vendidos" in (search_url or "").lower()) or (
        bool(ctx) and (getattr(ctx, "source", "").strip().lower() in {"turboclass_vendidos", "turboclass_sold"})
    )

    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href:
            continue

        ext = _extract_external_id(href)
        if not ext:
            continue

        url = _canonical_url(_abs_url(href))
        if not url:
            continue

        # Card container
        try:
            card = a.find_parent(class_=re.compile(r"car-col|car-card", re.I)) or a
        except Exception:
            card = a

        # make/model from title-wrap
        make = ""
        model = ""
        tw = None
        if hasattr(card, "select_one"):
            tw = card.select_one(".title-wrap")
        if tw is None:
            tw = a.select_one(".title-wrap")
        if tw is not None:
            h6 = tw.find("h6")
            h5 = tw.find("h5")
            if h6:
                make = _clean_text(h6.get_text(" ", strip=True))
            if h5:
                model = _clean_text(h5.get_text(" ", strip=True))

        # spec from grid-specs
        spec = ""
        gs = None
        if hasattr(card, "select_one"):
            gs = card.select_one(".grid-specs")
        if gs is None:
            gs = a.select_one(".grid-specs")
        if gs is not None:
            h = gs.find("h5")
            if h:
                spec = _clean_text(h.get_text(" ", strip=True))

        price = None
        year = None
        location = ""
        if hasattr(card, "select"):
            price = parse_brl_price(_find_row_value(card, "valor"))
            year = _parse_year(_find_row_value(card, "ano/modelo"))
            location = _find_row_value(card, "localidade")

        thumb = None
        img_div = None
        if hasattr(card, "select_one"):
            img_div = card.select_one("div[style*='background-image']")
        if img_div is None:
            img_div = a.select_one("div[style*='background-image']")
        if img_div is not None:
            thumb = _extract_bg_image(img_div.get("style") or "")

        anchor_title = a.get("title") or ""
        title = _build_title(make, model, anchor_title, spec, year)

        payload = {
                # IMPORTANT: sold-mode still updates the *same* source listings.
                "source": "turboclass",
                "external_id": ext,
                "title": title or None,
                "url": url,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": location or None,
                # optional structured fields (inserted only if schema supports)
                "year": year,
                "make": make or None,
                "model": model or None,
        }

        if is_sold_mode:
            payload["is_sold"] = True
            payload["sold_at"] = datetime.now(timezone.utc)
            payload["listing_type"] = "marketplace"
            payload.setdefault("extras", {})
            payload["extras"] = dict(payload["extras"] or {})
            payload["extras"]["sold_source"] = "turboclass_vendidos"

        out.append(payload)

        if limit and len(out) >= int(limit):
            break

    return finalize_listings("turboclass", out)
