from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from lxml import html as lxml_html

from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


_ICARROS_BASE = "https://www.icarros.com.br"

# Canonical iCarros listing pattern:
# https://www.icarros.com.br/comprar/<city-uf>/<make>/<model>/<year>/d<id>
_LISTING_ID_RE = re.compile(r"^https?://(?:www\.)?icarros\.com\.br/comprar/.+/\d{4}/d(\d+)(?:$|[/?#])", re.I)
_LISTING_URL_RE = re.compile(r'(?:https?://(?:www\.)?icarros\.com\.br)?/comprar/[^"\'\s]+?/\d{4}/d\d+(?:\?[^"\'\s]*)?', re.I)

_RE_PRICE = re.compile(r"R\$\s*[0-9\.]+(?:,[0-9]{1,2})?", re.I)
_RE_YEAR_IN_URL = re.compile(r"/(19\d{2}|20\d{2})/d\d+(?:$|[/?#])")
_RE_KM = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{1,7})\s*km\b", re.I)


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


def _pick_from_srcset(srcset: str, *, max_width: int = 1600) -> Optional[str]:
    """Pick a good URL from a srcset string."""
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
    return candidates[-1][1]  # if no widths, pick the last (often best)


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


def _upgrade_image_url(url: str) -> str:
    """Try to upgrade thumbnail URLs to higher resolution."""
    if not url:
        return url

    # fit-in/320x240 -> fit-in/1280x960
    url = re.sub(r"/fit-in/(\d{2,4})x(\d{2,4})/", "/fit-in/1280x960/", url)

    # ...-320x240.jpg -> ...-1280x960.jpg
    url = re.sub(r"(\D)(\d{2,4})x(\d{2,4})(\.(?:jpe?g|png|webp))\b", r"\g<1>1280x960\g<4>", url, flags=re.I)

    # query params w/h or width/height
    try:
        sp = urlsplit(url)
        qs = parse_qs(sp.query)
        changed = False
        for k in ("w", "width"):
            if k in qs:
                qs[k] = [str(max(int(qs[k][0]), 1280))]
                changed = True
        for k in ("h", "height"):
            if k in qs:
                qs[k] = [str(max(int(qs[k][0]), 720))]
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
            return int(m.group(1)) <= 420
        except Exception:
            return False
    m2 = re.search(r"(\d{2,4})x(\d{2,4})\.(?:jpe?g|png|webp)\b", u)
    if m2:
        try:
            return int(m2.group(1)) <= 420
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
                picked = _pick_from_srcset(v)
                if picked:
                    candidates.append(picked)
                else:
                    candidates.append(v.split(",")[0].strip().split(" ")[0])
            else:
                candidates.append(v)

    # picture sources
    for ss in node.xpath(".//picture//source[@srcset]/@srcset"):
        picked = _pick_from_srcset(ss)
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
        if "logo_icarros_compartilhar" in ul:
            return -200
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
        u = _normalize_asset_url(raw, base_url)
        if not u:
            continue
        sc = _score(u)
        if sc > best_score:
            best_score = sc
            best_url = u

    if best_url:
        best_url = _upgrade_image_url(best_url)
        if "logo_icarros_compartilhar" in (best_url or "").lower():
            return None

    return best_url



