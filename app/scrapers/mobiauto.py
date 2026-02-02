from __future__ import annotations

import json
import re
from typing import Any, Optional
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
    """Mobiauto costuma concatenar textos de múltiplos elementos sem espaços."""
    s = (s or "").replace("\xa0", " ")

    # separa letra<->numero e alguns separadores comuns
    s = re.sub(r"([A-Za-zÀ-ÿ])([0-9])", r"\1 \2", s)
    s = re.sub(r"([0-9])([A-Za-zÀ-ÿ])", r"\1 \2", s)
    s = re.sub(r"([)])([0-9])", r"\1 \2", s)
    s = re.sub(r"([0-9])([(])", r"\1 \2", s)

    # separa palavras coladas (ex: SPORTBACKPrestige, Aut)2019)
    s = re.sub(r"([a-zà-ÿ])([A-ZÁ-Ý])", r"\1 \2", s)
    s = re.sub(r"([A-ZÁ-Ý])([A-ZÁ-Ý][a-zà-ÿ])", r"\1 \2", s)

    # casos como "kmSão"
    s = re.sub(r"(km)([A-Za-zÀ-ÿ])", r"\1 \2", s, flags=re.IGNORECASE)

    return _clean_text(s)


_NOISE_RE = re.compile(
    r"\b(comparar|simular|ver\s+parcelas|financiamento|detalhes|enviar\s+mensagem)\b",
    re.IGNORECASE,
)


def _strip_title_noise(t: str) -> str:
    t = _deconcat(t)

    # corte na UI (mantém ano/ano, mas remove o resto do card)
    t = re.split(r"(?i)\bcomparar\b", t, maxsplit=1)[0]
    t = re.split(r"(?i)\bver\s+parcelas\b", t, maxsplit=1)[0]
    t = re.split(r"(?i)\benviar\s+mensagem\b", t, maxsplit=1)[0]

    # se aparecer preço, corta antes dele
    if "R$" in t:
        t = t.split("R$", 1)[0]

    # corta ao encontrar quilometragem / separador de distância
    t = re.split(r"(?i)\d{1,3}(?:\.\d{3})*\s*km", t, maxsplit=1)[0]
    t = t.split("|", 1)[0]

    # remove tokens que sobraram
    t = re.sub(r"(?i)\b[aà]\s*0\s*km\b", "", t)
    t = _NOISE_RE.sub("", t)

    return _clean_text(t)


def _extract_price_from_text(t: str):
    # pega um pedaço pequeno ao redor do "R$" pra reduzir falso positivo
    if not t or "R$" not in t:
        return None
    i = t.find("R$")
    snippet = t[i : i + 40]
    return parse_brl_price(snippet)


def _pick_thumb_from_element(el, base_url: str) -> Optional[str]:
    candidates: list[str] = []

    # <img src=...> e lazy attrs
    for xp in (".//img/@src", ".//img/@data-src", ".//img/@data-original", ".//img/@data-lazy-src"):
        candidates.extend(el.xpath(xp))

    # srcset
    for xp in (".//img/@srcset", ".//source/@srcset"):
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
        out.append(u)

    # prefer extension
    for u in out:
        if re.search(r"\.(jpg|jpeg|png|webp)($|\?)", u, flags=re.I):
            return u
    return out[0] if out else None


def _pick_thumb_near_element(el, base_url: str) -> Optional[str]:
    """Busca thumb no card (muitas vezes a imagem não está dentro do <a>)."""
    cur = el
    for _ in range(0, 7):  # sobe no máximo 6 níveis
        if cur is None:
            break
        thumb = _pick_thumb_from_element(cur, base_url)
        if thumb:
            return thumb
        cur = cur.getparent()
    return None


def _best_card_container(el):
    """Heurística barata pra pegar o container do card do anúncio.

    Objetivo: pegar um container pequeno (card) que contenha o link /detalhes/<id>
    e também a imagem e/ou preço, sem subir até o <body> e capturar imagens irrelevantes.
    """
    best = el
    cur = el
    for _ in range(0, 8):
        if cur is None:
            break

        # card típico tem poucos links de detalhe
        det_links = cur.xpath(".//a[contains(@href, '/detalhes/')]")
        has_det_link = len(det_links) >= 1
        has_price = "R$" in (cur.text_content() or "")
        has_img = bool(cur.xpath(".//img | .//picture | .//source"))

        if has_det_link and (has_price or has_img):
            best = cur
            # se já está bem contido, para aqui
            if len(det_links) <= 2:
                break

        cur = cur.getparent()

    return best if best is not None else el


def _looks_like_image_url(u: str) -> bool:
    if not u:
        return False
    ul = u.lower()
    if ul.startswith("http") and (
        "mobiauto.com.br/images/api/images" in ul
        or "image" in ul and "mobiauto.com.br" in ul
        or re.search(r"\.(jpg|jpeg|png|webp)($|\?)", ul)
    ):
        return True
    return False


