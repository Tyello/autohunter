from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html, FetchBlocked
from app.core.settings import settings
from app.services.browser_fetcher import fetch_html_browser, fetch_json_browser
from app.sources.types import ScrapeContext

# Optional: lightweight HTTP with TLS/browser fingerprint (best effort).
try:  # pragma: no cover
    from curl_cffi import requests as cf_requests  # type: ignore
except Exception:  # pragma: no cover
    cf_requests = None


# ----------------------------
# OLX health metrics (file-backed)
# ----------------------------

_OLX_HEALTH_LOCK = threading.Lock()
_OLX_HEALTH_PATH = os.getenv("OLX_HEALTH_PATH", ".data/health/olx.json")
_OLX_FORCE_BROWSER_HOURS_DEFAULT = int(os.getenv("OLX_FORCE_BROWSER_HOURS", "6"))
_OLX_IMPERSONATE = os.getenv("OLX_IMPERSONATE", "chrome120")


def _now_ts() -> int:
    return int(time.time())


def _ensure_health_dir() -> None:
    p = Path(_OLX_HEALTH_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)


def _read_health_unlocked() -> dict:
    try:
        with open(_OLX_HEALTH_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {}
        return d
    except Exception:
        return {}


def _write_health_unlocked(d: dict) -> None:
    _ensure_health_dir()
    tmp = _OLX_HEALTH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, _OLX_HEALTH_PATH)


def _prune_ts_24h(ts_list: list[int]) -> list[int]:
    now = _now_ts()
    cutoff = now - 24 * 3600
    return [t for t in ts_list if isinstance(t, int) and t >= cutoff]


def _health_update(fn) -> None:
    with _OLX_HEALTH_LOCK:
        d = _read_health_unlocked()
        if not isinstance(d, dict):
            d = {}
        fn(d)
        _write_health_unlocked(d)


def olx_health_record_http_ok() -> None:
    def _upd(d: dict) -> None:
        d["last_http_ok_ts"] = _now_ts()
        # Se HTTP voltou a funcionar, removemos o force-browser runtime.
        d["force_browser_until_ts"] = 0

    _health_update(_upd)


def olx_health_record_browser_fallback() -> None:
    def _upd(d: dict) -> None:
        arr = d.get("browser_fallback_ts")
        if not isinstance(arr, list):
            arr = []
        arr.append(_now_ts())
        d["browser_fallback_ts"] = _prune_ts_24h(arr)

    _health_update(_upd)


def olx_health_force_browser(hours: int | None = None) -> None:
    hours = hours or _OLX_FORCE_BROWSER_HOURS_DEFAULT

    def _upd(d: dict) -> None:
        d["force_browser_until_ts"] = _now_ts() + int(hours * 3600)

    _health_update(_upd)


def olx_health_runtime_force_remaining_sec() -> int:
    with _OLX_HEALTH_LOCK:
        d = _read_health_unlocked()
    until = int(d.get("force_browser_until_ts") or 0)
    rem = until - _now_ts()
    return rem if rem > 0 else 0


def olx_health_last_http_ok_ts() -> Optional[int]:
    with _OLX_HEALTH_LOCK:
        d = _read_health_unlocked()
    v = d.get("last_http_ok_ts")
    return int(v) if isinstance(v, (int, float)) and v > 0 else None


def olx_health_browser_fallback_count_24h() -> int:
    with _OLX_HEALTH_LOCK:
        d = _read_health_unlocked()
    arr = d.get("browser_fallback_ts")
    if not isinstance(arr, list):
        return 0
    return len(_prune_ts_24h([int(x) for x in arr if isinstance(x, (int, float))]))


def get_olx_health_snapshot() -> dict:
    """Para expor no /admin/health."""
    last_http = olx_health_last_http_ok_ts()
    rem = olx_health_runtime_force_remaining_sec()
    return {
        "last_http_ok_ts": last_http,
        "last_http_ok_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(last_http)) if last_http else None,
        "browser_fallback_24h": olx_health_browser_fallback_count_24h(),
        "force_browser_runtime_remaining_sec": rem,
        "force_browser_runtime_remaining_human": f"{rem // 3600}h{(rem % 3600) // 60:02d}m" if rem else "0",
        "force_browser_config_enabled": bool(getattr(settings, "olx_force_browser", False)),
        "fingerprint_http_enabled": cf_requests is not None,
    }


# ----------------------------
# Scraper
# ----------------------------


@dataclass
class OlxItem:
    external_id: str
    title: str
    url: str
    thumbnail_url: Optional[str]
    price: Optional[Decimal]
    currency: str = "BRL"
    location: Optional[str] = None


def build_olx_search_url(query: str, page: int = 1) -> str:
    q = quote_plus(query.strip())
    #return f"https://www.olx.com.br/brasil?q={q}&o={page}"
    return f"https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q={q}&o={page}"


def _parse_brl_price_to_decimal(text: str) -> Optional[Decimal]:
    if not text:
        return None
    t = text.strip()
    t = t.replace("R$", "").strip()
    t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return None


