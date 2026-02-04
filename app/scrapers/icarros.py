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
_LISTING_URL_RE = re.compile(r'https?://(?:www\.)?icarros\.com\.br/comprar/[^"\'\s]+?/\d{4}/d\d+(?:\?[^"\'\s]*)?', re.I)

_RE_PRICE = re.compile(r"R\$\s*[0-9\.]+(?:,[0-9]{1,2})?", re.I)
_RE_YEAR_IN_URL = re.compile(r"/(19\d{2}|20\d{2})/d\d+(?:$|[/?#])")
_RE_KM = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{1,7})\s*km\b", re.I)

logger = logging.getLogger(__name__)


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


def _is_default_share_logo(url: str) -> bool:
    u = (url or "").lower()
    return "logo_icarros_compartilhar" in u or "/comum/imagens/logo_icarros" in u


def _deep_collect_strings(obj, out: set[str]) -> None:
    if obj is None:
        return
    if isinstance(obj, str):
        s = obj.strip()
        if s:
            out.add(s)
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _deep_collect_strings(v, out)
        return
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _deep_collect_strings(v, out)
        return


def _extract_next_data(doc) -> Optional[dict]:
    raw = doc.xpath("string(//script[@id='__NEXT_DATA__']/text())") or ""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _extract_jsonld_objects(doc) -> list[dict]:
    objs: list[dict] = []
    for raw in doc.xpath("//script[@type='application/ld+json']/text()"):
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            objs.append(data)
        elif isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    objs.append(it)
    return objs


def _extract_images_from_structured(doc, base_url: str) -> list[str]:
    imgs: list[str] = []

    # JSON-LD: image / thumbnailUrl
    for obj in _extract_jsonld_objects(doc):
        for k in ("image", "thumbnailUrl"):
            v = obj.get(k)
            if isinstance(v, str):
                imgs.append(v)
            elif isinstance(v, list):
                for it in v:
                    if isinstance(it, str):
                        imgs.append(it)

    # Next.js data: scan for URL-like strings
    nd = _extract_next_data(doc)
    if nd:
        sset: set[str] = set()
        _deep_collect_strings(nd, sset)
        for s in sset:
            if not isinstance(s, str):
                continue
            if "icarros" not in s and not s.startswith("/") and not s.startswith("http"):
                continue
            if re.search(r"\.(?:jpe?g|png|webp)\b", s, re.I) or "fit-in/" in s or "img" in s.lower():
                imgs.append(s)

    # Normalize + filter
    out: list[str] = []
    seen: set[str] = set()
    for raw in imgs:
        u = _normalize_asset_url(raw, base_url)
        if not u:
            continue
        if _is_default_share_logo(u):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _extract_price_from_structured(doc) -> Optional[Decimal]:
    # JSON-LD offers.price is the best signal
    for obj in _extract_jsonld_objects(doc):
        offers = obj.get("offers")
        if isinstance(offers, dict):
            p = offers.get("price")
            cur = offers.get("priceCurrency")
            if p is not None and (cur in (None, "", "BRL")):
                try:
                    return Decimal(str(p))
                except Exception:
                    pass

    # Next.js data: pick the largest plausible 'price' number we find
    nd = _extract_next_data(doc)
    if not nd:
        return None

    vals: list[Decimal] = []

    def _walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                lk = str(k).lower()
                if lk in ("price", "preco", "valor", "pricevalue", "amount"):
                    if isinstance(v, (int, float, str)):
                        try:
                            d = Decimal(str(v).replace(".", "").replace(",", "."))
                            vals.append(d)
                        except Exception:
                            pass
                _walk(v)
        elif isinstance(o, list):
            for it in o:
                _walk(it)

    _walk(nd)

    plausible = [d for d in vals if d >= 2000 and d <= 5000000]
    return max(plausible) if plausible else None


def _extract_listing_urls_from_dom(doc, base_url: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for href in doc.xpath("//a[@href]/@href"):
        u = urljoin(base_url, href)
        u = _canonical_url(u)
        if not _is_listing_url(u):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)

    # Next.js data scan (collect strings and match URLs)
    nd = _extract_next_data(doc)
    if nd:
        sset: set[str] = set()
        _deep_collect_strings(nd, sset)
        for s in sset:
            if not isinstance(s, str):
                continue
            if "/comprar/" not in s or "/d" not in s:
                continue
            u = urljoin(base_url, s)
            u = _canonical_url(u)
            if _is_listing_url(u) and u not in seen:
                seen.add(u)
                out.append(u)

    return out


def _resolve_listing_url_from_fallback(doc, base_url: str, requested_url: str) -> Optional[str]:
    req_year = _extract_year_from_url(requested_url)
    req_city = _extract_location_from_url(requested_url)

    make = model = None
    try:
        sp = urlsplit(requested_url)
        seg = sp.path.strip("/").split("/")
        if len(seg) >= 4 and seg[0] == "comprar":
            make = seg[2].lower()
            model = seg[3].lower()
    except Exception:
        pass

    cands = _extract_listing_urls_from_dom(doc, base_url)
    if not cands:
        return None

    def _score(u: str) -> int:
        s = 0
        ul = u.lower()
        if req_year and f"/{req_year}/" in ul:
            s += 5
        if req_city:
            # partial match for slug is enough
            slug = req_city.lower().replace(" ", "-")
            if slug[:6] in ul:
                s += 3
        if make and f"/{make}/" in ul:
            s += 2
        if model and f"/{model}/" in ul:
            s += 2
        return s

    cands.sort(key=_score, reverse=True)
    return cands[0]

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


