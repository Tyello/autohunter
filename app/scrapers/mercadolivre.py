import re
import json
from typing import List, Dict, Any, Optional, Iterable
from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html, FetchBlocked
from app.scrapers.parsing import parse_brl_price
from app.sources.types import ScrapeContext

from app.core.settings import settings
from app.services.browser_fetcher import fetch_html_browser


def _fetch_html_ml(url: str, ctx: ScrapeContext, timeout: int = 25) -> str:
    proxy = getattr(ctx, "proxy_server", None)

    # 1) HTTP normal
    try:
        return fetch_html(
            url,
            timeout=timeout,
            referer="https://lista.mercadolivre.com.br/",
            proxy=proxy,
            min_delay_ms=250,
            max_delay_ms=900,
        )
    except FetchBlocked:
        pass

    # 2) curl_cffi (fingerprint melhor)
    try:
        from curl_cffi import requests as creq  # type: ignore

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://lista.mercadolivre.com.br/",
        }
        proxies = {"http": proxy, "https": proxy} if proxy else None

        r = creq.get(
            url,
            headers=headers,
            timeout=timeout,
            proxies=proxies,
            impersonate="chrome120",
            allow_redirects=True,
        )
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        pass

    # 3) fallback browser (se habilitado)
    if getattr(settings, "enable_playwright", False):
        res = fetch_html_browser(
            url,
            ctx=ctx,
            timeout_ms=timeout * 1000,
            wait_until="domcontentloaded",
            min_delay_ms=250,
            max_delay_ms=900,
        )
        return res.html

    # se chegou aqui, mantém sem mascarar: marca blocked mesmo
    raise FetchBlocked(403, url, reason="ml_403_all_strategies")


def _unescape_ml(s: str) -> str:
    """
    Mercado Livre costuma vir com escapes tipo \\u002F.
    """
    return (
        s.replace("\\u002F", "/")
         .replace("\\u003D", "=")
         .replace("\\u0026", "&")
         .replace("\\/", "/")
    )


def _extract_external_id_from_url(url: str) -> str:
    # captura MLB-1234567890 e normaliza para MLB1234567890
    m = re.search(r"(MLB)-(\d+)", url)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    # fallback: tenta MLB123 diretamente
    m2 = re.search(r"(MLB\d+)", url)
    if m2:
        return m2.group(1)
    return url


def _find_preloaded_state(html: str) -> Optional[dict]:
    """Parseia o JSON do script `__PRELOADED_STATE__` (quando existe).

    Observação: em páginas SPA (VIP / Motors), o preço muitas vezes só existe aqui.
    """
    try:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", id="__PRELOADED_STATE__")
        if not tag or not tag.string:
            return None
        return json.loads(tag.string)
    except Exception:
        return None


def _walk(obj: Any) -> Iterable[Any]:
    """Itera recursivamente por dicts/lists para buscas tolerantes a mudanças de layout."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _extract_price_from_vip_html(html: str) -> Optional[int]:
    """Extrai preço de uma página de anúncio (VIP) do Mercado Livre.

    Prioriza o JSON `__PRELOADED_STATE__`, com fallback para HTML visível.
    Retorna valor inteiro em BRL (ex.: 165590) ou None.
    """
    state = _find_preloaded_state(html)
    if state:
        # Caminho comum em VIP Motors: pageState.initialState.components.short_description[*].price.value
        try:
            comps = (
                state.get("pageState", {})
                     .get("initialState", {})
                     .get("components", {})
            )
            short_desc = comps.get("short_description") or []
            for comp in short_desc:
                if not isinstance(comp, dict):
                    continue
                # Alguns layouts têm id="price"/type="price".
                if comp.get("id") == "price" or comp.get("type") == "price":
                    p = comp.get("price") or {}
                    v = p.get("value")
                    if isinstance(v, (int, float)):
                        return int(v)
        except Exception:
            pass

        # Fallback ultra-tolerante: procura algum dict com {"type":"price", "price": {"value": ...}}
        for node in _walk(state):
            if not isinstance(node, dict):
                continue
            if node.get("type") == "price":
                p = node.get("price")
                if isinstance(p, dict) and isinstance(p.get("value"), (int, float)):
                    return int(p["value"])

            # Às vezes o bloco vem sem type, só "price": {"value": ...}
            p2 = node.get("price")
            if isinstance(p2, dict) and isinstance(p2.get("value"), (int, float)):
                return int(p2["value"])

    # Fallback HTML visível (quando SSR):
    try:
        soup = BeautifulSoup(html, "lxml")
        price_el = soup.select_one("span.andes-money-amount__fraction") or soup.select_one("span.price-tag-fraction")
        price_text = price_el.get_text(strip=True) if price_el else ""
        v = parse_brl_price(price_text)
        return int(v) if isinstance(v, (int, float)) else None
    except Exception:
        return None


def _parse_polycard_items(html: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Extrai itens do bloco embutido de POLYCARD.
    No seu HTML, os campos aparecem assim:
    - metadata.id: "MLB6160123242"
    - metadata.url: "carro.mercadolivre.com.br\\u002FMLB-6160123242-...."
    - components -> title.text
    - components -> price.current_price.value
    - pictures.pictures[0].id (para thumbnail)
    - components -> location.location.text (às vezes)
    """
    items: List[Dict[str, Any]] = []

    # Pega blocos de polycard de forma “good enough” (não é JSON válido completo, mas dá pra extrair)
    # Captura metadata.id, metadata.url e o trecho de components.
    pattern = re.compile(
        r'"polycard"\s*:\s*\{.*?"metadata"\s*:\s*\{.*?"id"\s*:\s*"(MLB\d+)".*?"url"\s*:\s*"(.*?)".*?\}\s*,'
        r'.*?"pictures"\s*:\s*\{.*?"pictures"\s*:\s*\[\s*\{\s*"id"\s*:\s*"(.*?)".*?\}\s*\].*?\}\s*,'
        r'.*?"components"\s*:\s*\[(.*?)\]\s*',
        re.DOTALL
    )

    for m in pattern.finditer(html):
        external_id = m.group(1)
        raw_url = _unescape_ml(m.group(2))
        pic_id = m.group(3)
        components = m.group(4)

        # title.text
        mt = re.search(r'"type"\s*:\s*"title".*?"text"\s*:\s*"(.*?)"', components, re.DOTALL)
        title = _unescape_ml(mt.group(1)) if mt else None

        # price.current_price.value
        mp = re.search(r'"type"\s*:\s*"price".*?"current_price"\s*:\s*\{.*?"value"\s*:\s*(\d+)', components, re.DOTALL)
        price = int(mp.group(1)) if mp else None

        # location.location.text (opcional)
        ml = re.search(r'"type"\s*:\s*"location".*?"text"\s*:\s*"(.*?)"', components, re.DOTALL)
        location = _unescape_ml(ml.group(1)) if ml else None

        # monta URL completa
        url = raw_url
        if url and not url.startswith("http"):
            url = "https://" + url.lstrip("/")

        # thumbnail: padrão comum que funciona bem com ID do picture
        # Ex.: "782273-MLB104686102403_012026"
        thumbnail_url = f"https://http2.mlstatic.com/D_Q_NP_2X_{pic_id}-E.webp" if pic_id else None

        items.append({
            "source": "mercadolivre",
            "external_id": external_id,
            "title": title,
            "url": url,
            "thumbnail_url": thumbnail_url,
            "price": price,
            "currency": "BRL",
            "location": location,
        })

        if len(items) >= limit:
            break

    return items