def _deep_find_first_image(obj: Any) -> Optional[str]:
    """Procura recursivamente por uma URL de imagem em JSON (Next.js/JSON-LD)."""
    stack: list[Any] = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, str):
            if _looks_like_image_url(cur):
                return cur
            continue
        if isinstance(cur, dict):
            # dá preferência a chaves comuns
            for k in ("image", "images", "thumbnail", "thumbnailUrl", "thumbnail_url", "url"):
                v = cur.get(k)
                if isinstance(v, str) and _looks_like_image_url(v):
                    return v
                if isinstance(v, list) and v:
                    for it in v:
                        if isinstance(it, str) and _looks_like_image_url(it):
                            return it
            # explora tudo
            for v in cur.values():
                stack.append(v)
        elif isinstance(cur, list):
            for it in cur:
                stack.append(it)
    return None


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

    # Title: meta -> h1/h2
    og_title = _clean_text(" ".join(doc.xpath("//meta[@property='og:title']/@content | //meta[@name='twitter:title']/@content")))
    h1 = _clean_text(" ".join(doc.xpath("//h1[1]//text()")))
    h2 = _clean_text(" ".join(doc.xpath("//h2[1]//text()")))
    title = _strip_title_noise(og_title or h1 or h2) or None

    # Thumb: meta og:image / twitter:image / itemprop image
    meta_imgs = doc.xpath(
        "//meta[@property='og:image']/@content | //meta[@name='twitter:image']/@content | //meta[@itemprop='image']/@content"
    )
    thumb = None
    for c in meta_imgs:
        c = (c or "").strip()
        if _looks_like_image_url(c):
            thumb = urljoin(url, c)
            break

    # JSON-LD
    if not thumb:
        for s in doc.xpath("//script[@type='application/ld+json']/text()"):
            s = (s or "").strip()
            if not s:
                continue
            try:
                data = json.loads(s)
            except Exception:
                continue
            thumb = _deep_find_first_image(data)
            if thumb:
                break

    # __NEXT_DATA__ (Next.js)
    if not thumb:
        nd = doc.xpath("//script[@id='__NEXT_DATA__']/text()")
        if nd:
            try:
                data = json.loads(nd[0])
                thumb = _deep_find_first_image(data)
            except Exception:
                pass

    # HTML gallery (fallback)
    if not thumb:
        candidates = doc.xpath("//img/@src | //img/@data-src | //img/@data-lazy-src | //source/@srcset")
        for c in candidates:
            if not c:
                continue
            if " " in c and "," in c:
                # srcset
                parts = [p.strip() for p in c.split(",") if p.strip()]
                c = parts[-1].split(" ")[0].strip() if parts else c
            u = urljoin(url, c)
            if _looks_like_image_url(u):
                thumb = u
                break

    return {"title": title, "thumbnail_url": thumb}


def scrape_mobiauto(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Mobiauto scraper.

    Strategy:
    - HTTP-first (Mobiauto costuma responder SSR)
    - Fallback Playwright quando bloqueado/JS-only
    - Extrai URL + title + price + thumbnail
    """

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

    # Mobiauto listing cards: /detalhes/<id>
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

        card = _best_card_container(a)
        raw_text = (card.text_content() or "")
        # tenta ser mais semântico antes do texto bruto
        raw_hint = a.get("aria-label") or a.get("title") or raw_text

        title = _strip_title_noise(raw_hint)
        if title and title.lower() in ("enviar mensagem", "ver detalhes", "detalhes"):
            title = ""

        price = _extract_price_from_text(raw_text)
        thumb = _pick_thumb_from_element(card, search_url) or _pick_thumb_near_element(card, search_url)

        cur = by_url.get(url) or {
            "source": "mobiauto",
            "external_id": external_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        if not cur.get("title") and title and 6 <= len(title) <= 160:
            cur["title"] = title

        if cur.get("price") is None and price is not None:
            cur["price"] = price

        if cur.get("thumbnail_url") is None and thumb:
            cur["thumbnail_url"] = thumb

        by_url[url] = cur

    # Fallback: URLs brutas se DOM mudar muito
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

    # Enrich: só alguns itens sem title/thumb (leve pro RPi)
    needs = [x for x in by_url.values() if not x.get("thumbnail_url") or not x.get("title")]
    for cur in needs[:6]:
        try:
            det = _detail_enrich(cur["url"], ctx)
            if not cur.get("title") and det.get("title"):
                cur["title"] = det["title"]
            if not cur.get("thumbnail_url") and det.get("thumbnail_url"):
                cur["thumbnail_url"] = det["thumbnail_url"]
        except Exception:
            continue

    return list(by_url.values())
