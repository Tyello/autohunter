from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

from app.core.text_norm import normalize
from app.scrapers.base import fetch_html
from app.scrapers.fetching import fetch_html_with_browser_fallback
from app.scrapers.parsing import parse_brl_price
from app.scrapers.utils import normalize_asset_url, pick_from_srcset
from app.sources.types import ScrapeContext


@dataclass
class ChavesNaMaoItem:
    external_id: str
    title: str
    url: str
    thumbnail_url: Optional[str]
    price: Optional[Decimal]
    currency: str = "BRL"
    location: Optional[str] = None


# ---- URL resolver (SSR pages) ----

def build_chavesnamao_search_url(query: str, page: int = 1) -> str:
    """Resolve a query into the most stable Chaves na Mão listing URL.

    The site has SSR model pages that are *much* more consistent than `?q=`.

    Examples:
      - https://www.chavesnamao.com.br/carros/brasil/honda-civic/
      - https://www.chavesnamao.com.br/carros/brasil/honda-civic-2.0-si-sedan-16v-4p/

    For the MVP we keep the resolver intentionally conservative:
    - Civic special cases (SI / Type R) -> specific trim pages
    - Otherwise, fallback to the generic `carros-usados/brasil/?q=...` search.

    NOTE: If you add new mappings, prefer ones you have validated exist.
    """

    raw = normalize(query)
    tok = raw.split()

    slug: Optional[str] = None

    # Honda Civic family (special cases reduce false positives a lot)
    if "civic" in tok:
        is_type_r = ("type" in tok and "r" in tok) or "typer" in tok
        is_si = "si" in tok or "sir" in tok
        is_coupe = "coupe" in tok or "2p" in tok

        if is_type_r:
            slug = "honda-civic-2.0-type-r-turbo-16v-4p"
        elif is_si and is_coupe:
            # Civic Si Coupé (ex.: 2014/2015 2.4 aspirado)
            slug = "honda-civic-2.4-si-coupe-16v-2p"
        elif is_si:
            # Civic Si Sedan (ex.: 2007/2008 2.0)
            slug = "honda-civic-2.0-si-sedan-16v-4p"
        else:
            slug = "honda-civic"

    # If we have a validated SSR slug, use it.
    if slug:
        url = f"https://www.chavesnamao.com.br/carros/brasil/{slug}/"
    else:
        # Fallback: generic search. Can be noisier.
        q = quote_plus(query.strip())
        url = f"https://www.chavesnamao.com.br/carros-usados/brasil/?q={q}"

    if page and page > 1:
        sep = "&" if "?" in url else "?"
        url += f"{sep}pagina={page}"
    return url


_CHAVES_BASE = "https://www.chavesnamao.com.br"

def _extract_thumb_from_anchor(a) -> Optional[str]:
    # 1) <img> dentro do <a>
    img = a.select_one("img")
    if img:
        cand = (
            img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
            or img.get("src")
        )
        if not cand:
            cand = pick_from_srcset(img.get("data-srcset") or img.get("srcset") or "", prefer_last=True)
        if cand:
            return normalize_asset_url(cand, _CHAVES_BASE)

    # 2) <source srcset> dentro de <picture>
    src = a.select_one("source[srcset]")
    if src:
        cand = pick_from_srcset(src.get("srcset") or "", prefer_last=True)
        if cand:
            return normalize_asset_url(cand, _CHAVES_BASE)

    # 3) background-image inline (card css)
    el = a.select_one("[style*='background-image']")
    if el:
        style = el.get("style") or ""
        m = re.search(r"background-image\s*:\s*url\((['\"]?)([^'\")]+)\1\)", style, re.I)
        if m:
            return normalize_asset_url(m.group(2), _CHAVES_BASE)

    return None

def _extract_location_from_url(url: str) -> Optional[str]:
    # Ex.: https://www.chavesnamao.com.br/carro/pr-curitiba/...
    try:
        p = urlparse(url)
        segs = [s for s in (p.path or "").split("/") if s]
    except Exception:
        return None

    if "carro" in segs:
        i = segs.index("carro")
        if i + 1 < len(segs):
            loc = segs[i + 1]  # pr-curitiba
            m = re.match(r"^([a-z]{2})-(.+)$", loc)
            if m:
                uf = m.group(1).upper()
                city_slug = m.group(2)
                city = " ".join([w for w in city_slug.split("-") if w]).title()
                return f"{city}-{uf}" if city else uf
    return None

