from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from lxml import html as lxml_html

from app.scrapers.parsing import parse_brl_price
from app.scrapers.utils import clean_text, normalize_asset_url, pick_from_srcset
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_ICARROS_BASE = "https://www.icarros.com.br"

logger = logging.getLogger(__name__)

# Canonical iCarros listing pattern:
# https://www.icarros.com.br/comprar/<city-uf>/<make>/<model>/<year>/d<id>
_LISTING_ID_RE = re.compile(r"^https?://(?:www\.)?icarros\.com\.br/comprar/.+/\d{4}/d(\d+)(?:$|[/?#])", re.I)
_LISTING_URL_RE = re.compile(r'https?://(?:www\.)?icarros\.com\.br/comprar/[^"\'\s]+?/\d{4}/d\d+(?:\?[^"\'\s]*)?', re.I)

_RE_PRICE = re.compile(r"R\$\s*[0-9\.]+(?:,[0-9]{1,2})?", re.I)
_RE_YEAR_IN_URL = re.compile(r"/(19\d{2}|20\d{2})/d\d+(?:$|[/?#])")
_RE_KM = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{1,7})\s*km\b", re.I)


def _canonical_url(url: str) -> str:
    """Drop query/fragment to avoid duplicates coming from 'pos=...' etc."""
    sp = urlsplit(url)
    return urlunsplit((sp.scheme, sp.netloc, sp.path, "", ""))


def _external_id(url: str) -> Optional[str]:
    m = re.search(r"/d(\d+)", url)
    return m.group(1) if m else None


def _is_listing_url(url: str) -> bool:
    return bool(_LISTING_ID_RE.match(url))


