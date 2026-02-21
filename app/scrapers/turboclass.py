from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html
from app.scrapers.fetching import fetch_html_with_browser_fallback
from app.scrapers.parsing import parse_brl_price
from app.scrapers.utils import normalize_asset_url, pick_from_srcset
from app.scrapers.contract import finalize_listings
from app.sources.types import ScrapeContext


_BASE = "https://turboclass.com.br"


# O TurboClass usa hrefs relativos SEM barra inicial (ex.: "anuncio/detalhe/..."),
# então aceitamos com ou sem "/" para não perder anúncios.
_RE_DETAIL = re.compile(r"(?:^|/)(?:anuncio/detalhe)/([^/?#]+)", re.I)
_RE_TC_ID = re.compile(r"\b(tc-[a-z0-9]+)\b", re.I)
_RE_YEARS = re.compile(r"\bANO\s*/\s*MODELO\s*(19\d{2}|20\d{2})\s*/\s*(19\d{2}|20\d{2})\b", re.I)
_RE_LOCATION = re.compile(r"\bLOCALIDADE\s+(.+?)\s+detalhes\b", re.I)


def _extract_external_id(url: str) -> str:
    """TurboClass usa um slug estável: tc-xxxxxx-..."""
    u = (url or "").strip()
    if not u:
        return ""

    m = _RE_DETAIL.search(u)
    slug = m.group(1) if m else ""
    if slug:
        m2 = _RE_TC_ID.search(slug)
        return (m2.group(1).lower() if m2 else slug)

    # fallback: o contract.finalize_listings tem fallback por URL, mas preferimos estabilidade
    return u


def _extract_thumb_from_anchor(a) -> Optional[str]:
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
            return normalize_asset_url(cand, _BASE)

    src = a.select_one("source[srcset]")
    if src:
        cand = pick_from_srcset(src.get("srcset") or "", prefer_last=True)
        if cand:
            return normalize_asset_url(cand, _BASE)

    # background-image inline
    el = a.select_one("[style*='background-image']")
    if el:
        style = el.get("style") or ""
        m = re.search(r"background-image\s*:\s*url\((['\"]?)([^'\")]+)\1\)", style, re.I)
        if m:
            return normalize_asset_url(m.group(2), _BASE)

    return None


def _parse_year(text: str) -> Optional[int]:
    if not text:
        return None

    m = _RE_YEARS.search(text)
    if m:
        try:
            y = int(m.group(1))
            return y if 1960 <= y <= 2035 else None
        except Exception:
            return None

    m2 = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if m2:
        try:
            y = int(m2.group(1))
            return y if 1960 <= y <= 2035 else None
        except Exception:
            return None
    return None


def _parse_location(text: str) -> Optional[str]:
    if not text:
        return None

    m = _RE_LOCATION.search(text)
    if m:
        loc = " ".join((m.group(1) or "").replace("\xa0", " ").split())
        return loc.strip() or None

    # fallback: último padrão Cidade/UF no texto
    matches = list(re.finditer(r"([A-Za-zÀ-ÿ0-9\s\-\.]+\/[A-Z]{2})\b", text))
    if matches:
        loc = " ".join(matches[-1].group(1).split())
        return loc.strip() or None

    return None


def _parse_title(text: str) -> Optional[str]:
    if not text:
        return None

    # Ex.: "Volkswagen Gol Turbo Motorização VALOR R$ ..."
    head = text
    if "VALOR" in head.upper():
        head = re.split(r"\bVALOR\b", head, maxsplit=1, flags=re.I)[0]

    # TurboClass às vezes usa unicode com combining marks (ex.: "Motorização"),
    # então cortamos pelo prefixo "Motoriz" ao invés de tentar casar o token inteiro.
    head = re.split(r"\bMotoriz", head, maxsplit=1, flags=re.I)[0].strip()
    head = " ".join(head.replace("\xa0", " ").split())
    return head or None


DETAIL_THUMB_MAX = 3


def scrape_turboclass(
    search_url: str,
    limit: int = 50,
    ctx: Optional[ScrapeContext] = None,
) -> list[dict]:
    """Scrape TurboClass (SSR) list page.

    Mantém scraping leve (1 página) e, opcionalmente, enriquece thumbs via OG:image
    em até `DETAIL_THUMB_MAX` anúncios (budget) para reduzir casos sem foto no Telegram.
    """

    if ctx is not None:
        html = fetch_html_with_browser_fallback(
            search_url,
            ctx=ctx,
            referer=_BASE + "/",
            wait_until="domcontentloaded",
        )
    else:
        html = fetch_html(search_url)

    soup = BeautifulSoup(html, "html.parser")

    out: list[dict] = []
    for a in soup.select('a[href*="anuncio/detalhe/"]'):
        href = a.get("href")
        if not href:
            continue

        text = (a.get_text(" ", strip=True) or "").strip()
        if not text:
            continue

        # Guardrail: a listagem de anúncios sempre traz VALOR/ANO/MODELO/LOCALIDADE no texto.
        if "R$" not in text and "VALOR" not in text.upper():
            continue

        # href pode vir como "anuncio/detalhe/..." (sem /) ou "/anuncio/detalhe/...".
        url = href.strip()
        if not url.startswith("http"):
            url = urljoin(_BASE + "/", url)

        external_id = _extract_external_id(url)
        if not external_id:
            continue

        price: Optional[Decimal] = parse_brl_price(text)
        title = _parse_title(text)
        year = _parse_year(text)
        location = _parse_location(text)
        thumb = _extract_thumb_from_anchor(a)

        out.append(
            {
                "source": "turboclass",
                "external_id": str(external_id),
                "title": title,
                "url": url,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": location,
                # persistência indireta (decorated title) no repo
                "year": year,
            }
        )

        if len(out) >= int(limit or 0):
            break

    # dedupe interno (antes do enrichment)
    seen: set[tuple[str, str]] = set()
    uniq: list[dict] = []
    for it in out:
        key = ((it.get("source") or ""), (it.get("external_id") or ""))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # Enriquecimento barato: OG:image na página do anúncio (budget fixo)
    missing = [it for it in uniq if not it.get("thumbnail_url") and it.get("url")]
    if missing:
        budget = DETAIL_THUMB_MAX
        for it in missing:
            if budget <= 0:
                break
            try:
                html_d = fetch_html(
                    it["url"],
                    ctx=ctx,
                    referer=_BASE + "/",
                    timeout=25,
                    min_delay_ms=120,
                    max_delay_ms=420,
                )
                s2 = BeautifulSoup(html_d, "html.parser")
                meta = s2.select_one('meta[property="og:image"]') or s2.select_one('meta[name="twitter:image"]')
                if meta and meta.get("content"):
                    it["thumbnail_url"] = normalize_asset_url(meta.get("content"), _BASE)
                    budget -= 1
                    continue
                img = s2.select_one("img[src]")
                if img and img.get("src"):
                    it["thumbnail_url"] = normalize_asset_url(img.get("src"), _BASE)
                    budget -= 1
            except Exception:
                continue

    return finalize_listings("turboclass", uniq)
