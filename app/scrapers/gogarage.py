from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus

import requests

from app.core.settings import settings
from app.scrapers.base import FetchBlocked, fetch_html
from app.scrapers.fetching import fetch_html_with_browser_fallback
from app.scrapers.parsing import parse_brl_price
from app.scrapers.contract import finalize_listings
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




def _clean_title_text(s: str) -> str:
    '''Normaliza títulos que às vezes vêm concatenados (ex: 'VolkswagenPolo').'''
    s = (s or '').strip()
    if not s:
        return ''
    # separa camelCase / MarcaModelo
    s = re.sub(r"(?<=[a-zÀ-ÿ])(?=[A-Z])", " ", s)
    # separa letras e números (ex: 'Polo2020' -> 'Polo 2020')
    s = re.sub(r"(?<=[A-Za-zÀ-ÿ])(?=\d)", " ", s)
    s = re.sub(r"(?<=\d)(?=[A-Za-zÀ-ÿ])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_bad_title(t: str) -> bool:
    """Detecta 'títulos' que na prática são UI (ex: '6 Visto', '9 pts Visto').

    Quando isso acontecer, forçamos fetch_details (orçamento limitado) para pegar og:title real.
    """
    t = (t or '').strip()
    if not t:
        return True
    tl = t.lower()
    if 'visto' in tl or 'pts' in tl or 'pontos' in tl:
        # se quase não há letras além da UI, é lixo
        letters = re.findall(r'[A-Za-zÀ-ÿ]', t)
        if len(letters) < 8:
            return True
        # padrões numéricos clássicos
        if re.fullmatch(r"\d+\s*(?:🚀\s*)?(?:\d+\s*)?(?:pts|pontos)?\s*visto", tl):
            return True
    # títulos só numéricos / muito curtos
    if len(t) < 6 and not re.search(r'[A-Za-zÀ-ÿ]{3,}', t):
        return True
    return False


def _strip_gogarage_suffix(title: str) -> str:
    """Remove sufixos de site como '— Go Garage 2026' do título."""
    t = (title or "").strip()
    if not t:
        return ""
    # Normaliza diferentes separadores (—, -, |) e remove ano do site no final.
    t = re.sub(r"\s*[\-|\|\u2014]\s*Go\s*Garage(?:\s*\d{4})?\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+Go\s*Garage(?:\s*\d{4})?\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _parse_srcset_first_url(srcset: str) -> Optional[str]:
    if not srcset:
        return None
    # srcset: "url1 320w, url2 640w" -> pega url1
    first = srcset.split(",")[0].strip()
    if not first:
        return None
    return first.split(" ")[0].strip() or None


def _extract_year_from_labels(text: str) -> Optional[int]:
    """Extrai ano olhando rótulos 'Ano', 'Ano/Modelo' etc., evitando capturar ano do rodapé."""
    if not text:
        return None
    patterns = [
        r"\bAno\s*/\s*Modelo\s*[:\-]?\s*(19\d{2}|20\d{2})\b",
        r"\bAno\s*do\s*modelo\s*[:\-]?\s*(19\d{2}|20\d{2})\b",
        r"\bAno\s*[:\-]?\s*(19\d{2}|20\d{2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                y = int(m.group(1))
                if 1900 <= y <= 2100:
                    return y
            except Exception:
                continue
    return None


def _extract_year_from_jsonld(html: str) -> Optional[int]:
    """Tenta extrair o ano via JSON-LD (Vehicle/Product) sem depender de regex global."""
    if not html:
        return None
    # pega todos os JSON-LD
    years: list[int] = []
    for m in re.finditer(r"<script[^>]+type=\"application/ld\+json\"[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        objs: list[dict] = []
        if isinstance(data, dict):
            objs = [data]
        elif isinstance(data, list):
            objs = [x for x in data if isinstance(x, dict)]

        def walk(obj: Any):
            if isinstance(obj, dict):
                # campos comuns
                for k in ("vehicleModelDate", "modelDate", "productionDate", "releaseDate", "datePublished", "dateCreated"):
                    v = obj.get(k)
                    if isinstance(v, (int, float)):
                        years.append(int(v))
                    elif isinstance(v, str):
                        mm = re.search(r"(19\d{2}|20\d{2})", v)
                        if mm:
                            years.append(int(mm.group(1)))
                # às vezes o ano vem dentro do nome
                name = obj.get("name")
                if isinstance(name, str):
                    mm = re.search(r"\b(19\d{2}|20\d{2})\b", name)
                    if mm:
                        years.append(int(mm.group(1)))
                # recursão leve
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for it in obj:
                    walk(it)

        for o in objs:
            walk(o)

    # filtra e escolhe o menor plausível quando há ruído do site (ex: ano atual).
    years = [y for y in years if 1900 <= y <= 2100]
    if not years:
        return None
    # Heurística: se há muitos anos e um deles é o ano atual do site (>= ano atual), preferir o menor.
    return min(years) if len(years) > 1 else years[0]


def _extract_image_from_jsonld(html: str) -> Optional[str]:
    if not html:
        return None
    for m in re.finditer(r"<script[^>]+type=\"application/ld\+json\"[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs: list[dict] = []
        if isinstance(data, dict):
            objs = [data]
        elif isinstance(data, list):
            objs = [x for x in data if isinstance(x, dict)]
        for o in objs:
            img = o.get("image")
            if isinstance(img, str) and img.startswith("http"):
                return img
            if isinstance(img, list):
                for it in img:
                    if isinstance(it, str) and it.startswith("http"):
                        return it
    return None
def _extract_best_year(text: str) -> int | None:
    ys: list[int] = []
    for m in re.finditer(r"\b(19\d{2}|20\d{2})\b", text or ""):
        try:
            y = int(m.group(1))
            if 1900 <= y <= 2100:
                ys.append(y)
        except Exception:
            continue
    return max(ys) if ys else None
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
    """Retorna um id estável para o anúncio.

    No GoGarage, o slug em /ads/<slug> é o identificador mais confiável.
    NÃO usamos heurísticas no texto (ex: '#6') porque isso colide com ruídos de UI
    e pode corromper registros (url de um carro com título de outro).
    """
    m = re.search(r"/ads/([^/?#]+)", url or "")
    return (m.group(1) if m else (url or "")).strip()


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
    return _clean_title_text(b2)[:160]


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
    """Tenta encontrar uma thumbnail no card.

    Muitos sites usam lazy-load (data-src) ou srcset; cobrimos esses casos.
    """
    try:
        el = card_el if card_el is not None else doc_el
        if el is None:
            return None

        # 1) src
        imgs = el.xpath(".//img[@src]/@src")
        for u in imgs:
            if isinstance(u, str) and u and u.startswith("http"):
                return u

        # 2) data-src / data-original
        for attr in ("data-src", "data-original", "data-lazy", "data-url"):
            imgs = el.xpath(f".//img[@{attr}]/@{attr}")
            for u in imgs:
                if isinstance(u, str) and u and u.startswith("http"):
                    return u

        # 3) srcset
        srcsets = el.xpath(".//img[@srcset]/@srcset")
        for ss in srcsets:
            u = _parse_srcset_first_url(ss)
            if u and u.startswith("http"):
                return u
    except Exception:
        return None
    return None




def fetch_details(url: str, *, ctx: ScrapeContext) -> Dict[str, Any]:
    """(Opcional) Completa campos essenciais de um anúncio.

    Importante: a página costuma conter o ano "atual" do site no <title> (ex: '— Go Garage 2026').
    NÃO podemos usar regex global pegando o maior ano do HTML.
    """
    html = fetch_html_with_browser_fallback(
        url,
        ctx=ctx,
        referer=GOGARAGE_BASE + "/",
        proxy=ctx.proxy_server,
        min_delay_ms=700,
        max_delay_ms=2000,
        wait_until="domcontentloaded",
    )

    title = ""
    thumb: Optional[str] = None

    try:
        from lxml import html as lhtml

        doc = lhtml.fromstring(html)

        # Título: preferir H1 (mais "limpo"), depois og:title, depois <title>
        h1 = doc.xpath("//h1//text()")
        if h1:
            title = " ".join([t.strip() for t in h1 if t and t.strip()]).strip()

        if not title:
            ogt = doc.xpath("//meta[@property='og:title']/@content")
            if ogt:
                title = ogt[0]

        if not title:
            tt = doc.xpath("//title/text()")
            if tt:
                title = tt[0]

        title = _strip_gogarage_suffix(title)

        # Imagem: JSON-LD > og:image > og:image:secure_url > imgs lazy/srcset
        thumb = _extract_image_from_jsonld(html)

        if not thumb:
            ogi = doc.xpath("//meta[@property='og:image']/@content") or doc.xpath("//meta[@property='og:image:secure_url']/@content")
            if ogi:
                thumb = ogi[0]

        if not thumb:
            # tenta imgs (inclui data-src/srcset)
            thumb = _guess_thumb(doc, doc)

        # às vezes a imagem vem em data-src de um carousel específico
        if not thumb:
            for attr in ("data-src", "data-original", "src"):
                imgs = doc.xpath(f"//img[@{attr}]/@{attr}")
                for u in imgs:
                    if isinstance(u, str) and u.startswith("http"):
                        thumb = u
                        break
                if thumb:
                    break

        if not thumb:
            srcsets = doc.xpath("//img[@srcset]/@srcset")
            for ss in srcsets:
                u = _parse_srcset_first_url(ss)
                if u and u.startswith("http"):
                    thumb = u
                    break

    except Exception:
        # mantém fallback abaixo
        title = _strip_gogarage_suffix(title)

    price = _guess_price(html)

    # Ano: preferir rótulos da página (Ano/Ano-Modelo). JSON-LD é bom, mas pode conter ruído do site.
    y_jsonld = _extract_year_from_jsonld(html)

    y_label = None
    try:
        from lxml import html as lhtml  # type: ignore
        _doc = lhtml.fromstring(html)
        y_label = _extract_year_from_labels(_doc.text_content() or "")
    except Exception:
        y_label = _extract_year_from_labels(html)

    year = y_label or y_jsonld

    if not year:
        # fallback: tenta achar no título limpo (sem 'Go Garage 2026')
        year = _extract_best_year(title)

    external_id = _guess_external_id(url, html)

    return {
        "external_id": external_id,
        "title": re.sub(r"\s+", " ", (title or "")).strip() or None,
        "thumbnail_url": thumb,
        "price": price,
        "year": year,
    }



def _extract_query_from_url(search_url: str) -> str:
    """Extrai o parâmetro q= do index.php (já decodificado)."""
    try:
        p = urlparse(search_url)
        qs = parse_qs(p.query or "")
        q = (qs.get("q") or [""])[0]
        return (q or "").strip()
    except Exception:
        return ""


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
            ctx=ctx,
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

    # Heurística: alguns modelos curtos (ex: "x3") precisam de marca na busca do GoGarage.
    q_hint = _extract_query_from_url(search_url)
    q_hint_l = q_hint.lower().strip()

    # GoGarage é 100% JS na listagem. Se forçado, tenta renderizar primeiro.
    if getattr(ctx, "force_browser", False) and settings.enable_playwright:
        try:
            html = _fetch_browser(search_url)
        except Exception:
            html = ""

    try:
        if not html:
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

    def _extract_urls_from_html(page_html: str) -> tuple[list[str], dict[str, Optional[str]]]:
        j = _extract_jsonld_itemlist(page_html)
        jmap = {u: n for u, n in j}
        u = [uu for uu, _ in j] if j else _extract_from_anchors(page_html)
        return u, jmap

    # 1) JSON-LD (se existir)
    urls, jsonld_map = _extract_urls_from_html(html)

    # Se veio HTML placeholder (JS) sem resultados, tenta renderizar via browser se permitido.
    if (
        (not urls)
        and settings.enable_playwright
        and any(s in html.lower() for s in ("carregando", "loading", "aguarde"))
    ):
        try:
            html = _fetch_browser(fetched_url)
            urls, jsonld_map = _extract_urls_from_html(html)
        except Exception:
            pass

    # 2) Fallback de busca com marca (ex: "bmw x3") quando a query é curta e o resultado é pobre.
    # Só roda quando o resultado veio pequeno (pra não duplicar custo em buscas normais).
    if len(urls) < 10 and q_hint_l:
        alt_qs: list[str] = []
        if q_hint_l in {"x1", "x2", "x3", "x4", "x5", "x6", "x7"}:
            alt_qs.append(f"bmw {q_hint_l}")

        for aq in alt_qs:
            if not aq:
                continue
            alt_url = f"{GOGARAGE_BASE}/index.php?q={quote_plus(aq)}"
            try:
                alt_html = _fetch_http(alt_url)
                alt_urls, alt_map = _extract_urls_from_html(alt_html)
                # merge mantendo ordem (e preservando jsonld_map quando disponível)
                for u in alt_urls:
                    if u not in urls:
                        urls.append(u)
                jsonld_map.update({k: v for k, v in alt_map.items() if k not in jsonld_map})
            except Exception:
                continue

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

    details_budget = 12  # limite de fetch_details por chamada (GoGarage cards são pobres)

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
        if _is_bad_title(title):
            title = ''
        price = _guess_price(blob)

        # Se existir ano no card/HTML, garante que ele apareça no título (ajuda filtros por ano).
        y = _extract_best_year(blob or '')
        if y and title and str(y) not in title:
            title = (title + f" {y}").strip()

        # GoGarage muitas vezes não coloca ano/preço no card. Se o ano não aparece, tenta details.
        has_year = bool(_extract_best_year(title) or y)

        # Se faltou coisa crítica ou ano, gasta "orçamento" com details (bem limitado)
        if details_budget > 0 and (not title or price is None or thumb is None or not has_year):
            try:
                d = fetch_details(url, ctx=ctx)
                details_budget -= 1
                external_id = str(d.get("external_id") or external_id)
                dt = (d.get("title") or "").strip()
                if dt and (not title or _is_bad_title(title)):
                    title = dt
                elif not title:
                    title = dt
                price = price or d.get("price")
                thumb = thumb or d.get("thumbnail_url")
                dy = d.get("year")
                if dy and title and str(dy) not in title:
                    title = (title + f" {dy}").strip()
            except Exception:
                details_budget -= 1

        
        # Não persiste lixo: se ainda não temos título útil, ignora o item (evita '6 Visto' no DB).
        if not title or _is_bad_title(title):
            continue

        out.append(
            {
                "source": "gogarage",
                "external_id": str(external_id),
                "title": _clean_title_text(title) or None,
                "url": url,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": None,
            }
        )

        if len(out) >= 60:
            break

    return finalize_listings("gogarage", out)


def urlparse_safe(url: str) -> str:
    """Retorna um fragmento estável do path para usar em xpath contains()."""
    m = re.search(r"/ads/[^/?#]+", url)
    return m.group(0) if m else url
