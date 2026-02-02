from __future__ import annotations

import json
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

def _deconcat(s: str) -> str:
    s = s or ""
    s = re.sub(r"([A-Za-zÀ-ÿ])([0-9])", r"\1 \2", s)
    s = re.sub(r"([0-9])([A-Za-zÀ-ÿ])", r"\1 \2", s)
    s = re.sub(r"(km)([A-Za-zÀ-ÿ])", r"\1 \2", s, flags=re.IGNORECASE)
    return _clean_text(s)


_NOISE_RE = re.compile(
    r"\b(comparar|simular|ver\s+parcelas|financiamento|detalhes)\b",
    re.IGNORECASE,
)


def _strip_title_noise(t: str) -> str:
    t = _deconcat(t)
    # corta no primeiro 'Comparar' (e também tira 'a 0 km')
    t = re.split(r"\bcomparar\b", t, flags=re.IGNORECASE)[0]
    t = re.sub(r"\b[aà]\s*0\s*km\b", "", t, flags=re.IGNORECASE)

    # se aparecer preço, corta antes dele
    if "R$" in t:
        t = t.split("R$", 1)[0]

    # corta ao encontrar quilometragem / separador
    t = re.split(r"\b\d{1,3}(?:\.\d{3})*\s*km\b", t, flags=re.IGNORECASE)[0]
    t = t.split("|", 1)[0]

    # remove tokens UI que sobraram
    t = _NOISE_RE.sub("", t)
    return _clean_text(t)




def _find_card_container(el, *, max_depth: int = 12):
    """Best-effort: climb parents and pick the container most likely to be the full card.

    Mobiauto often puts the /detalhes/ href in small nested anchors, while the
    title/price/thumb live in higher containers.
    """
    cur = el
    best = el
    best_score = -1

    for _ in range(max_depth):
        if cur is None:
            break

        try:
            txt = (cur.text_content() or "").replace(" ", " ")
            txt = re.sub(r"\s+", " ", txt).strip()
        except Exception:
            txt = ""

        score = 0
        if "R$" in txt:
            score += 8

        # image-ish elements
        try:
            score += len(cur.xpath(".//img")) * 3
        except Exception:
            pass

        try:
            score += len([1 for st in cur.xpath(".//*[@style]/@style") if "background-image" in (st or "")]) * 2
        except Exception:
            pass

        # longer text usually indicates a complete card
        score += min(len(txt), 400) // 80

        if score > best_score:
            best, best_score = cur, score

        cur = cur.getparent()


    # NOTE: lxml elements have confusing truthiness (historically depended on
    # children count). Avoid `best or el` to prevent FutureWarning.
    return best if best is not None else el


def _is_bad_image_url(u: str) -> bool:
    low = (u or "").lower()
    return any(x in low for x in ("logo", "sprite", "icon")) or low.endswith(".svg")


def _extract_head_image(doc, base_url: str) -> Optional[str]:
    """Try to extract a representative image from <head> metadata."""
    xps = (
        "//meta[@property='og:image']/@content",
        "//meta[@name='og:image']/@content",
        "//meta[@property='twitter:image']/@content",
        "//meta[@name='twitter:image']/@content",
        "//link[@rel='preload' and @as='image']/@href",
    )
    for xp in xps:
        for c in doc.xpath(xp):
            c = (c or "").strip()
            if not c:
                continue
            u = urljoin(base_url, c)
            if not u or u.startswith("data:"):
                continue
            if _is_bad_image_url(u):
                continue
            return u
    return None