def _extract_location_from_anchor_text(text: str) -> Optional[str]:
    # exemplos visíveis no próprio texto do link: "Curitiba , PR" / "São Paulo , SP"
    # às vezes vem poluído: "223.000 km Gasolina Mecânico Curitiba , PR"
    if not text:
        return None
    matches = list(re.finditer(r"([A-Za-zÀ-ÿ\s]+)\s*,\s*([A-Z]{2})\b", text))
    if not matches:
        return None
    m = matches[-1]  # pega a última ocorrência (mais perto do fim do texto)
    city_raw = " ".join((m.group(1) or "").split())
    uf = m.group(2)

    # remove lixo comum antes da cidade
    noise = {"km", "gasolina", "mecânico", "mecanico"}
    toks = [t for t in city_raw.split() if t.strip() and t.lower() not in noise]
    city = " ".join(toks[-4:])  # cidade tende a estar no fim
    return f"{city}-{uf}" if city else uf



DETAIL_THUMB_MAX = 3


def scrape_chavesnamao(
    search_url: str,
    limit: int = 50,
    ctx: Optional[ScrapeContext] = None,
) -> list[dict]:
    if ctx is not None:
        html = fetch_html_with_browser_fallback(
            search_url,
            ctx=ctx,
            referer=_CHAVES_BASE + "/",
            wait_until="domcontentloaded",
        )
    else:
        html = fetch_html(search_url)
    soup = BeautifulSoup(html, "html.parser")

    out: list[dict] = []

    # A página lista os anúncios como <a> com o título + preço no texto.
    # Regra de ouro pra não puxar "similares"/conteúdo editorial:
    # anúncios têm URL com /carro/.../id-<digits>/
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue

        if "/id-" not in href:
            continue

        text = (a.get_text(" ", strip=True) or "").strip()
        if "R$" not in text:
            continue

        url = href
        if url.startswith("/"):
            url = "https://www.chavesnamao.com.br" + url

        # external_id: tenta extrair último segmento numérico; senão usa a URL
        m = re.search(r"(\d{6,})", url)
        external_id = m.group(1) if m else url


        price = parse_brl_price(text)

        # location: primeiro tenta pela URL (mais confiável); fallback pro texto
        location = _extract_location_from_url(url) or _extract_location_from_anchor_text(text)

        # thumb: tenta extrair do card (img/srcset/background)
        thumb = _extract_thumb_from_anchor(a)

        # título: remove o preço e também tira o "Cidade , UF" do final
        title_raw = (text.split("R$")[0].strip() or "").strip()
        title_raw = re.sub(r"\s+[A-Za-zÀ-ÿ\s]+\s*,\s*[A-Z]{2}\b\s*$", "", title_raw).strip()
        title = title_raw or None

        out.append(
            {
                "source": "chavesnamao",
                "external_id": str(external_id),
                "title": title,
                "url": url,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": location,
            }
        )

        if len(out) >= limit:
            break

    # dedupe interno
    seen = set()
    uniq: list[dict] = []
    for it in out:
        key = (it.get("source"), it.get("external_id"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)


    # Enriquecimento barato: se alguns cards vierem sem thumb, tenta OG:image na página do anúncio.
    missing = [it for it in uniq if not it.get("thumbnail_url") and it.get("url")]
    if missing:
        budget = DETAIL_THUMB_MAX
        for it in missing:
            if budget <= 0:
                break
            try:
                html_d = fetch_html(it["url"])
                s2 = BeautifulSoup(html_d, "html.parser")
                meta = s2.select_one('meta[property="og:image"]') or s2.select_one('meta[name="twitter:image"]')
                if meta and meta.get("content"):
                    it["thumbnail_url"] = normalize_asset_url(meta.get("content"), _CHAVES_BASE)
                    budget -= 1
                    continue
                img = s2.select_one("img[src]")
                if img and img.get("src"):
                    it["thumbnail_url"] = normalize_asset_url(img.get("src"), _CHAVES_BASE)
                    budget -= 1
            except Exception:
                continue

    return uniq
