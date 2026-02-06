from __future__ import annotations

import re
import threading
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin, urlparse

import requests

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_json
from app.scrapers.parsing import parse_brl_price
from app.scrapers.contract import finalize_listings
from app.services.browser_fetcher import fetch_html_browser, fetch_json_browser
from app.sources.types import ScrapeContext


WEBMOTORS_BASE = "https://www.webmotors.com.br"
WEBMOTORS_SEARCH_API = "https://www.webmotors.com.br/api/search/car"
WEBMOTORS_GENAI_API = "https://www.webmotors.com.br/api/gen-ai/search"

# Cache leve em memória (Pi-friendly) para reduzir chamadas extras.
_GENAI_CACHE: dict[str, tuple[float, str]] = {}
_GENAI_LOCK = threading.Lock()

_WARMUP_AT: dict[str, float] = {}
_WARMUP_LOCK = threading.Lock()


def _looks_like_bot_challenge(text: str) -> bool:
    h = (text or "").lower()
    return (
        "captcha" in h
        or "verify you are" in h
        or "cloudflare" in h
        or "incapsula" in h
        or "datadome" in h
        or "perimeterx" in h
        or "access denied" in h
    )


def _extract_prompt_from_search_url(search_url: str) -> Optional[str]:
    """Extrai o termo do parâmetro `search=` (quando build_url usa esse formato)."""
    try:
        p = urlparse(search_url)
        qs = p.query or ""
        m = re.search(r"(?:^|&)search=([^&]+)", qs)
        if not m:
            return None
        raw = m.group(1)
        # decode básico (sem depender de parse_qs para manter leve)
        try:
            from urllib.parse import unquote_plus

            s = unquote_plus(raw)
        except Exception:
            s = raw
        s = (s or "").strip()
        return s if s else None
    except Exception:
        return None


def _genai_resolve_stock_url(prompt: str, ctx: ScrapeContext) -> Optional[str]:
    """Best-effort: usa /api/gen-ai/search para converter prompt em URL canônica.

    Observação: esse endpoint pode ser protegido (cookies/PerimeterX). Então:
    - falhas não quebram o scraper;
    - cache (24h) evita bater de novo no mesmo prompt.
    """
    p = (prompt or "").strip()
    if not p:
        return None

    now = time.time()
    with _GENAI_LOCK:
        cached = _GENAI_CACHE.get(p.lower())
        if cached and (now - cached[0]) < 24 * 3600:
            return cached[1] or None

    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": WEBMOTORS_BASE,
        "Referer": WEBMOTORS_BASE + "/",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    }

    proxies = None
    if ctx.proxy_server:
        proxies = {"http": ctx.proxy_server, "https": ctx.proxy_server}

    try:
        resp = requests.post(
            WEBMOTORS_GENAI_API,
            json={"prompt": p},
            headers=headers,
            timeout=(6, 25),
            proxies=proxies,
        )

        if resp.status_code in (403, 429):
            raise FetchBlocked(resp.status_code, WEBMOTORS_GENAI_API, reason="http_status")
        if resp.status_code == 200 and _looks_like_bot_challenge(resp.text or ""):
            raise FetchBlocked(200, WEBMOTORS_GENAI_API, reason="bot_challenge")
        resp.raise_for_status()

        data = resp.json() if resp.text else {}
        url = None
        if isinstance(data, dict):
            r = data.get("response")
            if isinstance(r, dict):
                url = r.get("url")
        url = (url or "").strip() if isinstance(url, str) else None
        if url and url.startswith("/"):
            url = urljoin(WEBMOTORS_BASE, url)
        if url and url.startswith("http"):
            with _GENAI_LOCK:
                _GENAI_CACHE[p.lower()] = (now, url)
            return url
    except FetchBlocked:
        # Não propaga: é só um "upgrade" opcional de URL.
        return None
    except Exception:
        return None

    with _GENAI_LOCK:
        _GENAI_CACHE[p.lower()] = (now, "")
    return None


