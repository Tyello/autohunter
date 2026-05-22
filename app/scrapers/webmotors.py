from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from dataclasses import replace
from typing import Optional
from urllib.parse import urljoin

from app.core.settings import settings
from app.scrapers.base import FetchBlocked
from app.scrapers.contract import finalize_listings
from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.scrapers.webmotors_debug import maybe_capture_webmotors_artifacts
from app.sources.types import ScrapeContext
from app.scrapers.webmotors_ops import (
    classify_webmotors_error,
    encode_webmotors_diag,
    extract_webmotors_diag,
)

WEBMOTORS_BASE = "https://www.webmotors.com.br"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def _extract_external_id(url: str) -> str:
    # geralmente o ID é numérico no final do path
    m = re.search(r"/(\d{6,})(?:\?|#|$)", url)
    if m:
        return m.group(1)
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]


_LOC_RE = re.compile(r"\b([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{2,})\s*[-/]\s*([A-Z]{2})\b")


def _extract_location(text: str) -> Optional[str]:
    t = _clean(text)
    m = _LOC_RE.search(t)
    if not m:
        return None
    city = _clean(m.group(1))
    st = (m.group(2) or "").strip()
    if not city or not st:
        return None
    return f"{city}-{st}"


def _pick_thumb(el) -> Optional[str]:
    try:
        for xp in (".//img/@src", ".//img/@data-src", ".//img/@data-lazy-src", ".//img/@srcset"):
            vals = el.xpath(xp)
            for v in vals:
                v = (v or "").strip()
                if not v:
                    continue
                # srcset: pega o primeiro URL
                if "," in v:
                    v = v.split(",")[0].strip().split(" ")[0].strip()
                if v.startswith("data:"):
                    continue
                low = v.lower()
                if any(x in low for x in ("logo", "sprite", "icon")):
                    continue
                return v
    except Exception:
        return None
    return None