def _split_og_title(og_title: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split iCarros og:title into (clean_title, location) when possible."""
    t = _clean_text(og_title or "")
    if not t:
        return None, None

    t = re.sub(r"\s*-\s*iCarros\s*$", "", t, flags=re.I).strip()
    t = re.sub(r"\s*\.\s*An[úu]ncio\s+\d+.*$", "", t, flags=re.I).strip()

    parts = [p.strip() for p in t.split(" - ") if p.strip()]
    if len(parts) >= 4 and re.fullmatch(r"[A-Z]{2}", parts[-1]):
        uf = parts[-1]
        city = parts[-2]
        car = " - ".join(parts[:-3]).strip() or parts[0]
        loc = f"{city}-{uf}"
        return car, loc

    return t, None

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


def _resolve_listing_url_from_fallback_page(html_text: str, base_url: str, requested_url: str) -> Optional[str]:
    """When iCarros redirects a detail URL to a model/catalog page (e.g. /a6#rfae),
    try to find a real listing URL in the HTML and return its canonical absolute URL.
    """
    if not html_text:
        return None

    # Hints from requested URL
    req_year = _extract_year_from_url(requested_url)
    try:
        sp = urlsplit(requested_url)
        seg = sp.path.strip("/").split("/")
        # /comprar/<city-uf>/<make>/<model>/<year>/d<id>
        req_city = seg[1] if len(seg) > 1 and seg[0] == "comprar" else None
        req_make = seg[2] if len(seg) > 2 and seg[0] == "comprar" else None
        req_model = seg[3] if len(seg) > 3 and seg[0] == "comprar" else None
    except Exception:
        req_city = req_make = req_model = None

    cands: list[str] = []
    for raw in _LISTING_URL_RE.findall(html_text):
        abs_u = urljoin(base_url, raw)
        canon = _canonical_url(abs_u)
        if _is_listing_url(canon):
            cands.append(canon)

    if not cands:
        return None

    # Score: prefer same city/make/model/year
    def _score(u: str) -> int:
        sc = 0
        try:
            sp2 = urlsplit(u)
            seg2 = sp2.path.strip("/").split("/")
            city2 = seg2[1] if len(seg2) > 1 and seg2[0] == "comprar" else None
            make2 = seg2[2] if len(seg2) > 2 and seg2[0] == "comprar" else None
            model2 = seg2[3] if len(seg2) > 3 and seg2[0] == "comprar" else None
        except Exception:
            city2 = make2 = model2 = None

        if req_city and city2 == req_city:
            sc += 5
        if req_make and make2 == req_make:
            sc += 4
        if req_model and model2 == req_model:
            sc += 4
        y = _extract_year_from_url(u)
        if req_year and y == req_year:
            sc += 6
        return sc

    best = max(cands, key=_score)
    return best


def _extract_price_from_structured(doc) -> Optional[Decimal]:
    """Try JSON-LD / structured data first, as iCarros pages can contain multiple BRL numbers."""
    try:
        scripts = doc.xpath("//script[@type='application/ld+json']/text()")
    except Exception:
        scripts = []

    def _walk(obj):
        if isinstance(obj, dict):
            # offers.price
            if "offers" in obj:
                offers = obj.get("offers")
                for it in (offers if isinstance(offers, list) else [offers]):
                    if isinstance(it, dict):
                        price = it.get("price") or it.get("priceValue") or it.get("lowPrice") or it.get("highPrice")
                        if price is not None:
                            yield price
                        ps = it.get("priceSpecification")
                        if isinstance(ps, dict) and ps.get("price") is not None:
                            yield ps.get("price")
            # direct price fields
            for k in ("price", "priceValue"):
                if k in obj and obj.get(k) is not None:
                    yield obj.get(k)
            for v in obj.values():
                yield from _walk(v)
        elif isinstance(obj, list):
            for it in obj:
                yield from _walk(it)

    for s in scripts:
        s = (s or "").strip()
        if not s:
            continue
        try:
            data = json.loads(s)
        except Exception:
            continue

        for val in _walk(data):
            # normalize val to Decimal
            if isinstance(val, (int, float, Decimal)):
                try:
                    return Decimal(str(val))
                except Exception:
                    continue
            if isinstance(val, str):
                # "189900" or "R$ 189.900,00"
                if re.fullmatch(r"\d+(?:\.\d+)?", val.strip()):
                    try:
                        return Decimal(val.strip())
                    except Exception:
                        continue
                d = parse_brl_price(val)
                if d is not None:
                    return d

    return None



def _extract_price_from_meta(doc) -> Optional[Decimal]:
    """Best-effort extraction from meta tags (often stable even when the body is JS-rendered)."""
    try:
        vals = doc.xpath(
            "//meta[@property='product:price:amount']/@content"
            " | //meta[@property='og:price:amount']/@content"
            " | //meta[@property='og:price']/@content"
            " | //meta[@property='product:price']/@content"
            " | //meta[@itemprop='price']/@content"
            " | //meta[@name='twitter:data1']/@content"
            " | //meta[@name='twitter:data2']/@content"
            " | //meta[@name='description']/@content"
        )
    except Exception:
        vals = []

    for v in vals or []:
        s = (v or "").strip()
        if not s:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", s):
            try:
                d = Decimal(s)
                if d > 0:
                    return d
            except Exception:
                pass
        d = parse_brl_price(s)
        if d is not None:
            return d
    return None


def _extract_price_from_dom(doc) -> Optional[Decimal]:
    """Try to find price-like nodes in the rendered DOM."""
    xpaths = [
        # common price containers
        "//*[contains(translate(@class,'PRECO','preco'),'preco') or contains(translate(@class,'PRICE','price'),'price')]",
        "//*[contains(translate(@data-testid,'PRICE','price'),'price') or contains(translate(@data-qa,'PRICE','price'),'price')]",
        # label -> value patterns
        "//*[contains(translate(normalize-space(.),'PREÇO','preço'),'preço') or contains(translate(normalize-space(.),'PRECO','preco'),'preco')]",
    ]
    texts: list[str] = []
    for xp in xpaths:
        try:
            for el in doc.xpath(xp):
                try:
                    t = _clean_text(el.text_content() or "")
                except Exception:
                    t = ""
                if t and ("R$" in t or "preço" in t.lower() or "preco" in t.lower()):
                    texts.append(t)
        except Exception:
            continue

    # Prefer a direct BRL match near the beginning
    for t in texts:
        m = re.search(r"(R\$\s*[0-9\.]+(?:,[0-9]{2})?)", t)
        if m:
            d = parse_brl_price(m.group(1))
            if d is not None:
                return d

    # fallback: pick best from the combined snippets
    if texts:
        return _best_price(" ".join(texts))
    return None


def _extract_price_from_scripts(html_text: str) -> Optional[Decimal]:
    """Scan inline scripts for common price keys."""
    if not html_text:
        return None

    # Keyed BRL string first (priceValue/preco/valor)
    pats = [
        r'"(?:priceValue|listingPrice|preco|valor|price)"\s*:\s*"(R\$\s*[0-9\.]+(?:,[0-9]{2})?)"',
        r"'(?:priceValue|listingPrice|preco|valor|price)'\s*:\s*'(R\$\s*[0-9\.]+(?:,[0-9]{2})?)'",
    ]
    for p in pats:
        m = re.search(p, html_text, flags=re.I)
        if m:
            d = parse_brl_price(m.group(1))
            if d is not None:
                return d

    # Numeric price fields: capture multiple and pick a plausible max
    nums: list[Decimal] = []
    for m in re.finditer(r'"(?:priceValue|listingPrice|preco|valor|price)"\s*:\s*([0-9]{4,8})(?:\.[0-9]{1,2})?', html_text, flags=re.I):
        try:
            d = Decimal(m.group(1))
            if Decimal(5000) <= d <= Decimal(20000000):
                nums.append(d)
        except Exception:
            pass

    return max(nums) if nums else None


def _extract_price_any(*, html_text: str, doc) -> Optional[Decimal]:
    return (
        _extract_price_from_structured(doc)
        or _extract_price_from_meta(doc)
        or _extract_price_from_dom(doc)
        or _extract_price_from_scripts(html_text)
        or _best_price(_clean_text(getattr(doc, "text_content", lambda: "")() or ""))
    )

def _detail_enrich(listing: dict, ctx: ScrapeContext, *, limit_timeout_ms: int = 35000) -> dict:
    """Fetch detail page to improve title/price/thumb/km/location.

    NOTE: Do NOT add non-column keys (year/km) to the listing dict here to avoid DB insert crashes.
    If we find year/km, we append them to the title (the bot can render them nicely).
    """
    url = listing.get("url") or ""
    if not url:
        return listing

    logger = logging.getLogger(__name__)

    # 1) fetch initial URL
    res = fetch_html_browser(url, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="domcontentloaded")
    html_text = res.html or ""
    base_url = res.final_url or url
    final_url = _canonical_url(base_url)

    logger.info("[icarros] detail nav requested_url=%s final_url=%s", url, base_url)

    # parse DOM
    doc = lxml_html.fromstring(html_text) if html_text else lxml_html.fromstring("<html/>")
    doc.make_links_absolute(base_url)

    # 2) if redirected to catalog (e.g. /a6#rfae), resolve real listing URL from page HTML
    if not _is_listing_url(final_url):
        resolved = _resolve_listing_url_from_fallback_page(html_text, base_url, url)
        if resolved and resolved != final_url:
            logger.info("[icarros] detail resolve requested_url=%s final_url=%s resolved_url=%s", url, base_url, resolved)
            res2 = fetch_html_browser(resolved, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="domcontentloaded")
            html_text = res2.html or ""
            base_url = res2.final_url or resolved
            final_url = _canonical_url(base_url)
            doc = lxml_html.fromstring(html_text) if html_text else lxml_html.fromstring("<html/>")
            doc.make_links_absolute(base_url)

    # update canonical URL + external_id
    listing["url"] = final_url
    ext = _external_id(final_url)
    if ext:
        listing["external_id"] = ext

    # 3) title & location
    og_title_vals = doc.xpath("//meta[@property='og:title']/@content | //meta[@name='twitter:title']/@content")
    og_title = _clean_text(og_title_vals[0]) if og_title_vals else None
    clean_title, loc_from_og = _split_og_title(og_title)

    title = clean_title
    if _looks_generic_title(title):
        # fallback: h1
        h1 = doc.xpath("string(//h1[1])")
        h1 = _clean_text(h1)
        if h1 and not _looks_generic_title(h1):
            title = h1

    # fallback: from url make/model + year
    if _looks_generic_title(title):
        try:
            seg = urlsplit(final_url).path.strip("/").split("/")
            # /comprar/<city-uf>/<make>/<model>/<year>/d<id>
            if len(seg) >= 6 and seg[0] == "comprar":
                make = seg[2].upper()
                model = seg[3].replace("-", " ").upper()
                y = seg[4]
                title = f"{make} {model} {y}"
        except Exception:
            pass

    location = listing.get("location") or loc_from_og or _extract_location_from_url(final_url)

    # 4) image (ignore generic logo)
    thumb = _extract_thumbnail_any(doc, base_url)
    if thumb:
        thumb = _upgrade_image_url(thumb)

    # 5) price
    price = listing.get("price")
    if price is None:
        price = _extract_price_any(html_text=html_text, doc=doc)

# 6) year/km hints (append to title; do NOT add keys)
    y = _extract_year_from_url(final_url) or _extract_year_from_url(url)
    km = _extract_km(doc.text_content() or "")

    title_out = title or listing.get("title")
    if title_out:
        if y and str(y) not in title_out:
            title_out = f"{title_out} {y}"
        if km and ("km" not in title_out.lower()):
            title_out = f"{title_out} {km} km"
        title_out = _clean_text(title_out)

    # 7) apply back
    if title_out and not _looks_generic_title(title_out):
        listing["title"] = title_out
    if price is not None:
        listing["price"] = price
    if thumb:
        listing["thumbnail_url"] = thumb
    if location:
        listing["location"] = location

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
                    }

    if not by_ext:
        for full_url in _LISTING_URL_RE.findall(html_text):
            abs_u = urljoin(base_url, full_url)
            canonical = _canonical_url(abs_u)
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
