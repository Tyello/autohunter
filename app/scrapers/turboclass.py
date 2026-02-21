from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Optional
from urllib.parse import urlparse, parse_qs
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html
from app.scrapers.fetching import fetch_html_with_browser_fallback
from app.scrapers.parsing import parse_brl_price
from app.scrapers.utils import normalize_asset_url, pick_from_srcset
from app.scrapers.contract import finalize_listings
from app.sources.types import ScrapeContext


_BASE = "https://turboclass.com.br"


_RE_DETAIL = re.compile(r"(?:^|/)anuncio/(?:detalhe|vendido)/([^/?#]+)", re.I)
_RE_TC_ID = re.compile(r"\b(tc-[a-z0-9]+)\b", re.I)
_RE_YEARS = re.compile(r"\bANO\s*/\s*MODELO\s*(19\d{2}|20\d{2})\s*/\s*(19\d{2}|20\d{2})\b", re.I)
_RE_LOCATION = re.compile(r"\bLOCALIDADE\s+(.+?)\s+detalhes\b", re.I)


# Cache leve em memória para evitar refetch da mesma página quando há várias wishlists.
# (Importante no Raspberry Pi: reduz CPU/RAM e tráfego, e evita padrões repetidos.)
_LIST_PAGE_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL_S = 120


def _extract_query_from_url(search_url: str) -> str:
    try:
        q = (parse_qs(urlparse(search_url).query).get("q") or [""])[0]
        return (q or "").strip()
    except Exception:
        return ""


def _cache_get(key: str) -> Optional[str]:
    now = time.time()
    hit = _LIST_PAGE_CACHE.get(key)
    if not hit:
        return None
    ts, html = hit
    if (now - ts) > _CACHE_TTL_S:
        try:
            del _LIST_PAGE_CACHE[key]
        except Exception:
            pass
        return None
    return html


def _cache_set(key: str, html: str) -> None:
    _LIST_PAGE_CACHE[key] = (time.time(), html)


def _fetch_list_html(
    url: str,
    *,
    ctx: Optional[ScrapeContext],
    force_browser: bool = False,
) -> str:
    """Fetch helper com cache e opção de forçar browser.

    Motivo:
    - TurboClass tem cenários onde o resultado da busca (q=...) parece depender de JS.
      Em HTTP puro, a página vem "vazia" (200 OK, sem cards). Nesses casos, o
      Playwright é a rota certa — mas só quando necessário.
    """

    proxy_key = getattr(ctx, "proxy_server", None) if ctx is not None else None
    key = f"turboclass::{proxy_key}::{1 if force_browser else 0}::{url}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if ctx is None:
        html = fetch_html(url)
        _cache_set(key, html)
        return html

    prev_force = getattr(ctx, "force_browser", False)
    try:
        if force_browser:
            try:
                setattr(ctx, "force_browser", True)
            except Exception:
                pass

        html = fetch_html_with_browser_fallback(
            url,
            ctx=ctx,
            referer=_BASE + "/",
            # Quando forçamos browser, esperamos "networkidle" para o JS preencher a lista.
            wait_until="networkidle" if force_browser else "domcontentloaded",
        )
        _cache_set(key, html)
        return html
    finally:
        if force_browser:
            try:
                setattr(ctx, "force_browser", prev_force)
            except Exception:
                pass


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
MAX_FALLBACK_PAGES = 25


def _parse_listings_from_html(html: str, *, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    out: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if not _RE_DETAIL.search(href):
            continue

        text = (a.get_text(" ", strip=True) or "").strip()
        if not text:
            continue

        # Guardrail: a listagem de anúncios sempre traz VALOR/ANO/MODELO/LOCALIDADE no texto.
        if "R$" not in text and "VALOR" not in text.upper():
            continue

        url = href
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
                "year": year,
            }
        )

        if len(out) >= int(limit or 0):
            break

    return out


def _normalize_for_match(s: str) -> str:
    # Normalização leve (sem depender de libs extras)
    s = (s or "").lower()
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fallback_scan_recent(
    query: str,
    *,
    limit: int,
    ctx: Optional[ScrapeContext],
) -> list[dict]:
    """Fallback HTTP-only: varre páginas recentes e filtra por tokens.

    Usado quando a busca `q=...` volta vazia (SPA/JS). Evita Playwright e ainda
    dá um recall razoável com custo controlado.
    """

    tokens = [t for t in _normalize_for_match(query).split() if len(t) >= 2]
    if not tokens:
        return []

    matched: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for pg in range(1, MAX_FALLBACK_PAGES + 1):
        # `q` vazio para manter SSR; ordenação por recentes.
        url = f"{_BASE}/anuncio-lista.php?o=rec&pg={pg}&q="
        html = _fetch_list_html(url, ctx=ctx, force_browser=False)
        items = _parse_listings_from_html(html, limit=300)

        for it in items:
            title = _normalize_for_match(str(it.get("title") or ""))
            if not title:
                continue
            if not all(tok in title for tok in tokens):
                continue

            key = ((it.get("source") or ""), (it.get("external_id") or ""))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            matched.append(it)

            if len(matched) >= int(limit or 0):
                return matched

    return matched


def scrape_turboclass(
    search_url: str,
    limit: int = 50,
    ctx: Optional[ScrapeContext] = None,
) -> list[dict]:
    """Scrape TurboClass (SSR) list page.

    Mantém scraping leve (1 página) e, opcionalmente, enriquece thumbs via OG:image
    em até `DETAIL_THUMB_MAX` anúncios (budget) para reduzir casos sem foto no Telegram.
    """

    q = _extract_query_from_url(search_url)

    html = _fetch_list_html(search_url, ctx=ctx, force_browser=False)
    out = _parse_listings_from_html(html, limit=limit)

    # TurboClass: quando `q` está presente, pode ser que a lista seja preenchida por JS.
    # Se veio vazia, tentamos UMA vez em browser (Playwright), sem depender de "blocked".
    if not out and q and ctx is not None:
        try:
            html2 = _fetch_list_html(search_url, ctx=ctx, force_browser=True)
            out = _parse_listings_from_html(html2, limit=limit)
        except Exception:
            out = out or []

    # Último fallback: varrer páginas recentes SSR e filtrar por tokens.
    if not out and q:
        try:
            out = _fallback_scan_recent(q, limit=limit, ctx=ctx)
        except Exception:
            out = out or []

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
