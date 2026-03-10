from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from dataclasses import replace
from typing import Optional
from urllib.parse import urljoin

from app.scrapers.base import FetchBlocked
from app.scrapers.contract import finalize_listings
from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext
from app.scrapers.webmotors_ops import (
    classify_webmotors_error,
    encode_webmotors_diag,
)

WEBMOTORS_BASE = "https://www.webmotors.com.br"


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


def scrape_webmotors(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Webmotors (Playwright-first) com HTML fallback sempre.

    - Browser-only (SPA + anti-bot)
    - Extrai listagem via HTML renderizado

    Nota: isso elimina a fragilidade do capture de XHR (endpoints mudam, bloqueios variam).
    """

    wait_modes = [str(getattr(ctx, "browser_wait_until", None) or "domcontentloaded"), "networkidle"]
    if wait_modes[0] == wait_modes[1]:
        wait_modes = [wait_modes[0]]

    path_ctxs: list[tuple[str, ScrapeContext]] = [("browser_direct", ctx)]
    if getattr(ctx, "proxy_server", None):
        path_ctxs = [("browser_proxy", ctx), ("browser_direct", replace(ctx, proxy_server=None))]

    attempt = 0
    fallback_used = False
    last_diag_err: Optional[Exception] = None

    for path_idx, (fetch_path, run_ctx) in enumerate(path_ctxs):
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
                diag = classify_webmotors_error(
                    RuntimeError("no_items_parsed"),
                    stage="parse_listings",
                    fetch_path=fetch_path,
                    attempt=attempt,
                    fallback_used=fallback_used,
                )
                last_diag_err = RuntimeError(encode_webmotors_diag(diag))
            except FetchBlocked as e:
                diag = classify_webmotors_error(
                    e,
                    stage="browser_fetch",
                    fetch_path=fetch_path,
                    attempt=attempt,
                    fallback_used=fallback_used,
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

    raise last_diag_err or RuntimeError("webmotors_html_fallback_failed")