def _parse_listings_from_html(html_text: str, page_url: str) -> list[dict]:
    """Parser de HTML renderizado (Playwright).

    Estratégia:
    - varre âncoras que apontam para páginas /comprar/ com um ID numérico
    - sobe no container do card e extrai título/preço/local/thumb por heurística

    Webmotors muda estrutura com frequência; isso é propositalmente tolerante.
    """

    if not html_text:
        return []

    try:
        from lxml import html as lhtml  # type: ignore
    except Exception:
        return []

    doc = lhtml.fromstring(html_text)
    doc.make_links_absolute(page_url)

    out_by_url: dict[str, dict] = {}

    # pega links de anúncios com ID numérico (evita nav/links genéricos)
    for a in doc.xpath("//a[contains(@href,'/comprar/') and @href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if "/comprar/" not in href:
            continue
        if not re.search(r"/(\d{6,})(?:\?|#|$)", href):
            continue

        url = href
        if url.startswith("/"):
            url = urljoin(WEBMOTORS_BASE, url)

        if url in out_by_url:
            continue

        # sobe em busca de um container mais "card-like"
        card = a
        for _ in range(8):
            p = card.getparent()
            if p is None:
                break
            card = p
            cls = (card.get("class") or "").lower()
            dt = (card.get("data-testid") or "").lower()
            if any(k in cls for k in ("card", "vehicle", "result", "listing")) or "card" in dt:
                break

        card_text = _clean(card.text_content() or "")

        # título: headings primeiro
        title = ""
        try:
            hs = card.xpath(".//*[self::h2 or self::h3 or self::h4]//text()")
            title = _clean(" ".join([x.strip() for x in hs if x and x.strip()]))
        except Exception:
            title = ""

        # fallback: atributo title do link / texto do link
        if not title:
            title = _clean((a.get("title") or "") or (a.text_content() or ""))

        # ainda vazio: usa primeiras palavras do card
        if not title and card_text:
            title = " ".join(card_text.split()[:12]).strip()

        # limpeza de UI
        tl = title.lower()
        if tl in ("ver detalhes", "detalhes", "comprar", "ver anúncio", "ver anuncio") or len(title) < 6:
            title = ""

        # preço (best-effort)
        price = None
        if "R$" in card_text:
            i = card_text.find("R$")
            price = parse_brl_price(card_text[i : i + 60])

        # localização
        loc = _extract_location(card_text)

        # thumb
        thumb = _pick_thumb(card)

        out_by_url[url] = {
            "source": "webmotors",
            "external_id": _extract_external_id(url),
            "url": url,
            "title": title or None,
            "price": (Decimal(str(int(price))) if price is not None else None),
            "thumbnail_url": thumb,
            "location": loc,
            "currency": "BRL",
        }

        if len(out_by_url) >= 70:
            break

    out = list(out_by_url.values())
    out.sort(key=lambda x: str(x.get("url") or ""))
    return out[:60]


def _looks_like_zero_results(html: str) -> bool:
    low = (html or "").lower()
    return any(
        k in low
        for k in (
            "nenhum veículo encontrado",
            "nenhum veiculo encontrado",
            "não encontramos resultados",
            "nao encontramos resultados",
            "0 resultados",
        )
    )


def _extract_title(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    if not m:
        return ""
    return _clean(m.group(1) or "")[:180]


def _detect_block_signals(html: str, *, final_url: str) -> list[str]:
    low = (html or "").lower()
    signals: list[str] = []
    checks = {
        "challenge_cloudflare": ["cloudflare", "just a moment", "cf-chl"],
        "challenge_captcha": ["captcha", "hcaptcha", "recaptcha", "data-sitekey"],
        "challenge_bot": ["verify you are", "are you human", "access denied", "perimeterx", "datadome", "incapsula"],
        "soft_block_interstitial": ["unusual traffic", "aguarde", "security check", "checking your browser"],
    }
    for key, needles in checks.items():
        if any(n in low for n in needles):
            signals.append(key)

    if len((html or "").strip()) < 1200:
        signals.append("suspicious_html_too_small")
    if "__next" in low and "/comprar/" not in low and "estoque" not in low:
        signals.append("js_shell_without_listing_content")
    f_low = (final_url or "").lower()
    if any(k in f_low for k in ("/challenge", "/security", "captcha", "blocked")):
        signals.append("suspicious_final_url")
    return signals


def _extra_bool(ctx: ScrapeContext, key: str, default: bool = False) -> bool:
    extra = getattr(ctx, "extra", None) or {}
    val = extra.get(key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        low = val.strip().lower()
        if low in {"1", "true", "yes", "on"}:
            return True
        if low in {"0", "false", "no", "off"}:
            return False
    return default


def _extra_str(ctx: ScrapeContext, key: str, default: str) -> str:
    extra = getattr(ctx, "extra", None) or {}
    val = extra.get(key, default)
    if val is None:
        return default
    s = str(val).strip()
    return s or default


def _looks_like_webmotors_challenge(html: str) -> tuple[bool, str | None]:
    low = (html or "").lower()
    checks: list[tuple[str, list[str]]] = [
        ("access_denied", ["access to this page has been denied"]),
        ("press_and_hold", ["pressione e segure"]),
        ("perimeterx", ["perimeterx", "provider=perimeterx"]),
        ("px_captcha", ["px-captcha"]),
        ("captcha", ["captcha"]),
        ("bot", ["bot_challenge_fingerprint", "bot"]),
        ("human_check", ["humano", "humano"]),
    ]
    for reason, needles in checks:
        if any(n in low for n in needles):
            return True, reason
    return False, None


def _fetch_webmotors_html_curl_cffi(search_url: str, ctx: ScrapeContext) -> tuple[int | None, str]:
    from curl_cffi import requests as curl_requests  # type: ignore

    kwargs = {
        "impersonate": _extra_str(ctx, "webmotors_curl_cffi_impersonate", "chrome"),
        "timeout": float(_extra_str(ctx, "webmotors_curl_cffi_timeout_s", "22")),
        "headers": {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    }
    if getattr(ctx, "proxy_server", None):
        kwargs["proxy"] = str(getattr(ctx, "proxy_server"))
    resp = curl_requests.get(search_url, **kwargs)
    return int(getattr(resp, "status_code", 0) or 0), str(getattr(resp, "text", "") or "")


def _format_curl_cffi_diag(*, enabled: bool, attempted: bool, impersonate: str, status: int | None, fallback_reason: str | None) -> str:
    if not enabled:
        return ""
    return (
        f"curl_cffi_attempted={str(attempted).lower()};"
        f"curl_cffi_enabled={str(enabled).lower()};"
        f"curl_cffi_impersonate={impersonate};"
        f"curl_cffi_status={status};"
        f"curl_cffi_fallback_reason={fallback_reason}"
    )


def _is_webmotors_blocked_diag(reason: str | None) -> bool:
    diag = extract_webmotors_diag(reason)
    return isinstance(diag, dict) and str(diag.get("bucket") or "").upper() == "BLOCKED"


def scrape_webmotors(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Webmotors (Playwright-first) com HTML fallback sempre.

    - Browser-only (SPA + anti-bot)
    - Extrai listagem via HTML renderizado

    Nota: isso elimina a fragilidade do capture de XHR (endpoints mudam, bloqueios variam).
    """

    last_diag_err: Optional[Exception] = None
    curl_cffi_enabled = _extra_bool(ctx, "webmotors_curl_cffi_enabled", default=False)
    curl_impersonate = _extra_str(ctx, "webmotors_curl_cffi_impersonate", "chrome")
    curl_fetch_path = "browser_direct"
    curl_fallback_reason: Optional[str] = None
    curl_status: int | None = None
    if curl_cffi_enabled:
        try:
            curl_status, curl_html = _fetch_webmotors_html_curl_cffi(search_url, ctx)
            blocked, _blocked_reason = _looks_like_webmotors_challenge(curl_html)
            if blocked:
                curl_fallback_reason = "challenge"
            else:
                curl_items = _parse_listings_from_html(curl_html, search_url)
                if curl_items:
                    return finalize_listings("webmotors", curl_items)
                if _looks_like_zero_results(curl_html):
                    return []
                curl_fallback_reason = "no_items"
            curl_fetch_path = "curl_cffi_then_browser"
        except ImportError:
            curl_fallback_reason = "not_installed"
            curl_fetch_path = "curl_cffi_then_browser"
        except Exception:
            curl_fallback_reason = "error"
            curl_fetch_path = "curl_cffi_then_browser"
        if curl_fallback_reason:
            last_diag_err = RuntimeError(_format_curl_cffi_diag(enabled=True, attempted=True, impersonate=curl_impersonate, status=curl_status, fallback_reason=curl_fallback_reason))

    curl_diag = _format_curl_cffi_diag(
        enabled=curl_cffi_enabled,
        attempted=curl_cffi_enabled,
        impersonate=curl_impersonate,
        status=curl_status,
        fallback_reason=curl_fallback_reason,
    )

    wait_modes = [str(getattr(ctx, "browser_wait_until", None) or "domcontentloaded"), "networkidle"]
    if wait_modes[0] == wait_modes[1]:
        wait_modes = [wait_modes[0]]

    path_ctxs: list[tuple[str, ScrapeContext]] = [("browser_direct", ctx)]
    if getattr(ctx, "proxy_server", None):
        path_ctxs = [("browser_proxy", ctx), ("browser_direct", replace(ctx, proxy_server=None))]

    attempt = 0
    fallback_used = False
    debug_enabled = bool((getattr(ctx, "extra", None) or {}).get("webmotors_debug_capture", settings.webmotors_debug_capture_enabled))

    for path_idx, (fetch_path, run_ctx) in enumerate(path_ctxs):
        if path_idx == 0 and curl_fetch_path == "curl_cffi_then_browser":
            fetch_path = "curl_cffi_then_browser"
        if path_idx > 0:
            fallback_used = True
        for wait_until in wait_modes:
            attempt += 1
            try:
                res = fetch_html_browser(
                    search_url,
                    ctx=run_ctx,
                    timeout_ms=int(getattr(run_ctx, "browser_timeout_ms", 60000) or 60000),
                    wait_until=wait_until,
                    min_delay_ms=int(getattr(run_ctx, "browser_min_delay_ms", 120) or 120),
                    max_delay_ms=int(getattr(run_ctx, "browser_max_delay_ms", 520) or 520),
                )
                items = _parse_listings_from_html(res.html, res.final_url or search_url)
                if items:
                    return finalize_listings("webmotors", items)
                if _looks_like_zero_results(res.html):
                    return []
                page_title = _extract_title(res.html)
                signals = _detect_block_signals(res.html, final_url=res.final_url or search_url)
                strong_signals = [s for s in signals if s != "suspicious_html_too_small"]
                if curl_diag:
                    strong_signals.append(curl_diag)
                if strong_signals:
                    diag = classify_webmotors_error(
                        FetchBlocked(200, search_url, reason="soft_block_or_challenge_200"),
                        stage="parse_listings",
                        fetch_path=fetch_path,
                        attempt=attempt,
                        http_status=200,
                        final_url=res.final_url or search_url,
                        page_title=page_title,
                        blocked_reason=f"soft_block_or_challenge_200;{curl_diag}" if curl_diag else "soft_block_or_challenge_200",
                        detected_signals=strong_signals,
                        cards_found=len(items),
                        fallback_used=fallback_used,
                    )
                    cap = maybe_capture_webmotors_artifacts(
                        enabled=debug_enabled,
                        url=search_url,
                        fetch_path=fetch_path,
                        status="blocked",
                        final_url=res.final_url,
                        html=res.html,
                        cards_found=len(items),
                        blocked_reason=f"soft_block_or_challenge_200;{curl_diag}" if curl_diag else "soft_block_or_challenge_200",
                        detected_signals=strong_signals,
                        fallback_used=fallback_used,
                        attempt=attempt,
                        page_title=page_title,
                    )
                    if cap is not None:
                        diag = replace(diag, evidence=f"{diag.evidence};debug_metadata={cap.metadata_path}")
                    raise FetchBlocked(200, search_url, reason=encode_webmotors_diag(diag))
                diag = classify_webmotors_error(
                    RuntimeError("no_items_parsed"),
                    stage="parse_listings",
                    fetch_path=fetch_path,
                    attempt=attempt,
                    fallback_used=fallback_used,
                    http_status=200,
                    final_url=res.final_url or search_url,
                    page_title=page_title,
                    blocked_reason=f"no_cards_parsed;{curl_diag}" if curl_diag else "no_cards_parsed",
                    detected_signals=[],
                    cards_found=len(items),
                )
                last_diag_err = RuntimeError(encode_webmotors_diag(diag))
            except FetchBlocked as e:
                reason = str(getattr(e, "reason", "") or "")
                if "WM_DIAG::" in reason:
                    if fetch_path == "browser_direct" or _is_webmotors_blocked_diag(reason):
                        raise
                    last_diag_err = RuntimeError(reason or "blocked")
                    break
                diag = classify_webmotors_error(
                    e,
                    stage="browser_fetch",
                    fetch_path=fetch_path,
                    attempt=attempt,
                    fallback_used=fallback_used,
                    http_status=int(getattr(e, "status_code", 0) or 0) or None,
                    blocked_reason=f"{str(getattr(e, 'reason', '') or 'fetch_blocked')};{curl_diag}" if curl_diag else str(getattr(e, "reason", "") or "fetch_blocked"),
                )
                # blocked on direct path is terminal; proxy path can fallback to direct once.
                if fetch_path == "browser_direct":
                    raise FetchBlocked(e.status_code, search_url, reason=encode_webmotors_diag(diag)) from e
                last_diag_err = RuntimeError(encode_webmotors_diag(diag))
                break
            except Exception as e:
                diag = classify_webmotors_error(
                    e,
                    stage="browser_fetch",
                    fetch_path=fetch_path,
                    attempt=attempt,
                    fallback_used=fallback_used,
                )
                last_diag_err = RuntimeError(encode_webmotors_diag(diag))
                if diag.bucket in {"BLOCKED", "PROXY"}:
                    break

    if _is_webmotors_blocked_diag(str(last_diag_err or "")):
        diag = extract_webmotors_diag(str(last_diag_err))
        status = 200
        if isinstance(diag, dict):
            status = int(diag.get("http_status") or 200)
        raise FetchBlocked(status, search_url, reason=str(last_diag_err)) from last_diag_err
    raise last_diag_err or RuntimeError("webmotors_html_fallback_failed")
