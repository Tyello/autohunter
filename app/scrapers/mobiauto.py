from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from lxml import html as lxml_html

from app.scrapers.fetching import fetch_html_with_browser_fallback
from app.scrapers.parsing import parse_brl_price
from app.scrapers.contract import finalize_listings
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
    r"\b(comparar|simular|ver\s+parcelas|financiamento|detalhes|enviar\s+mensagem)\b",
    re.IGNORECASE,
)


# Ex.: "Guarulhos-SP | a 0 km" (distância até a loja, NÃO a km do carro)
_LOC_DISTANCE_RE = re.compile(
    r"(?P<loc>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]+\s*-\s*[A-Z]{2})\s*(?:\|\s*a\s*\d[\d\.,]*\s*km)?\b",
    re.UNICODE,
)


def _extract_location(t: str) -> Optional[str]:
    t = _deconcat(t)
    m = _LOC_DISTANCE_RE.search(t)
    if not m:
        return None
    loc = _clean_text(m.group("loc"))
    # normaliza "Cidade - SP" -> "Cidade-SP"
    loc = re.sub(r"\s*-\s*", "-", loc)
    return loc or None


def _strip_title_noise(t: str) -> str:
    """Normaliza o texto do card do Mobiauto, removendo UI/noise, mas preservando ano e KM do carro."""

    t = _deconcat(t)

    # Remove/zera pedaços de UI
    t = _NOISE_RE.sub(" ", t)

    # Remove preço inline caso venha colado no texto do card
    t = re.sub(r"R\$\s*[0-9\.]+(?:,[0-9]{1,2})?", " ", t)

    # Remove localização + distância no final (deixa loc em campo separado)
    t = _LOC_DISTANCE_RE.sub(" ", t)

    # Remove apenas o token "| a X km" se sobrar
    t = re.sub(r"\|\s*a\s*\d[\d\.,]*\s*km\b", " ", t, flags=re.IGNORECASE)

    # Alguns cards colam "0 km" (distância) em situações; evita remover odômetro real (ex.: "0 km" sem barra)
    t = re.sub(r"\b[aà]\s*0\s*km\b", " ", t, flags=re.IGNORECASE)

    # Compacta
    t = _clean_text(t)

    # Heurística: se ainda sobrou "Comparar" colado sem espaço
    t = re.sub(r"\bcomparar\b", " ", t, flags=re.IGNORECASE)

    return _clean_text(t)


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
    html_text = fetch_html_with_browser_fallback(
        url,
        ctx=ctx,
        timeout=25,
        proxy=ctx.proxy_server,
        wait_until="domcontentloaded",
        timeout_ms=60000,
    )

    doc = lxml_html.fromstring(html_text)
    doc.make_links_absolute(url)

    h1 = _clean_text(" ".join(doc.xpath("//h1[1]//text()")))
    h2 = _clean_text(" ".join(doc.xpath("//h2[1]//text()")))
    title = _clean_text(" ".join([x for x in (h1, h2) if x])) or None

    # tenta pegar imagem/thumbnail. Observação: o CDN do Mobiauto frequentemente entrega URL sem extensão.
    candidates = []

    # meta tags (OG/Twitter)
    candidates.extend(doc.xpath("//meta[@property='og:image']/@content"))
    candidates.extend(doc.xpath("//meta[@name='twitter:image']/@content"))

    # img tags + lazy variants
    candidates.extend(doc.xpath("//img/@src | //img/@data-src | //img/@data-lazy-src"))

    # srcset (img/picture)
    candidates.extend(doc.xpath("//img/@srcset | //source/@srcset"))

    def _expand_srcset(v: str) -> list[str]:
        v = (v or '').strip()
        if not v:
            return []
        if ',' not in v and ' ' not in v:
            return [v]
        out = []
        for part in v.split(','):
            part = part.strip()
            if not part:
                continue
            out.append(part.split(' ')[0].strip())
        return out

    thumb = None
    for raw in candidates:
        for c in _expand_srcset(raw):
            if not c:
                continue
            u = urljoin(url, c)
            low = u.lower()
            if any(x in low for x in ('logo', 'sprite', 'icon')):
                continue

            # aceita URL com extensão OU CDN do Mobiauto (sem extensão)
            if re.search(r"\.(jpg|jpeg|png|webp)(?:$|\?)", u, flags=re.I) or "mobiauto.com.br/images/" in low or "image" in low and "mobiauto.com.br" in low:
                thumb = u
                break
        if thumb:
            break

    if not thumb:
        # regex no HTML todo (último recurso) - considera extensão e URLs do CDN
        imgs = re.findall(r"https?://[^\s\"']+\.(?:jpg|jpeg|png|webp)(?:\?[^\"']*)?", html_text, flags=re.I)
        for u in imgs:
            low = u.lower()
            if any(x in low for x in ('logo', 'sprite', 'icon')):
                continue
            thumb = u
            break

        if not thumb:
            cdn = re.findall(r"https?://image\d+\.mobiauto\.com\.br/[^\s\"']+", html_text, flags=re.I)
            for u in cdn:
                low = u.lower()
                if any(x in low for x in ('logo', 'sprite', 'icon')):
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
    html_text = fetch_html_with_browser_fallback(
        search_url,
        ctx=ctx,
        timeout=25,
        proxy=ctx.proxy_server,
        wait_until="domcontentloaded",
        timeout_ms=60000,
    )

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

        raw_card = a.get('aria-label') or a.get('title') or a.text_content()

        # sobe um pouco para pegar o container do card (normalmente carrega preço/imagem)
        card = a
        for _ in range(4):
            p = card.getparent()
            if p is None:
                break
            card = p
            try:
                if card.xpath('.//img') or 'R$' in (card.text_content() or ''):
                    break
            except Exception:
                break

        loc = _extract_location(raw_card)
        text = _strip_title_noise(raw_card)
        if not text or text.lower() in ("enviar mensagem", "ver detalhes", "detalhes"):
            text = ""

        card_text = (card.text_content() or "")
        price = _extract_price_from_text(card_text) or _extract_price_from_text(raw_card)

        # thumbnail (best-effort): tenta no card e depois no <a>
        thumb = _pick_thumb_from_element(card, search_url) or _pick_thumb_from_element(a, search_url)

        cur = by_url.get(url) or {
            "source": "mobiauto",
            "external_id": external_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        }

        if cur.get("location") is None and loc:
            cur["location"] = loc

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

    return finalize_listings("mobiauto", list(by_url.values()))