def _json_loads_best_effort(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        # sometimes multiple JSON objects are concatenated; try to isolate the first
        try:
            if raw.startswith("{") and raw.endswith("}"):
                return json.loads(raw)
            raw2 = raw.rstrip(";\n ")
            return json.loads(raw2)
        except Exception:
            return None


def _find_first_image_in_obj(obj) -> Optional[str]:
    if obj is None:
        return None

    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("http") and re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", s, flags=re.I):
            return s
        return None

    if isinstance(obj, dict):
        # prefer common image keys
        for k in ("image", "images", "photo", "photos", "thumbnail", "thumbnailUrl", "url"):
            if k in obj:
                found = _find_first_image_in_obj(obj.get(k))
                if found:
                    return found
        for v in obj.values():
            found = _find_first_image_in_obj(v)
            if found:
                return found
        return None

    if isinstance(obj, (list, tuple)):
        for v in obj:
            found = _find_first_image_in_obj(v)
            if found:
                return found
        return None

    return None


def _extract_structured_image(doc, base_url: str) -> Optional[str]:
    """Try JSON-LD / Next.js data for an image URL."""
    # JSON-LD
    for raw in doc.xpath("//script[@type='application/ld+json']/text()"):
        data = _json_loads_best_effort(raw)
        if data is None:
            continue
        found = _find_first_image_in_obj(data)
        if found:
            u = urljoin(base_url, found)
            if u and not _is_bad_image_url(u):
                return u

    # Next.js
    raw_next = doc.xpath("//script[@id='__NEXT_DATA__']/text()")
    if raw_next:
        data = _json_loads_best_effort(raw_next[0])
        found = _find_first_image_in_obj(data)
        if found:
            u = urljoin(base_url, found)
            if u and not _is_bad_image_url(u):
                return u

    return None


def _extract_price_from_text(t: str):
    # pega um pedaço pequeno ao redor do "R$" pra reduzir falso positivo
    if not t or "R$" not in t:
        return None
    i = t.find("R$")
    snippet = t[i:i+40]
    return parse_brl_price(snippet)


def _pick_thumb_from_element(el, base_url: str) -> Optional[str]:
    candidates: list[str] = []

    # <img src=...> e lazy attrs
    for xp in (".//img/@src", ".//img/@data-src", ".//img/@data-original", ".//img/@data-lazy-src"):
        candidates.extend(el.xpath(xp))

    # srcset
    for xp in (".//img/@srcset", ".//img/@data-srcset", ".//img/@data-lazy-srcset", ".//source/@srcset"):
        for ss in el.xpath(xp):
            parts = [p.strip() for p in (ss or "").split(",") if p.strip()]
            if not parts:
                continue
            # pega o último (tende a ser maior)
            last = parts[-1].split(" ")[0].strip()
            if last:
                candidates.append(last)

    # style="background-image:url(...)"
    for st in el.xpath(".//*[@style]/@style"):
        if "background-image" in (st or ""):
            m = re.search(r"url\(['\"]?([^'\")]+)", st)
            if m:
                candidates.append(m.group(1))

    # normalize + filter
    out: list[str] = []
    for c in candidates:
        if not c:
            continue
        if c.startswith("data:"):
            continue
        u = urljoin(base_url, c)
        low = u.lower()
        if any(x in low for x in ("logo", "sprite", "icon")):
            continue
        # aceita imagens mesmo sem extensão (mas prefere com)
        out.append(u)

    # prefer extension
    for u in out:
        if re.search(r"\.(jpg|jpeg|png|webp)($|\?)", u, flags=re.I):
            return u
    return out[0] if out else None


def _detail_enrich(url: str, ctx: ScrapeContext) -> dict:
    """Extrai title + thumb direto da página de detalhe (fallback)."""
    if bool(getattr(ctx, "force_browser", False)):
        html_text = fetch_html_browser(url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded").html
    else:
        try:
            html_text = fetch_html(url, ctx=ctx, proxy=ctx.proxy_server, timeout=25)
        except FetchBlocked:
            if not settings.enable_playwright:
                raise
            html_text = fetch_html_browser(url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded").html
        except Exception:
            if not settings.enable_playwright:
                raise
            html_text = fetch_html_browser(url, ctx=ctx, timeout_ms=60000, wait_until="domcontentloaded").html

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(url)

    h1 = _clean_text(" ".join(doc.xpath("//h1[1]//text()")))
    h2 = _clean_text(" ".join(doc.xpath("//h2[1]//text()")))
    title = _clean_text(" ".join([x for x in (h1, h2) if x])) or None

    # thumbnail: head/meta > structured data > DOM images > last-resort regex
    thumb = _extract_head_image(doc, url) or _extract_structured_image(doc, url)

    if not thumb:
        candidates = []
        # standard & lazy
        candidates.extend(doc.xpath("//img/@src | //img/@data-src | //img/@data-lazy-src | //img/@data-original"))
        # srcset
        candidates.extend(doc.xpath("//img/@srcset | //img/@data-srcset | //img/@data-lazy-srcset | //source/@srcset"))
        # background-image styles
        for st in doc.xpath("//*[@style]/@style"):
            if "background-image" in (st or ""):
                m2 = re.search(r"url\(['\"]?([^'\")]+)", st)
                if m2:
                    candidates.append(m2.group(1))

        for c in candidates:
            if not c or c.startswith("data:"):
                continue
            u = urljoin(url, c)
            if _is_bad_image_url(u):
                continue
            if re.search(r"\.(jpg|jpeg|png|webp)($|\?)", u, flags=re.I):
                thumb = u
                break

        if not thumb:
            # accept image URLs even without file extension (some CDNs)
            for c in candidates:
                if not c or c.startswith("data:"):
                    continue
                u = urljoin(url, c)
                if _is_bad_image_url(u):
                    continue
                thumb = u
                break

    if not thumb:
        imgs = re.findall(r"https?://[^\s\"']+\.(?:jpg|jpeg|png|webp)(?:\?[^\"']*)?", html_text, flags=re.I)
        for u in imgs:
            if _is_bad_image_url(u):
                continue
            thumb = u
            break

    return {"title": title, "thumbnail_url": thumb}





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

        card = _find_card_container(a)
        card_text = (card.text_content() or "")

        raw_title = a.get('aria-label') or a.get('title') or card_text or a.text_content()
        text = _strip_title_noise(raw_title)
        if not text or text.lower() in ("enviar mensagem", "ver detalhes", "detalhes"):
            text = ""

        price = _extract_price_from_text(card_text)

        # thumbnail (best-effort)
        thumb = _pick_thumb_from_element(card, search_url)

        cur = by_url.get(url) or {
            "source": "mobiauto",
            "external_id": external_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        # Title heuristic
        if not cur.get("title") and text and len(text) >= 6 and len(text) <= 140:
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


    # Enrich a few items missing title/thumbnail (cheap backfill)
    needs = [x for x in by_url.values() if not x.get("thumbnail_url") or not x.get("title")]
    for cur in needs[:8]:
        try:
            det = _detail_enrich(cur["url"], ctx)
            if not cur.get("title") and det.get("title"):
                cur["title"] = det["title"]
            if not cur.get("thumbnail_url") and det.get("thumbnail_url"):
                cur["thumbnail_url"] = det["thumbnail_url"]
        except Exception:
            continue

    return list(by_url.values())