def _extract_year_from_url(url: str) -> Optional[int]:
    m = _RE_YEAR_IN_URL.search(url or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _slug_to_city_uf(slug: str) -> Optional[str]:
    """Convert 'sao-jose-do-rio-preto-sp' -> 'Sao Jose Do Rio Preto-SP'."""
    slug = (slug or "").strip().strip("/")
    if not slug:
        return None
    parts = [p for p in slug.split("-") if p]
    if len(parts) < 2:
        return None
    uf = parts[-1].upper()
    city = " ".join(p.capitalize() for p in parts[:-1])
    return f"{city}-{uf}"


def _extract_location_from_url(url: str) -> Optional[str]:
    """iCarros listing URLs often embed city/UF in the first path segment after /comprar/."""
    try:
        sp = urlsplit(url)
        path = sp.path.strip("/")
        seg = path.split("/")
        # /comprar/<city-uf>/...
        if len(seg) >= 2 and seg[0] == "comprar" and seg[1] not in ("usados", "novos"):
            return _slug_to_city_uf(seg[1])
    except Exception:
        return None
    return None


def _extract_make_model_city_from_url(url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (make, model, city_slug) from /comprar/<city-uf>/<make>/<model>/..."""
    try:
        sp = urlsplit(url)
        seg = sp.path.strip("/").split("/")
        # /comprar/<city-uf>/<make>/<model>/...
        if len(seg) >= 4 and seg[0] == "comprar":
            city_slug = seg[1]
            make = seg[2]
            model = seg[3]
            return make, model, city_slug
    except Exception:
        pass
    return None, None, None


def _pretty_slug(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip().strip("/")
    if not s:
        return None
    parts = re.split(r"[-_\s]+", s)
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if re.match(r"^[a-z]\d+$", p, re.I):
            out.append(p.upper())
        elif re.match(r"^\d+[a-z]+$", p, re.I):
            out.append(p.upper())
        else:
            out.append(p[:1].upper() + p[1:])
    return " ".join(out)


def _title_from_url(url: str) -> Optional[str]:
    make, model, _city = _extract_make_model_city_from_url(url)
    year = _extract_year_from_url(url)
    pm = _pretty_slug(make)
    pmodel = _pretty_slug(model)
    if pm and pmodel and year:
        return f"{pm} {pmodel} {year}"
    if pm and pmodel:
        return f"{pm} {pmodel}"
    return None


def _resolve_listing_url_from_fallback_page(html_text: str, *, requested_url: str, base_url: str) -> Optional[str]:
    """If iCarros redirects a listing URL to a catalog page (e.g. /a6#rfae),
    try to recover the real listing URL from the HTML (often contains the correct /<year>/d<id> link).
    """
    if not html_text:
        return None

    req_make, req_model, req_city = _extract_make_model_city_from_url(requested_url)
    req_year = _extract_year_from_url(requested_url)

    found: list[str] = []
    for u in _LISTING_URL_RE.findall(html_text):
        cu = _canonical_url(urljoin(base_url, u))
        if _is_listing_url(cu):
            found.append(cu)

    if not found:
        return None

    def _score(u: str) -> int:
        make, model, city = _extract_make_model_city_from_url(u)
        year = _extract_year_from_url(u)
        s = 0
        if req_city and city and req_city == city:
            s += 5
        if req_make and make and req_make == make:
            s += 3
        if req_model and model and req_model == model:
            s += 3
        if req_year and year and req_year == year:
            s += 4
        return s

    found = list(dict.fromkeys(found))
    found.sort(key=_score, reverse=True)
    best = found[0]
    if _score(best) >= 6:
        return best
    return None


def _extract_km(text: str) -> Optional[str]:
    """Extract odometer; ignore patterns like '| a 0 km' (distance-to-you)."""
    if not text:
        return None

    candidates: list[str] = []
    for m in _RE_KM.finditer(text):
        prefix = (text[max(0, m.start() - 6): m.start()] or "").lower()
        if re.search(r"(\b|\|)\s*a\s*$", prefix):
            # matches '| a ' just before the number
            continue
        candidates.append(m.group(1))

    if not candidates:
        return None

    # prefer thousands format
    for c in candidates:
        if re.match(r"^\d{1,3}(?:\.\d{3})+$", c):
            return c
    return candidates[0]


def _extract_prices(text: str) -> list[Decimal]:
    """Return all price-like BRL numbers found in a blob."""
    if not text:
        return []
    out: list[Decimal] = []
    for m in _RE_PRICE.finditer(text):
        d = parse_brl_price(m.group(0))
        if d is not None:
            out.append(d)
    return out


def _best_price(text: str) -> Optional[Decimal]:
    """Prefer 'por R$ X' when present; otherwise the highest BRL value."""
    if not text:
        return None

    # Prefer "por R$ ..."
    m = re.search(r"\bpor\s+(R\$\s*[0-9\.]+(?:,[0-9]{1,2})?)", text, re.I)
    if m:
        d = parse_brl_price(m.group(1))
        if d is not None:
            return d

    vals = _extract_prices(text)
    if not vals:
        return None
    return max(vals)


def _upgrade_image_url(url: str) -> str:
    """Try to upgrade thumbnail URLs to higher resolution."""
    if not url:
        return url

    # fit-in/320x240 -> fit-in/1600x1200
    url = re.sub(r"/fit-in/(\d{2,4})x(\d{2,4})/", "/fit-in/1600x1200/", url)

    # ...-320x240.jpg -> ...-1600x1200.jpg
    url = re.sub(
        r"(\D)(\d{2,4})x(\d{2,4})(\.(?:jpe?g|png|webp))\b",
        r"\g<1>1600x1200\g<4>",
        url,
        flags=re.I,
    )

    # query params w/h or width/height
    try:
        sp = urlsplit(url)
        qs = parse_qs(sp.query)
        changed = False
        for k in ("w", "width"):
            if k in qs:
                qs[k] = [str(max(int(qs[k][0]), 1600))]
                changed = True
        for k in ("h", "height"):
            if k in qs:
                qs[k] = [str(max(int(qs[k][0]), 900))]
                changed = True
        if changed:
            url = urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(qs, doseq=True), sp.fragment))
    except Exception:
        pass

    return url


def _is_tiny_image(url: str) -> bool:
    u = (url or "").lower()
    if "thumb" in u:
        return True
    m = re.search(r"[?&](?:w|width)=(\d+)", u)
    if m:
        try:
            return int(m.group(1)) <= 640
        except Exception:
            return False
    m2 = re.search(r"(\d{2,4})x(\d{2,4})\.(?:jpe?g|png|webp)\b", u)
    if m2:
        try:
            return int(m2.group(1)) <= 640
        except Exception:
            return False
    return False


def _extract_thumbnail_any(node, base_url: str) -> Optional[str]:
    candidates: list[str] = []

    # meta tags (detail pages)
    for v in node.xpath(".//meta[@property='og:image']/@content | .//meta[@name='twitter:image']/@content"):
        candidates.append(v)

    # images
    for img in node.xpath(".//img"):
        for attr in ("data-srcset", "srcset", "data-src", "data-lazy-src", "data-original", "src"):
            v = img.get(attr)
            if not v:
                continue
            if "srcset" in attr:
                picked = pick_from_srcset(v)
                if picked:
                    candidates.append(picked)
                else:
                    candidates.append(v.split(",")[0].strip().split(" ")[0])
            else:
                candidates.append(v)

    # picture sources
    for ss in node.xpath(".//picture//source[@srcset]/@srcset"):
        picked = pick_from_srcset(ss)
        if picked:
            candidates.append(picked)

    # background-image style
    for st in node.xpath(
        ".//*[@style and contains(translate(@style,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'background-image')]/@style"
    ):
        m = re.search(r"background-image\s*:\s*url\(([^)]+)\)", st, flags=re.I)
        if m:
            candidates.append(m.group(1).strip().strip('"\''))

    def _score(u: str) -> int:
        s = 0
        ul = (u or "").lower()
        if not ul or ul.startswith("data:"):
            return -50
        if "logo" in ul or "icon" in ul or "sprite" in ul:
            s -= 10
        if ul.endswith(".svg"):
            s -= 10
        if re.search(r"\.(jpe?g|png|webp)\b", ul):
            s += 4
        if "icarros" in ul:
            s += 2
        if "thumb" in ul:
            s -= 2
        m = re.search(r"[?&](?:w|width)=(\d+)", ul)
        if m:
            try:
                s += min(int(m.group(1)) // 200, 8)
            except Exception:
                pass
        m2 = re.search(r"(\d{2,4})x(\d{2,4})\.(?:jpe?g|png|webp)\b", ul)
        if m2:
            try:
                w = int(m2.group(1))
                h = int(m2.group(2))
                s += min((w * h) // (300 * 300), 8)
            except Exception:
                pass
        return s

    best_url: Optional[str] = None
    best_score = -10**9

    for raw in candidates:
        u = normalize_asset_url(raw, base_url)
        if not u:
            continue
        sc = _score(u)
        if sc > best_score:
            best_score = sc
            best_url = u

    if best_url:
        best_url = _upgrade_image_url(best_url)

    return best_url


def _looks_generic_title(title: Optional[str]) -> bool:
    t = (title or "").strip().lower()
    if not t:
        return True
    if t.startswith("comprar "):
        return True
    if t in ("comprar", "icarros", "carros usados", "comprar carros"):
        return True
    if len(t) < 10:
        return True
    return False


def _detail_enrich(listing: dict, ctx: ScrapeContext, *, limit_timeout_ms: int = 35000) -> dict:
    """Fetch detail page to improve title/price/thumb/km/location.

    iCarros sometimes redirects a listing URL to a catalog page (e.g. /a6#rfae) when the ad id is stale.
    In that case, attempt to recover the real listing URL from the fallback HTML and re-fetch.
    """
    url = listing.get("url") or ""
    if not url:
        return listing

    try:
        # Prefer networkidle on detail pages (SPA hydration), but fall back to domcontentloaded.
        try:
            res = fetch_html_browser(url, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="networkidle")
        except Exception:
            res = fetch_html_browser(url, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="domcontentloaded")

        html_text = res.html
        final_url = res.final_url or url
        logger.info("[icarros] detail nav requested_url=%s final_url=%s", url, final_url)

        base_url = final_url

        # If we landed on a non-listing URL (catalog), try to recover the real listing URL from HTML.
        if not _is_listing_url(_canonical_url(base_url)):
            resolved = _resolve_listing_url_from_fallback_page(html_text, requested_url=url, base_url=base_url)
            if resolved and resolved != _canonical_url(base_url):
                logger.info("[icarros] detail resolve requested_url=%s final_url=%s resolved_url=%s", url, base_url, resolved)
                try:
                    res2 = fetch_html_browser(resolved, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="networkidle")
                except Exception:
                    res2 = fetch_html_browser(resolved, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="domcontentloaded")
                html_text = res2.html
                base_url = res2.final_url or resolved
                listing["url"] = _canonical_url(base_url)
                ext2 = _external_id(base_url)
                if ext2:
                    listing["external_id"] = ext2
            else:
                # Don't trust metadata from catalog fallback pages.
                logger.info("[icarros] detail fallback non-listing (no resolve) requested_url=%s final_url=%s", url, base_url)
                if not listing.get("title"):
                    listing["title"] = _title_from_url(url)
                if not listing.get("location"):
                    listing["location"] = _extract_location_from_url(url)
                if not listing.get("year"):
                    y = _extract_year_from_url(url)
                    if y:
                        listing["year"] = y
                return listing

        doc = lxml_html.fromstring(html_text)
        doc.make_links_absolute(base_url)

        # Title: prefer og:title, then h1, then any strong header-like node
        title = None
        ogt = doc.xpath("string(//meta[@property='og:title']/@content)") or ""
        ogt = clean_text(ogt)
        if ogt and len(ogt) <= 180:
            title = ogt

        if _looks_generic_title(title):
            h1 = clean_text(doc.xpath("string(//h1[1])") or "")
            if h1 and 6 <= len(h1) <= 180:
                title = h1

        if _looks_generic_title(title):
            for xp in ("//h2", "//h3"):
                for n in doc.xpath(xp):
                    t = clean_text(n.text_content())
                    if t and "R$" not in t and 10 <= len(t) <= 180:
                        title = t
                        break
                if not _looks_generic_title(title):
                    break

        # Price: first try JSON-LD offers.price
        price: Optional[Decimal] = None
        for raw in doc.xpath("//script[@type='application/ld+json']/text()"):
            raw = (raw or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    p = offers.get("price")
                    cur = offers.get("priceCurrency")
                    if p is not None and (cur in (None, "", "BRL")):
                        try:
                            price = Decimal(str(p))
                            break
                        except Exception:
                            pass
                if price is not None:
                    break
            if price is not None:
                break

        if price is None:
            price = _best_price(clean_text(doc.text_content()))

        # Thumbnail
        thumb = _extract_thumbnail_any(doc, base_url=base_url)

        # KM
        km = _extract_km(clean_text(doc.text_content()))

        # Location
        # Location: from URL
        location = listing.get("location") or _extract_location_from_url(base_url)

        if title and not _looks_generic_title(title):
            title = re.sub(r"^comprar\s+", "", title, flags=re.I).strip()
            listing["title"] = title

        if not listing.get("title"):
            listing["title"] = _title_from_url(base_url) or _title_from_url(url)

        if price is not None:
            listing["price"] = price

        if thumb and (not listing.get("thumbnail_url") or _is_tiny_image(listing.get("thumbnail_url") or "")):
            listing["thumbnail_url"] = thumb

        if km and not listing.get("km"):
            listing["km"] = km

        if location and not listing.get("location"):
            listing["location"] = location

        y = listing.get("year") or _extract_year_from_url(base_url)
        if y and not listing.get("year"):
            listing["year"] = y

    except Exception:
        return listing

    return listing

    try:
        res = fetch_html_browser(url, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="domcontentloaded")
        html_text = res.html
        base_url = res.final_url or url

        doc = lxml_html.fromstring(html_text)
        doc.make_links_absolute(base_url)

        # Title: prefer og:title, then h1, then any strong header-like node
        title = None
        ogt = doc.xpath("string(//meta[@property='og:title']/@content)") or ""
        ogt = clean_text(ogt)
        if ogt and len(ogt) <= 180:
            title = ogt

        if _looks_generic_title(title):
            h1 = clean_text(doc.xpath("string(//h1[1])") or "")
            if h1 and 6 <= len(h1) <= 180:
                title = h1

        if _looks_generic_title(title):
            for xp in ("//h2", "//h3"):
                for n in doc.xpath(xp):
                    t = clean_text(n.text_content())
                    if t and "R$" not in t and 10 <= len(t) <= 180:
                        title = t
                        break
                if not _looks_generic_title(title):
                    break

        # Price: first try JSON-LD offers.price
        price: Optional[Decimal] = None
        for raw in doc.xpath("//script[@type='application/ld+json']/text()"):
            raw = (raw or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            # data can be list or dict
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if not isinstance(obj, dict):
                    continue
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    p = offers.get("price")
                    cur = offers.get("priceCurrency")
                    if p is not None and (cur in (None, "", "BRL")):
                        try:
                            price = Decimal(str(p))
                            break
                        except Exception:
                            pass
                if price is not None:
                    break
            if price is not None:
                break

        if price is None:
            # fallback: best price from visible text
            price = _best_price(clean_text(doc.text_content()))

        # Thumbnail: prefer richer sources on detail
        thumb = _extract_thumbnail_any(doc, base_url=base_url)

        # KM: from detail text (more reliable)
        km = _extract_km(clean_text(doc.text_content()))

        # Location: from URL (detail has it)
        location = listing.get("location") or _extract_location_from_url(base_url)
        # Pack year/km into title (avoid extra DB columns)
        y = _extract_year_from_url(base_url)
        km = _extract_km(_clean_text(doc.text_content()))
        if title:
            if y and not re.search(r"\b(19\d{2}|20\d{2})\b", title):
                title = f"{title} {y}"
            if km and "km" not in title.lower():
                title = f"{title} • {km:,}".replace(",", ".") + " km"

        if title and not _looks_generic_title(title):
            listing["title"] = title
        if price is not None:
            listing["price"] = price
        if thumb and (not listing.get("thumbnail_url") or _is_tiny_image(listing.get("thumbnail_url") or "")):
            listing["thumbnail_url"] = thumb
        if location and not listing.get("location"):
            listing["location"] = location

    except Exception:
        return listing

    return listing


def scrape_icarros(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """iCarros scraper (Playwright-first).

    Strategy:
    - Fetch the search page in Playwright (iCarros blocks simple HTTP).
    - Extract listing URLs quickly.
    - Enrich a limited number of listings using the detail page to get:
      high-res photo + accurate title + correct price + km + location.
    """
    res = fetch_html_browser(search_url, ctx=ctx, timeout_ms=45000, wait_until="domcontentloaded")
    html_text = res.html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(res.final_url or search_url)

    base_url = res.final_url or search_url

    by_ext: dict[str, dict] = {}

    # Fast pass: grab listing URLs (anchors + regex fallback)
    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        if not href:
            continue
        url = urljoin(base_url, href)
        if "icarros.com.br" not in url:
            continue

        url = _canonical_url(url)
        if not _is_listing_url(url):
            continue

        ext = _external_id(url)
        if not ext:
            continue
        if ext in by_ext:
            continue

        # Minimal info now; enrich later.
        by_ext[ext] = {
            "source": "icarros",
            "external_id": ext,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": _extract_location_from_url(url),
            "year": _extract_year_from_url(url),
            "km": None,
        }

    if not by_ext:
        for full_url in _LISTING_URL_RE.findall(html_text):
            canonical = _canonical_url(full_url)
            if not _is_listing_url(canonical):
                continue
            ext = _external_id(canonical)
            if not ext or ext in by_ext:
                continue
            by_ext[ext] = {
                "source": "icarros",
                "external_id": ext,
                "url": canonical,
                "title": None,
                "price": None,
                "thumbnail_url": None,
                "location": _extract_location_from_url(canonical),
                "year": _extract_year_from_url(canonical),
                "km": None,
            }

    items = list(by_ext.values())

    # Enrich first N (enough to improve user experience + matching on Pi)
    ENRICH_MAX = 5
    enriched: list[dict] = []
    for i, it in enumerate(items):
        if i < ENRICH_MAX:
            it = _detail_enrich(it, ctx)
        enriched.append(it)

    return enriched
