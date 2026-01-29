from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_html
from app.scrapers.parsing import parse_brl_price
from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


GOGARAGE_BASE = "https://www.gogarage.com.br"


def _to_decimal_brl(v: Any) -> Optional[Decimal]:
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


def _extract_jsonld_itemlist(html: str) -> List[Tuple[str, Optional[str]]]:
    """Tenta extrair urls de anúncios via JSON-LD (SEO-friendly)."""
    out: List[Tuple[str, Optional[str]]] = []
    for m in re.finditer(r"<script[^>]+type=\"application/ld\+json\"[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        candidates: List[dict] = []
        if isinstance(data, dict):
            candidates = [data]
        elif isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]

        for obj in candidates:
            if "itemListElement" not in obj:
                continue
            items = obj.get("itemListElement")
            if not isinstance(items, list):
                continue
            for el in items:
                url = None
                name = None
                if isinstance(el, dict):
                    # formatos comuns: {"url":...} ou {"item": {"@id":...}}
                    url = el.get("url") or el.get("@id")
                    item = el.get("item") if isinstance(el.get("item"), dict) else None
                    if not url and item:
                        url = item.get("@id") or item.get("url")
                        name = item.get("name")
                    if not name:
                        name = el.get("name")
                if isinstance(url, str) and "/ads/" in url:
                    out.append((url, name.strip() if isinstance(name, str) else None))

    # dedupe mantendo ordem
    seen = set()
    uniq: List[Tuple[str, Optional[str]]] = []
    for u, n in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append((u, n))
    return uniq


def _extract_from_anchors(html: str) -> List[str]:
    """Fallback: varre âncoras /ads/ no HTML."""
    try:
        from lxml import html as lhtml

        doc = lhtml.fromstring(html)
        urls = []
        for a in doc.xpath("//a[contains(@href,'/ads/') and @href]"):
            href = a.get("href")
            if not href:
                continue
            full = urljoin(GOGARAGE_BASE, href)
            if "/ads/" not in full:
                continue
            urls.append(full)

        # dedupe
        seen = set()
        out = []
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
        return out
    except Exception:
        # regex extremo
        urls = []
        for m in re.finditer(r'href="([^"]+/ads/[^"]+)"', html):
            urls.append(urljoin(GOGARAGE_BASE, m.group(1)))
        return list(dict.fromkeys(urls))


def _guess_external_id(url: str, blob: str) -> str:
    mid = re.search(r"#(\d+)", blob or "")
    if mid:
        return mid.group(1)
    # usa slug como id estável
    m = re.search(r"/ads/([^/?#]+)", url)
    return (m.group(1) if m else url).strip()


def _guess_title(url: str, anchor_text: str, blob: str, jsonld_name: Optional[str] = None) -> str:
    if jsonld_name and jsonld_name.strip():
        return re.sub(r"\s+", " ", jsonld_name).strip()
    t = (anchor_text or "").strip()
    if t and len(t) >= 6:
        return re.sub(r"\s+", " ", t)
    # tenta pegar primeira linha antes de preço
    b = re.sub(r"\s+", " ", (blob or "")).strip()
    if not b:
        return ""
    # remove preço pra sobrar título
    b2 = re.sub(r"R\$\s*[\d\.]+", "", b).strip()
    return b2[:120].strip()


def _guess_price(blob: str) -> Optional[Decimal]:
    if not blob:
        return None
    m = re.search(r"R\$\s*[\d\.]+", blob)
    if not m:
        m = re.search(r"R\$\s*[\d\.]+\,\d{2}", blob)
    if not m:
        return None
    return _to_decimal_brl(m.group(0))


def _guess_thumb(doc_el, card_el=None) -> Optional[str]:
    try:
        el = card_el or doc_el
        if el is None:
            return None
        imgs = el.xpath('.//img/@src')
        if imgs:
            return imgs[0]
    except Exception:
        return None
    return None


def fetch_details(url: str, *, ctx: ScrapeContext) -> Dict[str, Any]:
    """(Opcional) Completa campos essenciais de um anúncio."""
    html = fetch_html(
        url,
        referer=GOGARAGE_BASE + "/",
        proxy=ctx.proxy_server,
        min_delay_ms=700,
        max_delay_ms=2000,
    )

    title = ""
    thumb = None
    try:
        from lxml import html as lhtml

        doc = lhtml.fromstring(html)
        ogt = doc.xpath("//meta[@property='og:title']/@content")
        if ogt:
            title = ogt[0]
        if not title:
            t = doc.xpath("//title/text()")
            if t:
                title = t[0]
        ogi = doc.xpath("//meta[@property='og:image']/@content")
        if ogi:
            thumb = ogi[0]
    except Exception:
        pass

    price = _guess_price(html)
    external_id = _guess_external_id(url, html)

    return {
        "external_id": external_id,
        "title": re.sub(r"\s+", " ", (title or "")).strip() or None,
        "thumbnail_url": thumb,
        "price": price,
    }