def _maybe_warmup(ctx: ScrapeContext) -> None:
    """Warmup leve para reduzir chance de challenge no primeiro hit.

    Faz no máximo 1 vez a cada 6h por proxy.
    """
    key = (ctx.proxy_server or "__no_proxy__") + "::webmotors"
    now = time.time()
    with _WARMUP_LOCK:
        last = _WARMUP_AT.get(key)
        if last and (now - last) < 6 * 3600:
            return
        _WARMUP_AT[key] = now

    try:
        fetch_html_browser(
            WEBMOTORS_BASE + "/",
            ctx=ctx,
            timeout_ms=18000,
            wait_until="domcontentloaded",
            min_delay_ms=60,
            max_delay_ms=180,
        )
    except Exception:
        # Warmup é best-effort.
        pass


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


def _capture_search_payload_browser(page_url: str, ctx: ScrapeContext) -> dict:
    """Abre a página de estoque no browser e captura o JSON do XHR /api/search/car."""
    _maybe_warmup(ctx)
    r = fetch_json_browser(
        page_url,
        ctx=ctx,
        timeout_ms=35000,
        wait_until="domcontentloaded",
        capture_mode="url_contains:/api/search/car",
        min_delay_ms=120,
        max_delay_ms=520,
    )
    if not isinstance(r.data, dict):
        raise RuntimeError("Browser JSON capture returned non-dict payload")
    return r.data


def scrape_webmotors(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Webmotors é tipicamente hostil a clients HTTP (BLOCKED com HTTP 200).

    Estratégia (Pi-friendly, mas robusta):
    - Browser-first (Playwright) capturando o JSON do XHR /api/search/car (sem parser pesado de HTML)
    - Fallback HTTP apenas se Playwright estiver indisponível/desligado
    - Best-effort: tenta converter `search=` em URL canônica via /api/gen-ai/search (cache 24h)
    """

    # 1) Tenta “upgrade” do URL para filtros canônicos (marca/modelo) quando vier no formato `search=`.
    page_url = search_url
    prompt = _extract_prompt_from_search_url(search_url)
    if prompt:
        upgraded = _genai_resolve_stock_url(prompt, ctx)
        if upgraded:
            page_url = upgraded

    # 2) Browser-first: captura do XHR /api/search/car
    payload: Optional[dict] = None
    browser_capture_error: Optional[Exception] = None
    browser_capture_no_json = False

    if bool(getattr(settings, "enable_playwright", False)):
        try:
            payload = _capture_search_payload_browser(page_url, ctx)
        except FetchBlocked:
            raise
        except RuntimeError as e:
            msg = str(e).lower()
            if "playwright disabled for source" in msg:
                # Gate/config desligado -> tenta HTTP
                browser_capture_error = e
            elif "no json response matched" in msg or "capture failed" in msg:
                browser_capture_no_json = True
                browser_capture_error = e
            else:
                browser_capture_error = e
        except Exception as e:
            browser_capture_error = e

    # Se force_browser está ligado, falha cedo (não tenta HTTP).
    if payload is None and getattr(ctx, "force_browser", False):
        if browser_capture_no_json:
            raise FetchBlocked(200, page_url, reason="no_json_capture")
        if browser_capture_error:
            raise browser_capture_error
        raise RuntimeError("force_browser=true but Playwright is unavailable")

    # 3) Fallback HTTP (quando Playwright indisponível/desligado ou falhou)
    if payload is None:
        url2 = _encode_url_param(page_url)
        api_url = f"{WEBMOTORS_SEARCH_API}?url={url2}&actualPage=1&displayPerPage=60"
        try:
            payload_any = fetch_json(
                api_url,
                ctx=ctx,
                referer=WEBMOTORS_BASE + "/",
                proxy=ctx.proxy_server,
                min_delay_ms=650,
                max_delay_ms=2100,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            payload = payload_any if isinstance(payload_any, dict) else {}
        except FetchBlocked:
            # Se browser tentou mas não conseguiu capturar nada, marca como blocked (challenge/hard block).
            if browser_capture_no_json and bool(getattr(settings, "enable_playwright", False)):
                raise FetchBlocked(200, page_url, reason="no_json_capture")
            raise
        except Exception:
            # Último recurso: quando browser fallback está habilitado, tenta só checar challenge e sair.
            if bool(getattr(settings, "enable_playwright", False)) and getattr(ctx, "browser_fallback_enabled", False):
                try:
                    fetch_html_browser(page_url, ctx=ctx, timeout_ms=20000, wait_until="domcontentloaded")
                except FetchBlocked:
                    raise
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

    return finalize_listings("webmotors", out)