def _pick_from_srcset(srcset: str, *, max_width: int = 2048) -> Optional[str]:
    """Pick a good URL from a srcset string.

    Prefer the largest width <= max_width; if none, pick the largest available.
    """
    if not srcset:
        return None

    candidates: list[tuple[int, str]] = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        u = bits[0].strip()
        w = 0
        if len(bits) >= 2:
            m = re.match(r"(\d+)w$", bits[1].strip())
            if m:
                try:
                    w = int(m.group(1))
                except Exception:
                    w = 0
        candidates.append((w, u))

    if not candidates:
        return None

    le = [c for c in candidates if c[0] and c[0] <= max_width]
    if le:
        le.sort(key=lambda x: x[0], reverse=True)
        return le[0][1]

    candidates.sort(key=lambda x: x[0], reverse=True)
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


def _upgrade_image_url(url: str) -> str:
    """Try to upgrade thumbnail URLs to higher resolution."""
    if not url:
        return url

    url = re.sub(r"/fit-in/(\d{2,4})x(\d{2,4})/", "/fit-in/1600x1200/", url)
    url = re.sub(r"(\D)(\d{2,4})x(\d{2,4})(\.(?:jpe?g|png|webp))\b", r"\g<1>1600x1200\g<4>", url, flags=re.I)

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

    for v in node.xpath(".//meta[@property='og:image']/@content | .//meta[@name='twitter:image']/@content"):
        candidates.append(v)

    candidates.extend(_extract_images_from_structured(node, base_url))

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

    for ss in node.xpath(".//picture//source[@srcset]/@srcset"):
        picked = _pick_from_srcset(ss)
        if picked:
            candidates.append(picked)

    for st in node.xpath(
        ".//*[@style and contains(translate(@style,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'background-image')]/@style"
    ):
        m = re.search(r"background-image\s*:\s*url\(([^)]+)\)", st, flags=re.I)
        if m:
            candidates.append(m.group(1).strip().strip('"\''))

    def _score(u: str) -> int:
        ul = (u or "").lower()
        if not ul or ul.startswith("data:"):
            return -50
        if _is_default_share_logo(ul):
            return -999

        s = 0
        if "logo" in ul or "icon" in ul or "sprite" in ul:
            s -= 20
        if ul.endswith(".svg"):
            s -= 20
        if re.search(r"\.(jpe?g|png|webp)\b", ul):
            s += 6
        if "icarros" in ul:
            s += 2
        if "thumb" in ul:
            s -= 4

        m = re.search(r"[?&](?:w|width)=(\d+)", ul)
        if m:
            try:
                s += min(int(m.group(1)) // 200, 10)
            except Exception:
                pass
        m2 = re.search(r"(\d{2,4})x(\d{2,4})(?:\.(?:jpe?g|png|webp)\b|/)", ul)
        if m2:
            try:
                w = int(m2.group(1))
                h = int(m2.group(2))
                s += min((w * h) // (300 * 300), 12)
            except Exception:
                pass
        return s

    best_url: Optional[str] = None
    best_score = -10**9

    for raw in candidates:
        u = _normalize_asset_url(raw, base_url)
        if not u:
            continue
        if _is_default_share_logo(u):
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


def _detail_enrich(listing: dict, ctx: ScrapeContext, *, limit_timeout_ms: int = 45000) -> dict:
    """Fetch detail page to improve title/price/thumb/location (Playwright-first)."""
    url = listing.get("url") or ""
    if not url:
        return listing

    try:
        res = fetch_html_browser(url, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="domcontentloaded")
        html_text = res.html
        base_url = res.final_url or url

        logger.info("[icarros] detail nav requested_url=%s final_url=%s", url, base_url)

        doc = lxml_html.fromstring(html_text)
        doc.make_links_absolute(base_url)

        # Resolve redirect/fallback pages (ex: /a6#rfae)
        if not _is_listing_url(_canonical_url(base_url)):
            resolved = _resolve_listing_url_from_fallback(doc, base_url, url)
            if resolved and _is_listing_url(resolved):
                logger.info("[icarros] detail resolve requested_url=%s final_url=%s resolved_url=%s", url, base_url, resolved)
                res2 = fetch_html_browser(resolved, ctx=ctx, timeout_ms=limit_timeout_ms, wait_until="domcontentloaded")
                html_text = res2.html
                base_url = res2.final_url or resolved
                doc = lxml_html.fromstring(html_text)
                doc.make_links_absolute(base_url)
                listing["url"] = _canonical_url(base_url)
                ext = _external_id(base_url)
                if ext:
                    listing["external_id"] = ext

        # Title: prefer og:title, then h1, then headers
        title = None
        ogt = _clean_text(doc.xpath("string(//meta[@property='og:title']/@content)") or "")
        if ogt:
            head = ogt.split(" - ")[0].strip()
            if 6 <= len(head) <= 180:
                title = head

        if _looks_generic_title(title):
            h1 = _clean_text(doc.xpath("string(//h1[1])") or "")
            if h1 and 6 <= len(h1) <= 180:
                title = h1

        if _looks_generic_title(title):
            for xp in ("//h2", "//h3"):
                for n in doc.xpath(xp):
                    t = _clean_text(n.text_content())
                    if t and "R$" not in t and 10 <= len(t) <= 180:
                        title = t
                        break
                if not _looks_generic_title(title):
                    break

        if title:
            title = re.sub(r"^comprar\s+", "", title, flags=re.I).strip()

        # Price: structured > text
        price: Optional[Decimal] = _extract_price_from_structured(doc)
        if price is None:
            price = _best_price(_clean_text(doc.text_content()))

        # Thumbnail
        thumb = _extract_thumbnail_any(doc, base_url=base_url)
        if thumb and _is_default_share_logo(thumb):
            thumb = None

        # Location: from URL
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