def scrape_gogarage(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Scraper HTTP-first para Go Garage.

    - Prioriza HTML/JSON-LD (muito mais leve que renderizar JS)
    - Mantém fallback opcional via Playwright (desligado por padrão)
    """

    def _ctx_fallback_enabled() -> bool:
        # Compatível com versões antigas do ScrapeContext
        return bool(getattr(ctx, "browser_fallback_enabled", False))

    def _fetch_http(url: str) -> str:
        return fetch_html(
            url,
            referer=GOGARAGE_BASE + "/",
            proxy=ctx.proxy_server,
            min_delay_ms=700,
            max_delay_ms=2200,
        )

    def _fetch_browser(url: str) -> str:
        res = fetch_html_browser(url, ctx=ctx)
        return res.html

    def _alt_urls(url: str) -> list[str]:
        """Gera rotas alternativas quando o site muda (ex.: 404 em /?q=)."""
        try:
            from urllib.parse import urlparse, parse_qs, urlencode

            p = urlparse(url)
            qs = parse_qs(p.query or "")
            qv = (qs.get("q") or [""])[0]

            out: list[str] = []

            # 1) força www
            host = p.netloc
            if host and not host.startswith("www."):
                host_www = "www." + host
                out.append(p._replace(netloc=host_www).geturl())

            # 2) força /index.php?q=
            if qv:
                out.append(f"{GOGARAGE_BASE}/index.php?{urlencode({'q': qv})}")

            # 3) alternativa antiga /?q=
            if qv:
                out.append(f"{GOGARAGE_BASE}/?{urlencode({'q': qv})}")

            # dedupe mantendo ordem
            seen = set()
            uniq = []
            for u in out:
                if u in seen:
                    continue
                seen.add(u)
                uniq.append(u)
            return uniq
        except Exception:
            return []

    html = ""
    fetched_url = search_url
    try:
        html = _fetch_http(search_url)
    except FetchBlocked:
        if settings.enable_playwright and _ctx_fallback_enabled():
            html = _fetch_browser(search_url)
        else:
            raise
    except requests.HTTPError as e:
        # rota mudou / endpoint instável
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 404:
            for alt in _alt_urls(search_url):
                try:
                    html = _fetch_http(alt)
                    fetched_url = alt
                    break
                except Exception:
                    continue

            if not html and settings.enable_playwright and _ctx_fallback_enabled():
                # última tentativa: renderiza via browser em uma rota alternativa (ou a original)
                html = _fetch_browser(_alt_urls(search_url)[0] if _alt_urls(search_url) else search_url)
        else:
            raise

    # 1) JSON-LD (se existir)
    jsonld = _extract_jsonld_itemlist(html)
    jsonld_map = {u: n for u, n in jsonld}

    urls = [u for u, _ in jsonld] if jsonld else _extract_from_anchors(html)

    # Se veio HTML placeholder (JS) sem resultados, tenta renderizar via browser se permitido.
    if (
        (not urls)
        and settings.enable_playwright
        and _ctx_fallback_enabled()
        and any(s in html.lower() for s in ("carregando", "loading", "aguarde"))
    ):
        try:
            html = _fetch_browser(fetched_url)
            jsonld = _extract_jsonld_itemlist(html)
            jsonld_map = {u: n for u, n in jsonld}
            urls = [u for u, _ in jsonld] if jsonld else _extract_from_anchors(html)
        except Exception:
            pass

    out: List[dict] = []
    seen: set[str] = set()

    # Tentativa de enriquecer via leitura do HTML de listagem
    doc = None
    try:
        from lxml import html as lhtml

        doc = lhtml.fromstring(html)
        doc.make_links_absolute(GOGARAGE_BASE)
    except Exception:
        doc = None

    details_budget = 10  # limite de fetch_details por chamada

    for url in urls:
        if not isinstance(url, str) or "/ads/" not in url:
            continue

        anchor_text = ""
        blob = ""
        thumb = None

        if doc is not None:
            # tenta achar a âncora exata e seu "card" pai
            try:
                a_nodes = doc.xpath(f"//a[contains(@href, '{urlparse_safe(url)}')]")
            except Exception:
                a_nodes = []
            if a_nodes:
                a = a_nodes[0]
                anchor_text = " ".join([t.strip() for t in a.xpath('.//text()') if t and t.strip()]).strip()
                card = a
                for _ in range(6):
                    if card is None:
                        break
                    cls = (card.get('class') or '').lower()
                    if any(k in cls for k in ('card', 'achado', 'item', 'post', 'result')):
                        break
                    card = card.getparent()
                blob = (card.text_content() if card is not None else a.text_content()) or ""
                thumb = _guess_thumb(doc, card)

        external_id = _guess_external_id(url, blob)
        if external_id in seen:
            continue
        seen.add(external_id)

        title = _guess_title(url, anchor_text, blob, jsonld_map.get(url))
        price = _guess_price(blob)

        # Se faltou coisa crítica, gasta "orçamento" com details (bem limitado)
        if details_budget > 0 and (not title or price is None or thumb is None):
            try:
                d = fetch_details(url, ctx=ctx)
                details_budget -= 1
                external_id = str(d.get("external_id") or external_id)
                title = title or (d.get("title") or "")
                price = price or d.get("price")
                thumb = thumb or d.get("thumbnail_url")
            except Exception:
                details_budget -= 1

        out.append(
            {
                "source": "gogarage",
                "external_id": str(external_id),
                "title": title or None,
                "url": url,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": None,
            }
        )

        if len(out) >= 60:
            break

    return out


def urlparse_safe(url: str) -> str:
    """Retorna um fragmento estável do path para usar em xpath contains()."""
    m = re.search(r"/ads/[^/?#]+", url)
    return m.group(0) if m else url
