from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import html as lxml_html

from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_ICARROS_BASE = "https://www.icarros.com.br"

# Canonical iCarros listing pattern:
# https://www.icarros.com.br/comprar/<city-uf>/<make>/<model>/<year>/d<id>
_LISTING_ID_RE = re.compile(r"^https?://(?:www\.)?icarros\.com\.br/comprar/.+/\d{4}/d(\d+)(?:$|[/?#])", re.I)
_LISTING_URL_RE = re.compile(r'https?://(?:www\.)?icarros\.com\.br/comprar/[^\"\'\s]+?/\d{4}/d\d+(?:\?[^\"\'\s]*)?', re.I)


def _clean_text(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def _canonical_url(url: str) -> str:
    """Drop query/fragment to avoid duplicates coming from 'pos=...' etc."""
    sp = urlsplit(url)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))


def _external_id(url: str) -> Optional[str]:
    m = re.search(r"/d(\d+)", url)
    return m.group(1) if m else None


def _is_listing_url(url: str) -> bool:
    return bool(_LISTING_ID_RE.match(url))


def _extract_price(text: str):
    """Parse a BRL-looking price substring from arbitrary card text."""
    if not text:
        return None
    m = re.search(r"R\$\s*[0-9\.]+(?:,[0-9]{1,2})?", text)
    if not m:
        return None
    return parse_brl_price(m.group(0))


def _pick_from_srcset(srcset: str, *, max_width: int = 900) -> Optional[str]:
    """Pick a reasonable URL from a srcset string.

    Prefer the highest width <= max_width; otherwise take the smallest candidate.
    Handles 'url 540w, url2 1080w' and 'url 2x' formats.
    """
    if not srcset:
        return None

    candidates: list[tuple[int, str]] = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        url = bits[0].strip()
        size = 0
        if len(bits) >= 2:
            token = bits[1].strip().lower()
            if token.endswith("w"):
                try:
                    size = int(token[:-1])
                except Exception:
                    size = 0
            elif token.endswith("x"):
                # treat density as width-like ordering
                try:
                    size = int(float(token[:-1]) * 1000)
                except Exception:
                    size = 0
        candidates.append((size, url))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0] or 0)
    under = [c for c in candidates if c[0] and c[0] <= max_width]
    if under:
        return under[-1][1]

    # No widths under threshold (or no widths at all) -> pick the smallest to reduce bytes.
    return candidates[0][1]


def _normalize_asset_url(raw: str, base_url: str) -> Optional[str]:
    if not raw:
        return None
    u = raw.strip()
    if not u or u.startswith("data:"):
        return None
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/"):
        u = urljoin(base_url, u)
    return u


def _extract_thumbnail(card, base_url: str) -> Optional[str]:
    """Try multiple lazy-load patterns used by iCarros."""

    # 1) <img ...> with various attributes
    imgs = card.xpath(".//img")
    if imgs:
        img = imgs[0]
        for attr in ("data-src", "data-lazy-src", "data-original", "data-srcset", "srcset", "src"):
            v = img.get(attr)
            if not v:
                continue
            if "srcset" in attr:
                picked = _pick_from_srcset(v)
                if picked:
                    return _normalize_asset_url(picked, base_url)
            else:
                return _normalize_asset_url(v, base_url)

    # 2) <picture><source srcset=...>
    srcsets = card.xpath(".//picture//source[@srcset]/@srcset")
    for ss in srcsets:
        picked = _pick_from_srcset(ss)
        if picked:
            return _normalize_asset_url(picked, base_url)

    # 3) background-image style
    style_nodes = card.xpath(
        ".//*[@style and contains(translate(@style,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'background-image')]"
    )
    for n in style_nodes:
        st = (n.get("style") or "")
        m = re.search(r"background-image\s*:\s*url\(([^)]+)\)", st, flags=re.I)
        if m:
            raw = m.group(1).strip().strip('"\'')
            u = _normalize_asset_url(raw, base_url)
            if u:
                return u

    return None


def _find_card(a):
    """Return a reasonable card container to extract price/thumb/title."""
    cur = a
    for _ in range(6):
        text = _clean_text(cur.text_content())
        if "R$" in text or cur.xpath(".//img") or cur.xpath(".//picture"):
            return cur
        p = cur.getparent()
        if p is None:
            break
        cur = p
    return a


def _extract_title(card, a) -> Optional[str]:
    # Prefer header-like nodes
    for xp in (".//h1", ".//h2", ".//h3"):
        for n in card.xpath(xp):
            t = _clean_text(n.text_content())
            if t and "R$" not in t and 6 <= len(t) <= 140:
                return t

    # fall back to anchor title attr or text content
    t = _clean_text(a.get("title") or "") or _clean_text(a.text_content())
    if t and "R$" not in t and 6 <= len(t) <= 160:
        return t
    return None


def scrape_icarros(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """iCarros scraper (Playwright-first).

    iCarros often blocks plain HTTP clients; rely on Playwright. We avoid
    wait_until='networkidle' because modern pages can keep network busy forever.
    """
    res = fetch_html_browser(search_url, ctx=ctx, timeout_ms=45000, wait_until="domcontentloaded")
    html_text = res.html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(res.final_url or search_url)

    by_ext: dict[str, dict] = {}
    base_url = res.final_url or search_url

    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        if not href:
            continue

        url = urljoin(base_url, href)
        if "icarros.com.br" not in url:
            continue

        url = _canonical_url(url)

        # Keep only real listing pages (avoid dealership/stock pages like /ache/estoque.jsp?id=...)
        if not _is_listing_url(url):
            continue

        ext = _external_id(url)
        if not ext:
            continue

        card = _find_card(a)

        card_text = _clean_text(card.text_content())
        price = _extract_price(card_text)
        thumb = _extract_thumbnail(card, base_url=base_url)
        title = _extract_title(card, a)

        cur = by_ext.get(ext) or {
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

        by_ext[ext] = cur

    # fallback: regex over the raw HTML (strict listing URLs)
    if not by_ext:
        for full_url in _LISTING_URL_RE.findall(html_text):
            canonical = _canonical_url(full_url)
            if not _is_listing_url(canonical):
                continue
            ext = _external_id(canonical)
            if not ext:
                continue
            if ext in by_ext:
                continue
            by_ext[ext] = {
                "source": "icarros",
                "external_id": ext,
                "url": canonical,
                "title": None,
                "price": None,
                "thumbnail_url": None,
                "location": None,
            }

    return list(by_ext.values())