def _walk(obj: Any) -> Iterable[Any]:
    """Percorre estrutura JSON (dict/list) produzindo todos os nós."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk(x)


def _extract_next_data_json(html: str) -> Optional[dict]:
    """
    Tenta extrair o JSON do <script id="__NEXT_DATA__" type="application/json">...</script>
    (padrão Next.js). Se não achar, tenta fallback por regex.
    """
    soup = BeautifulSoup(html, "html.parser")

    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            return json.loads(tag.string)
        except Exception:
            pass

    # fallback (caso o parser não pegue string por tamanho)
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None


def _extract_items_from_next_data(next_data: dict) -> list[OlxItem]:
    """
    Os itens aparecem com chaves como:
    - subject
    - priceValue / price
    - friendlyUrl
    - listId
    - images (com urls)
    """
    items: list[OlxItem] = []

    for node in _walk(next_data):
        if not isinstance(node, dict):
            continue

        # padrão “listing”
        if "listId" in node and ("friendlyUrl" in node or "url" in node):
            list_id = node.get("listId")
            url = node.get("friendlyUrl") or node.get("url")
            title = node.get("subject") or node.get("title") or ""

            if not list_id or not url:
                continue

            # thumbnail
            thumb = None
            imgs = node.get("images")
            if isinstance(imgs, list) and imgs:
                first = imgs[0]
                if isinstance(first, dict):
                    thumb = first.get("originalWebp") or first.get("original")
                elif isinstance(first, str):
                    thumb = first

            # preço (pode vir em priceValue ou price)
            price_text = node.get("priceValue") or node.get("price") or ""
            price = _parse_brl_price_to_decimal(price_text)

            # localização (quando vier)
            loc = None
            loc_details = node.get("locationDetails")
            if isinstance(loc_details, dict):
                mun = loc_details.get("municipality")
                uf = loc_details.get("uf")
                if mun and uf:
                    loc = f"{mun}-{uf}"
                elif uf:
                    loc = uf

            items.append(
                OlxItem(
                    external_id=str(list_id),
                    title=title.strip(),
                    url=url,
                    thumbnail_url=thumb,
                    price=price,
                    location=loc,
                )
            )

    # de-dup interno por external_id
    seen = set()
    unique: list[OlxItem] = []
    for it in items:
        if it.external_id in seen:
            continue
        seen.add(it.external_id)
        unique.append(it)

    return unique


def _items_to_dicts(items: list[OlxItem]) -> list[dict]:
    out: list[dict] = []
    for it in items:
        out.append(
            {
                "source": "olx",
                "external_id": str(it.external_id),
                "title": it.title or None,
                "url": it.url,
                "thumbnail_url": it.thumbnail_url,
                "price": it.price,
                "currency": "BRL",
                "location": it.location,
            }
        )
    return out


def _looks_like_cf_or_bot(html: str) -> bool:
    h = (html or "").lower()
    return (
        "captcha" in h
        or "cloudflare" in h
        or "attention required" in h
        or "verify you are" in h
        or "access denied" in h
    )


def _storage_state_path_for_ctx(ctx: ScrapeContext, source: str) -> str:
    base = Path(getattr(settings, "playwright_storage_dir", None) or ".data/playwright")
    base.mkdir(parents=True, exist_ok=True)
    proxy_key = ctx.proxy_server or "__no_proxy__"
    safe_proxy = proxy_key.replace(":", "_").replace("/", "_")
    safe_source = (source or "unknown").replace(":", "_").replace("/", "_")
    return str(base / f"storage_{safe_source}__{safe_proxy}.json")


def _load_playwright_cookies_for_olx(ctx: ScrapeContext) -> dict[str, str]:
    """Reaproveita cookies persistidos pelo PlaywrightPool (storage_state)."""
    src = (ctx.source or "olx").lower().strip() or "olx"
    path = _storage_state_path_for_ctx(ctx, src)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies") or []
        out: dict[str, str] = {}
        for c in cookies:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            value = c.get("value")
            domain = (c.get("domain") or "")
            if not name or value is None:
                continue
            # mantém cookies de olx (ou domínios “largos”)
            if "olx.com.br" in domain or domain.endswith(".olx.com.br") or domain == "":
                out[str(name)] = str(value)
        return out
    except Exception:
        return {}


def _fetch_http_hybrid(search_url: str, ctx: ScrapeContext, *, min_delay_ms: int, max_delay_ms: int) -> str:
    """HTTP leve (preferência), com fingerprint quando disponível e cookies do Playwright."""
    time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

    referer = "https://www.olx.com.br/"

    # 1) Preferência: curl_cffi com TLS fingerprint
    if cf_requests is not None:
        cookies = _load_playwright_cookies_for_olx(ctx)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": referer,
        }

        proxies = None
        if ctx.proxy_server:
            proxies = {"http": ctx.proxy_server, "https": ctx.proxy_server}

        r = cf_requests.get(
            search_url,
            headers=headers,
            cookies=cookies or None,
            proxies=proxies,
            timeout=25,
            allow_redirects=True,
            impersonate=_OLX_IMPERSONATE,
        )

        status = int(getattr(r, "status_code", 0) or 0)
        text = getattr(r, "text", "") or ""

        if status in (403, 429):
            raise FetchBlocked(status, search_url, reason="http_status")

        if status == 200 and _looks_like_cf_or_bot(text):
            raise FetchBlocked(200, search_url, reason="bot_challenge")

        if status >= 400:
            raise FetchBlocked(status, search_url, reason="http_status")

        olx_health_record_http_ok()
        return text

    # 2) Fallback: requests hardened (pode ser bloqueado)
    html = fetch_html(
        search_url,
        referer=referer,
        proxy=ctx.proxy_server,
        min_delay_ms=0,
        max_delay_ms=0,
    )
    olx_health_record_http_ok()
    return html


def _runtime_force_browser_active() -> bool:
    return olx_health_runtime_force_remaining_sec() > 0


def scrape_olx(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Retorna lista de dicts pronta para ingest_listings().

    Estratégia OLX (Pi-friendly):
    - HTTP (fingerprint + cookies do Playwright storage_state) como caminho leve.
    - Se bloquear (403/challenge), usa Playwright para aquecer cookies e tenta HTTP novamente.
    - Se ainda bloquear, entra em force-browser runtime por N horas (default 6h) para evitar loops de 403.
    """

    min_http_delay = 1200
    max_http_delay = 4200

    force_browser_mode = bool(getattr(settings, "olx_force_browser", False)) or _runtime_force_browser_active()

    def _fetch_browser_html() -> str:
        res = fetch_html_browser(
            search_url,
            ctx=ctx,
            wait_until="domcontentloaded",
            timeout_ms=20000,
            min_delay_ms=300,
            max_delay_ms=900,
        )
        return res.html

    # 1) Force browser path
    if force_browser_mode and bool(getattr(settings, "enable_playwright", False)):
        try:
            j = fetch_json_browser(
                search_url,
                ctx=ctx,
                wait_until="domcontentloaded",
                timeout_ms=20000,
                capture_mode="olx_next_data",
                min_delay_ms=300,
                max_delay_ms=900,
            ).data

            if not any(
                isinstance(n, dict) and "listId" in n and ("friendlyUrl" in n or "url" in n)
                for n in _walk(j)
            ):
                raise RuntimeError("Captured JSON did not include OLX listings")

            items = _extract_items_from_next_data(j)
            return _items_to_dicts(items)
        except Exception:
            html = _fetch_browser_html()

        next_data = _extract_next_data_json(html)
        if not next_data:
            items = _fallback_parse_from_cards(html)
            if not items:
                raise FetchBlocked(200, search_url, reason="empty_or_unparseable")
            return _items_to_dicts(items)

        items = _extract_items_from_next_data(next_data)
        return _items_to_dicts(items)

    # 2) Preferred: HTTP hybrid
    try:
        html = _fetch_http_hybrid(search_url, ctx, min_delay_ms=min_http_delay, max_delay_ms=max_http_delay)
    except FetchBlocked:
        if bool(getattr(settings, "enable_playwright", False)) and bool(getattr(settings, "enable_olx_browser_fallback", True)):
            # caiu no browser (fallback)
            olx_health_record_browser_fallback()

            # Warmup cookies/session via real browser (persisted in storage_state)
            try:
                _fetch_browser_html()
            except Exception:
                pass

            # Retry HTTP once
            try:
                html = _fetch_http_hybrid(search_url, ctx, min_delay_ms=400, max_delay_ms=1200)
            except FetchBlocked:
                # Still blocked -> enter runtime force browser for a while
                olx_health_force_browser()
                html = _fetch_browser_html()
        else:
            raise

    next_data = _extract_next_data_json(html)
    if not next_data:
        items = _fallback_parse_from_cards(html)
        if not items:
            raise FetchBlocked(200, search_url, reason="empty_or_unparseable")
        return _items_to_dicts(items)

    items = _extract_items_from_next_data(next_data)
    return _items_to_dicts(items)


def _fallback_parse_from_cards(html: str) -> list[OlxItem]:
    """Fallback se __NEXT_DATA__ não estiver disponível."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[OlxItem] = []

    for a in soup.select('a[data-testid="adcard-link"]'):
        href = a.get("href")
        if not href:
            continue

        title = (a.get_text(" ", strip=True) or "").strip()

        price = None
        price_text = None
        container = a.find_parent()
        if container:
            price_el = container.select_one(".olx-adcard__price")
            if price_el:
                price_text = price_el.get_text(strip=True)
                price = _parse_brl_price_to_decimal(price_text)

        img = None
        if container:
            img_el = container.select_one("img")
            if img_el:
                img = img_el.get("src")

        m = re.search(r"(\d{6,})", href)
        external_id = m.group(1) if m else href

        out.append(
            OlxItem(
                external_id=external_id,
                title=title,
                url=href,
                thumbnail_url=img,
                price=price,
            )
        )

    seen = set()
    unique = []
    for it in out:
        if it.external_id in seen:
            continue
        seen.add(it.external_id)
        unique.append(it)
    return unique
