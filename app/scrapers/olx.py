from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html, FetchBlocked
from app.scrapers.parsing import parse_brl_price
from app.scrapers.contract import finalize_listings
from app.core.settings import settings

logger = logging.getLogger(__name__)
from app.core.runtime_paths import health_dir, playwright_storage_dir
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
_OLX_HEALTH_PATH = settings.olx_health_path or str(health_dir() / "olx.json")
_OLX_FORCE_BROWSER_HOURS_DEFAULT = int(settings.olx_force_browser_hours)
_OLX_IMPERSONATE = settings.olx_impersonate


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


def _walk(obj: Any) -> Iterable[Any]:
    """Percorre estrutura JSON (dict/list) produzindo todos os nós."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _walk(x)


_PLACEHOLDER_RE = re.compile(
    r"(placeholder|no[-_]?image|sem[-_]?foto|logo|sprite|avatar|blank|transparent|1x1|olx-share)",
    re.I,
)
_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|webp)(?:[?#].*)?$", re.I)


def _first_srcset_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.split(",", 1)[0].strip().split(" ", 1)[0].strip() or None


def _normalize_olx_image_url(value: Any, base_url: str = "https://www.olx.com.br/") -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or raw.startswith(("data:", "blob:", "javascript:")):
        return None
    if "," in raw and " " in raw:
        raw = _first_srcset_url(raw) or raw
    url = urljoin(base_url, raw)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    low = url.lower()
    if _PLACEHOLDER_RE.search(low):
        return None
    host = parsed.netloc.lower()
    if not (_IMAGE_EXT_RE.search(low) or any(token in host for token in ("olxcdn", "img", "image", "cloudfront"))):
        return None
    return url


def _pick_olx_image_from_obj(obj: Any, base_url: str = "https://www.olx.com.br/") -> str | None:
    if isinstance(obj, dict):
        for key in ("originalWebp", "original", "thumbnail", "imageUrl", "image_url", "src"):
            img = _normalize_olx_image_url(obj.get(key), base_url)
            if img:
                return img
        if any(k in obj for k in ("width", "height", "mime", "type", "originalWebp", "original", "thumbnail")):
            img = _normalize_olx_image_url(obj.get("url"), base_url)
            if img:
                return img
        for key, value in obj.items():
            if key in {"subject", "title", "price", "priceValue", "description", "friendlyUrl", "url"}:
                continue
            img = _pick_olx_image_from_obj(value, base_url)
            if img:
                return img
    elif isinstance(obj, list):
        for value in obj:
            img = _pick_olx_image_from_obj(value, base_url)
            if img:
                return img
    elif isinstance(obj, str):
        return _normalize_olx_image_url(obj, base_url)
    return None


def _image_from_tag(tag: Any, base_url: str) -> str | None:
    for attr in ("src", "data-src", "data-original", "data-lazy"):
        img = _normalize_olx_image_url(tag.get(attr), base_url)
        if img:
            return img
    return _normalize_olx_image_url(_first_srcset_url(tag.get("srcset")), base_url)


def _extract_olx_detail_thumbnail(html: str, detail_url: str) -> str | None:
    soup = BeautifulSoup(html or "", "html.parser")
    for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]', 'meta[property="twitter:image"]'):
        tag = soup.select_one(selector)
        if tag:
            img = _normalize_olx_image_url(tag.get("content"), detail_url)
            if img:
                return img
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or "{}")
        except Exception:
            continue
        payload = data.get("image") if isinstance(data, dict) else data
        img = _pick_olx_image_from_obj(payload, detail_url)
        if img:
            return img
    for tag in soup.select("picture source, picture img, [data-testid*=gallery] source, [data-testid*=gallery] img, .gallery source, .gallery img, img"):
        img = _image_from_tag(tag, detail_url)
        if img:
            return img
    for tag in soup.select('[style*="background"]'):
        m = re.search(r"url\(['\"]?([^)'\"]+)", tag.get("style") or "", flags=re.I)
        if m:
            img = _normalize_olx_image_url(m.group(1), detail_url)
            if img:
                return img
    return None


def _fetch_olx_detail_html(url: str, ctx: ScrapeContext) -> str:
    """Busca a pagina de detalhe com o mesmo hardening (TLS impersonation + cookies) usado
    na busca principal (_fetch_http_hybrid). Sem esse hardening, a OLX bloqueia o fetch de
    detalhe a partir de IPs de datacenter e o parser roda sobre uma pagina de bloqueio."""
    referer = "https://www.olx.com.br/"
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
            url,
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
            raise FetchBlocked(status, url, reason="http_status")
        if status == 200 and _looks_like_cf_or_bot(text):
            raise FetchBlocked(200, url, reason="bot_challenge")
        if status >= 400:
            raise FetchBlocked(status, url, reason="http_status")
        return text
    return fetch_html(url, ctx=ctx, referer=referer, proxy=ctx.proxy_server, min_delay_ms=0, max_delay_ms=0)


def _enrich_missing_olx_thumbnails(items: list[OlxItem], ctx: ScrapeContext, *, limit: int | None = None) -> list[OlxItem]:
    cap = max(0, int(limit if limit is not None else getattr(settings, "olx_detail_thumbnail_enrich_limit", 3) or 0))
    missing = [it for it in items if not it.thumbnail_url and it.url]
    if len(missing) > cap:
        logger.warning(
            "_enrich_missing_olx_thumbnails: %s items missing thumbnail but cap is %s, %s will stay without photo this run",
            len(missing), cap, len(missing) - cap,
        )
    enriched = 0
    for item in items:
        if enriched >= cap:
            break
        if item.thumbnail_url or not item.url:
            continue
        was_blocked = False
        try:
            html = _fetch_olx_detail_html(item.url, ctx=ctx)
            thumb = _extract_olx_detail_thumbnail(html, item.url)
        except FetchBlocked as exc:
            thumb = None
            was_blocked = True
            logger.warning(
                "_enrich_missing_olx_thumbnails: detail page BLOCKED %s (status=%s reason=%s)",
                item.url, exc.status_code, exc.reason
            )
        except Exception as exc:
            thumb = None
            logger.warning("_enrich_missing_olx_thumbnails: failed to fetch/parse detail page %s: %s", item.url, exc)
        if thumb:
            item.thumbnail_url = thumb
        elif not was_blocked:
            logger.warning("_enrich_missing_olx_thumbnails: no thumbnail found on detail page %s", item.url)
        enriched += 1
    return items

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


_NEXT_F_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)')
_RSC_CHUNK_PREFIX_RE = re.compile(r'^[0-9a-zA-Z]+:(.*)$', re.DOTALL)


def _extract_rsc_json_chunks(html: str) -> list[Any]:
    """Extrai os payloads JSON embutidos no streaming RSC do Next.js App Router:
    self.__next_f.push([1, "<chunkId>:<json...>"]).

    A OLX migrou as paginas de busca (e o parser antigo so olhava para
    <script id="__NEXT_DATA__">, formato do Pages Router) para esse streaming,
    entao _extract_next_data_json passou a nao encontrar nada e o codigo caia
    no fallback de cards em HTML, cujo seletor de preco (.olx-adcard__price)
    tambem ficou desatualizado -- resultado: titulo/url extraidos, preco None.
    """
    chunks: list[Any] = []
    for raw in _NEXT_F_PUSH_RE.findall(html or ""):
        try:
            decoded = json.loads(raw)
        except Exception:
            continue
        m = _RSC_CHUNK_PREFIX_RE.match(decoded)
        body = m.group(1) if m else decoded
        try:
            data = json.loads(body)
        except Exception:
            continue
        chunks.append(data)
    return chunks


def _extract_items_from_next_data(next_data: Any) -> list[OlxItem]:
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

            # thumbnail: OLX can expose images under several nested keys.
            thumb = _pick_olx_image_from_obj(node, str(url))

            # preço (pode vir em priceValue ou price)
            price_text = node.get("priceValue") or node.get("price") or ""
            price = parse_brl_price(price_text)

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


def _extract_year_from_title(title: str) -> Optional[int]:
    """Extrai o ano (1900-2099) do título usando regex.

    Retorna o último ano encontrado como int, ou None se nenhum encontrado.
    """
    matches = re.findall(r"\b(19\d{2}|20\d{2})\b", title)
    return int(matches[-1]) if matches else None


def _extract_mileage_from_title(title: str) -> Optional[int]:
    """Extrai a quilometragem do título usando regex.

    Suporta formatos como "45.000 km" ou "45000 km".
    Retorna a quilometragem como int (sem separadores/sufixo "km"), ou None
    se nenhuma encontrada. Retorna int (não string) porque o valor é
    persistido diretamente na coluna Integer `mileage_km`
    (app/repositories/car_listings_repo.py não faz coerção numérica nesse
    caminho de escrita).
    """
    m = re.search(r"\d{1,3}(?:\.\d{3})+\s*[Kk][Mm]\b|\b\d{4,6}\s*[Kk][Mm]\b", title)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    return int(digits) if digits else None


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
                "year": _extract_year_from_title(it.title),
                "km": _extract_mileage_from_title(it.title),
            }
        )
    return finalize_listings("olx", out)


def _looks_like_cf_or_bot(html: str) -> bool:
    """Detects an actual Cloudflare/bot *challenge* interstitial page.

    IMPORTANT: bare "cloudflare" is NOT a valid signal on its own. OLX
    embeds Cloudflare's bot-management/insights beacon
    (static.cloudflareinsights.com/beacon.min.js) and challenge-platform
    scripts on ordinary, fully-rendered listing pages as standard
    infrastructure -- confirmed by fetching real, successful detail pages
    that contain the word "cloudflare" yet have full content (700KB-1.6MB)
    and a correctly extractable og:image. A bare substring match on
    "cloudflare" therefore false-positives on legitimate pages and was
    discarding valid detail-page fetches before extraction ever ran.
    """
    h = (html or "").lower()
    return (
        "captcha" in h
        or "attention required" in h
        or "verify you are" in h
        or "access denied" in h
        or "just a moment" in h
        or "checking your browser" in h
        or "cf-browser-verification" in h
    )


def _storage_state_path_for_ctx(ctx: ScrapeContext, source: str) -> str:
    base = playwright_storage_dir()
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
        ctx=ctx,
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
            return _items_to_dicts(_enrich_missing_olx_thumbnails(items, ctx))
        except Exception:
            html = _fetch_browser_html()

        items = _parse_olx_listing_items(html)
        if not items:
            raise FetchBlocked(200, search_url, reason="empty_or_unparseable")
        return _items_to_dicts(_enrich_missing_olx_thumbnails(items, ctx))

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

    items = _parse_olx_listing_items(html)
    if not items:
        raise FetchBlocked(200, search_url, reason="empty_or_unparseable")
    return _items_to_dicts(_enrich_missing_olx_thumbnails(items, ctx))


def _parse_olx_listing_items(html: str) -> list[OlxItem]:
    """Tenta, em ordem: __NEXT_DATA__ (Pages Router, formato legado) -> chunks
    RSC do App Router (formato atual da busca) -> fallback de cards em HTML."""
    next_data = _extract_next_data_json(html)
    if next_data:
        items = _extract_items_from_next_data(next_data)
        if items:
            return items

    rsc_chunks = _extract_rsc_json_chunks(html)
    if rsc_chunks:
        items = _extract_items_from_next_data(rsc_chunks)
        if items:
            return items

    return _fallback_parse_from_cards(html)


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
                price = parse_brl_price(price_text)

        img = None
        if container:
            for media_el in container.select("picture source, picture img, img, source"):
                img = _image_from_tag(media_el, href)
                if img:
                    break
            if not img:
                for styled in container.select('[style*="background"]'):
                    m_bg = re.search(r"url\(['\"]?([^)'\"]+)", styled.get("style") or "", flags=re.I)
                    if m_bg:
                        img = _normalize_olx_image_url(m_bg.group(1), href)
                    if img:
                        break

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