def scrape_mercadolivre(search_url: str, ctx: Optional[ScrapeContext] = None) -> List[Dict[str, Any]]:
    """
    HTML público do Mercado Livre.
    """
    # ctx é mantido por compatibilidade com o pipeline unificado (scrape(url, ctx)).
    # Mercado Livre não usa sessão sticky hoje.
    html = _fetch_html_ml(search_url, ctx, timeout=25)

    # 1) tentativa via HTML “clássico”
    soup = BeautifulSoup(html, "lxml")
    items: List[Dict[str, Any]] = []

    cards = soup.select("li.ui-search-layout__item")
    if not cards:
        cards = soup.select("div.ui-search-result__wrapper")

    for c in cards[:50]:
        a = c.select_one("a.ui-search-link") or c.select_one("a")
        if not a or not a.get("href"):
            continue

        url = a["href"].split("#")[0]
        title_el = c.select_one("h2.ui-search-item__title") or c.select_one("h2")
        title = title_el.get_text(strip=True) if title_el else None

        img = c.select_one("img")
        thumb = img.get("data-src") or img.get("src") if img else None

        price_el = c.select_one("span.andes-money-amount__fraction") or c.select_one("span.price-tag-fraction")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = parse_brl_price(price_text)

        external_id = _extract_external_id_from_url(url)

        items.append({
            "source": "mercadolivre",
            "external_id": external_id,
            "title": title,
            "url": url,
            "thumbnail_url": thumb,
            "price": price,
            "currency": "BRL",
            "location": None,
        })

    # Sempre tenta extrair POLYCARD (é o layout novo do ML), mas usa como:
    # - fallback (quando títulos somem)
    # - preenchimento de campos faltantes (quando só alguns cards vieram incompletos)
    poly_items = _parse_polycard_items(html, limit=50)
    poly_by_id = {p.get("external_id"): p for p in poly_items if p.get("external_id")}

    # 1) Se veio quase tudo sem title, retorna POLYCARD direto.
    empty_titles = sum(1 for i in items if not i.get("title"))
    if (not items) or (items and empty_titles > (len(items) * 0.7)):
        if poly_items:
            return poly_items

    # 2) Mescla POLYCARD para completar campos faltantes.
    for it in items:
        pid = it.get("external_id")
        p = poly_by_id.get(pid)
        if not p:
            continue
        # completa só o que estiver faltando
        for k in ("title", "thumbnail_url", "price", "location", "url"):
            if not it.get(k) and p.get(k):
                it[k] = p[k]

    # 3) Último fallback: se ainda faltar preço em alguns anúncios, busca a página VIP do anúncio
    # (capado para não virar N+1 sempre).
    missing_price = [i for i in items if not i.get("price") and i.get("url")]
    if missing_price:
        max_vip_fetch = 5
        for it in missing_price[:max_vip_fetch]:
            try:
                vip_html = _fetch_html_ml(it["url"], ctx, timeout=20)
                vip_price = _extract_price_from_vip_html(vip_html)
                if vip_price:
                    it["price"] = vip_price
            except Exception:
                # falhou: segue com price None
                pass

    return items
