from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin, urlparse

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_json
from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


WEBMOTORS_BASE = "https://www.webmotors.com.br"
WEBMOTORS_SEARCH_API = "https://www.webmotors.com.br/api/search/car"


def _to_decimal_brl(v: Any) -> Optional[Decimal]:
    """Converte preço (int/float/str) para Decimal BRL, com tolerância."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(int(v)))
        except Exception:
            return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, str):
        p = parse_brl_price(v)
        if p is None:
            return None
        try:
            return Decimal(str(int(p)))
        except Exception:
            return None
    return None


def _safe_get(d: Any, *path: str) -> Any:
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _normalize_location(city: Optional[str], state: Optional[str]) -> Optional[str]:
    c = (city or "").strip()
    s = (state or "").strip()
    if c and s:
        return f"{c}-{s}"
    if s:
        return s
    return None


def _encode_url_param(search_url: str) -> str:
    """Webmotors /api/search/car espera o parâmetro `url` com a URL de busca
    totalmente percent-encoded (incluindo / ? & =). O padrão usado em diversos
    exemplos públicos é:
      url2 = "https://www.webmotors.com.br/" + quote(path_and_query, safe='')
    """

    u = search_url.strip()
    if u.startswith(WEBMOTORS_BASE + "/"):
        path_qs = u[len(WEBMOTORS_BASE) + 1 :]
    else:
        parsed = urlparse(u)
        path_qs = (parsed.path.lstrip("/") or "")
        if parsed.query:
            path_qs = f"{path_qs}?{parsed.query}"
        if not path_qs:
            # fallback: passa o original (melhor que nada)
            path_qs = u

    return f"{WEBMOTORS_BASE}/" + quote(path_qs, safe="")


def _pick_thumb(item: dict) -> Optional[str]:
    # Formatos comuns (mudam bastante): Photos/Medias/Photo
    for key_path in [
        ("Medias", "Photos"),
        ("Media", "Photos"),
        ("Photos",),
    ]:
        cur = item
        for k in key_path:
            cur = cur.get(k) if isinstance(cur, dict) else None
        if isinstance(cur, list) and cur:
            first = cur[0]
            if isinstance(first, dict):
                url = first.get("Url") or first.get("url")
                if url:
                    return url
            if isinstance(first, str):
                return first

    url = item.get("Photo") or item.get("PhotoUrl") or item.get("photo")
    if isinstance(url, str) and url:
        return url
    return None


def _build_title(spec: dict) -> str:
    # Alguns retornam Title pronto
    t = spec.get("Title") or spec.get("title")
    if isinstance(t, str) and len(t.strip()) >= 3:
        return re.sub(r"\s+", " ", t).strip()

    def val(field: str) -> Optional[str]:
        v = spec.get(field)
        if isinstance(v, dict):
            vv = v.get("Value") or v.get("value")
            return str(vv).strip() if vv else None
        if isinstance(v, str):
            return v.strip()
        return None

    make = val("Make")
    model = val("Model")
    version = val("Version")
    year_model = spec.get("YearModel") or spec.get("Year Model") or spec.get("Yearmodel")
    ym = str(year_model).strip() if year_model else None

    parts = [p for p in [make, model, version, ym] if p]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _extract_results(payload: dict) -> List[dict]:
    # Padrão observado: payload['SearchResults']
    sr = payload.get("SearchResults") or payload.get("searchResults") or []
    return sr if isinstance(sr, list) else []


def scrape_webmotors(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Scraper HTTP-first para Webmotors.

    Estratégia:
    - Usa o endpoint interno XHR: GET /api/search/car
    - Mantém fallback opcional via Playwright (desligado por padrão)
    """

    url2 = _encode_url_param(search_url)
    api_url = f"{WEBMOTORS_SEARCH_API}?url={url2}&actualPage=1&displayPerPage=60"

    try:
        payload = fetch_json(
            api_url,
            referer=WEBMOTORS_BASE + "/",
            proxy=ctx.proxy_server,
            min_delay_ms=700,
            max_delay_ms=2200,
            headers={
                "X-Requested-With": "XMLHttpRequest",
            },
        )
    except FetchBlocked:
        # Fallback controlado
        if settings.enable_playwright:
            res = fetch_html_browser(search_url, ctx=ctx)
            # Sem parser pesado aqui: se chegou ao browser, apenas abandona (ops decide).
            # Retornamos vazio para não derrubar o job.
            return []
        raise
    except Exception:
        if settings.enable_playwright:
            return []
        raise

    results = _extract_results(payload if isinstance(payload, dict) else {})

    out: list[dict] = []
    seen: set[str] = set()

    for it in results:
        if not isinstance(it, dict):
            continue

        external_id = (
            str(it.get("UniqueId") or it.get("uniqueId") or it.get("Id") or it.get("id") or "")
            .strip()
        )
        if not external_id:
            # tentativa: número no link
            candidate = it.get("Link") or it.get("Url") or it.get("SeoUrl")
            if isinstance(candidate, str):
                m = re.search(r"(\d{6,})", candidate)
                if m:
                    external_id = m.group(1)
        if not external_id:
            continue
        if external_id in seen:
            continue
        seen.add(external_id)

        spec = it.get("Specification") or it.get("specification") or {}
        if not isinstance(spec, dict):
            spec = {}

        title = _build_title(spec)

        prices = it.get("Prices") or it.get("prices") or {}
        if not isinstance(prices, dict):
            prices = {}
        price = (
            _to_decimal_brl(prices.get("Price"))
            or _to_decimal_brl(prices.get("price"))
            or _to_decimal_brl(prices.get("FinancialPrice"))
            or _to_decimal_brl(prices.get("financialPrice"))
        )

        link = it.get("Link") or it.get("Url") or it.get("SeoUrl") or it.get("link") or it.get("url")
        url = None
        if isinstance(link, str) and link.strip():
            url = link.strip()
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("/"):
                url = urljoin(WEBMOTORS_BASE, url)
            if not url.startswith("http"):
                url = urljoin(WEBMOTORS_BASE + "/", url)
        else:
            url = search_url

        thumb = _pick_thumb(it)

        seller = it.get("Seller") or it.get("seller") or {}
        if not isinstance(seller, dict):
            seller = {}

        city = _safe_get(seller, "City", "Value") or seller.get("City") or seller.get("city")
        state = _safe_get(seller, "State", "Value") or seller.get("State") or seller.get("state")
        location = _normalize_location(str(city) if city else None, str(state) if state else None)

        out.append(
            {
                "source": "webmotors",
                "external_id": external_id,
                "title": title or None,
                "url": url,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": location,
            }
        )

        if len(out) >= 60:
            break

    return out
