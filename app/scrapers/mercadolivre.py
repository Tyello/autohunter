import re
import json
from typing import List, Dict, Any, Optional, Iterable
from urllib.parse import urlparse, urlunparse, parse_qs, unquote

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html, FetchBlocked
from app.scrapers.fetching import fetch_html_with_browser_fallback
from app.services.browser_fetcher import fetch_html_browser, reset_browser_state_for_source
from app.scrapers.parsing import parse_brl_price
from app.sources.types import ScrapeContext

from app.core.settings import settings


def _fetch_html_ml(url: str, ctx: ScrapeContext, timeout: int = 25) -> str:
    proxy = getattr(ctx, "proxy_server", None)

    # 1) HTTP normal/hardened (with auto cookies from storage_state in base.fetch_html).
    try:
        return fetch_html(
            url,
            ctx=ctx,
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
            "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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
            impersonate=getattr(settings, "ml_impersonate", None) or "chrome120",
            allow_redirects=True,
        )
        if r.status_code == 200 and r.text:
            return r.text
        if int(getattr(r, "status_code", 0) or 0) in (403, 429):
            raise FetchBlocked(int(r.status_code), url, reason="http_status")
    except FetchBlocked:
        pass
    except Exception:
        pass

    # 3) Hybrid ideal: browser warmup -> retry HTTP once -> browser HTML as last resort.
    if settings.enable_playwright and getattr(ctx, "browser_fallback_enabled", False):
        return fetch_html_with_browser_fallback(
            url,
            ctx=ctx,
            timeout=timeout,
            referer="https://lista.mercadolivre.com.br/",
            proxy=proxy,
            min_delay_ms=250,
            max_delay_ms=900,
            wait_until="domcontentloaded",
            timeout_ms=timeout * 1000,
            browser_min_delay_ms=250,
            browser_max_delay_ms=900,
            allow_browser_fallback=True,
        )

    raise FetchBlocked(403, url, reason="ml_403_all_strategies")


def _is_ml_security_or_captcha_page(html: str, final_url: str = "") -> bool:
    lower_html = (html or "").lower()
    lower_url = (final_url or "").lower()
    return any(marker in lower_url for marker in ("/captcha/wall",)) or any(
        marker in lower_html
        for marker in (
            "seguridad — mercado libre",
            "seguridad - mercado libre",
            "/captcha/wall",
            "account-verification",
            "captcha",
            "hcaptcha",
            "g-recaptcha",
            "are you human",
        )
    )


def _is_ml_shell_without_results(html: str) -> bool:
    """Detecta respostas-shell do ML sem cards úteis de veículo.

    Heurística conservadora para ativar fallback browser somente quando necessário.
    """
    if not html or not html.strip():
        return False

    lower_html = html.lower()
    content_length = len(html)

    if any(marker in lower_html for marker in ("captcha", "acesso negado", "access denied", "403 forbidden")):
        return False

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = (title_match.group(1).strip() if title_match else "")
    is_ml_title = "mercado livre" in title.lower() or "| mercado livre" in title.lower()
    if not is_ml_title:
        return False

    li_cards = len(re.findall(r"<li[^>]+class=[\"'][^\"']*ui-search-layout__item", html, re.IGNORECASE))
    mlb_links = len(re.findall(r"href=[\"'][^\"']*MLB-", html, re.IGNORECASE))
    vehicle_links = len(re.findall(r"carro\.mercadolivre\.com\.br", lower_html))

    if li_cards > 0 or mlb_links > 0 or vehicle_links > 2:
        return False

    has_canonical = bool(re.search(r"<link[^>]+rel=[\"']canonical[\"']", html, re.IGNORECASE))
    has_og_url = bool(re.search(r"<meta[^>]+property=[\"']og:url[\"']", html, re.IGNORECASE))

    return content_length < 50_000 or not (has_canonical or has_og_url)


def _fetch_ml_search_with_shell_fallback(url: str, ctx: Optional[ScrapeContext], timeout: int = 25) -> str:
    """Busca HTML da listagem ML priorizando HTTP e fallback browser networkidle."""
    html = _fetch_html_ml(url, ctx, timeout=timeout)
    if not _is_ml_shell_without_results(html):
        return html

    if not (settings.enable_playwright and ctx and getattr(ctx, "browser_fallback_enabled", False)):
        return html

    def _browser_fetch_once() -> tuple[str, str]:
        browser_res = fetch_html_browser(
            url,
            ctx=ctx,
            timeout_ms=timeout * 1000,
            wait_until="networkidle",
            min_delay_ms=250,
            max_delay_ms=900,
            block_resources=False,
        )
        return (browser_res.html or "", getattr(browser_res, "final_url", "") or "")

    browser_html, browser_final_url = _browser_fetch_once()
    if _is_ml_security_or_captcha_page(browser_html, browser_final_url):
        raise FetchBlocked(200, url, reason="ml_security_or_captcha_page")

    if not _is_ml_shell_without_results(browser_html):
        return browser_html

    reset_browser_state_for_source("mercadolivre", ctx, block_resources=False, clear_storage=True)
    retry_html, retry_final_url = _browser_fetch_once()
    if _is_ml_security_or_captcha_page(retry_html, retry_final_url):
        raise FetchBlocked(200, url, reason="ml_security_or_captcha_page")
    if _is_ml_shell_without_results(retry_html):
        raise FetchBlocked(200, url, reason="ml_shell_without_results")
    return retry_html


def _unescape_ml(s: str) -> str:
    """
    Mercado Livre costuma vir com escapes no HTML, por exemplo:
      "\u002F" (sequência literal)
      "\\/" (slash escapado)
    """
    if not s:
        return ""
    s = (s or "")

    # sequências literais comuns
    s = (
        s.replace("\\u002F", "/")
         .replace("\\u003D", "=")
         .replace("\\u0026", "&")
         .replace("\\/", "/")
    )

    # fallback genérico: decodifica qualquer \uXXXX remanescente
    if re.search(r"\\u[0-9a-fA-F]{4}", s):
        try:
            s = s.encode("utf-8", "ignore").decode("unicode_escape")
        except Exception:
            pass
        s = s.replace("\\/", "/")

    return s


def _is_tracking_url(url: str) -> bool:
    """Detecta URLs de tracking patrocinado (click*.mercadolivre.com.br/brand_ads/...)."""
    if not url:
        return False
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").lower()
        if "mercadolivre.com.br" not in host:
            return False
        if host.startswith("click") or host.startswith("clk"):
            return True
        if "brand_ads/clicks" in path:
            return True
    except Exception:
        pass
    return False


def _strip_query_fragment(url: str) -> str:
    """Remove ?query e #fragment para evitar URLs gigantes e tokens falsos no matching."""
    if not url:
        return ""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return url.split("#")[0].split("?")[0]

# Apenas anúncios do vertical de veículos (carros/caminhonetes) devem entrar no AutoHunter.
# Itens de "produto" (peças/acessórios) podem aparecer como patrocinados na listagem e devem ser descartados.
_ALLOWED_VEHICLE_HOSTS = {"carro.mercadolivre.com.br"}


_ML_VEHICLE_HOST = "carro.mercadolivre.com.br"
_ML_LIST_HOST = "lista.mercadolivre.com.br"
_ML_VEHICLE_LIST_PREFIX = "/veiculos/carros-caminhonetes/"


def _ensure_vehicle_search_url(url: str) -> str:
    """Normaliza a busca para o vertical de veículos.

    O ML canonicaliza buscas de veículos em:
      https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/<slug>

    Historicamente, URLs no host `carro.mercadolivre.com.br/<slug>` redirecionam/canonicalizam
    para `lista.*`, e o guardrail antigo interpretava isso como "saiu do vertical" (found=0).

    Aqui normalizamos a URL para o vertical correto e removemos query/fragment.
    """
    url = (url or "").strip()
    if not url:
        return url

    # completa esquema
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")

    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "")

        # Se já é uma busca canônica de veículos, só limpa query/fragment.
        if host == _ML_LIST_HOST and (path or "").lower().startswith(_ML_VEHICLE_LIST_PREFIX):
            p = p._replace(query="", fragment="", params="")
            return urlunparse(p)

        # Se parece uma página de anúncio (VIP) por MLB-XXXX, não converte para busca.
        if re.search(r"/MLB-\d+", path, re.IGNORECASE) or re.search(r"\bMLB-\d+\b", path, re.IGNORECASE):
            p = p._replace(query="", fragment="", params="")
            return urlunparse(p)

        # Para qualquer URL do ML, reescreve para o vertical de veículos em lista.*
        if "mercadolivre.com.br" in host:
            slug = path.strip("/")
            if slug.lower().startswith(_ML_VEHICLE_LIST_PREFIX.strip("/")):
                # evita duplicar prefix
                new_path = "/" + slug
            else:
                new_path = _ML_VEHICLE_LIST_PREFIX + slug

            p = p._replace(
                scheme="https",
                netloc=_ML_LIST_HOST,
                path=new_path,
                query="",
                fragment="",
                params="",
            )
            return urlunparse(p)
    except Exception:
        pass

    return url

def _is_vehicle_host(url: str) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).netloc or "").lower()
        return host in _ALLOWED_VEHICLE_HOSTS
    except Exception:
        return False


def _is_vehicle_search_vertical(url: str) -> bool:
    """Valida se a URL (canonical/og:url) ainda está no vertical de veículos.

    Aceita:
    - lista.mercadolivre.com.br/veiculos/carros-caminhonetes/...
    - carro.mercadolivre.com.br/<slug> (busca) — mas NÃO VIP (MLB-...)
    """
    if not url:
        return False
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").lower()

        if host == _ML_LIST_HOST and path.startswith(_ML_VEHICLE_LIST_PREFIX):
            return True

        if host == _ML_VEHICLE_HOST:
            # VIP: carro.mercadolivre.com.br/MLB-xxxx
            if re.search(r"/mlb-\d+", path, re.IGNORECASE):
                return False
            return True
    except Exception:
        pass
    return False



def _extract_canonical_or_og_url(html: str) -> str:
    """Tenta descobrir a URL efetiva (pós-redirect) via canonical/og:url."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        link = soup.find("link", rel="canonical")
        href = (link.get("href") if link else "") or ""
        if not href:
            meta = soup.find("meta", attrs={"property": "og:url"})
            href = (meta.get("content") if meta else "") or ""

        href = _unescape_ml((href or "").strip())
        if href.startswith("//"):
            href = "https:" + href
        if href and not href.startswith("http") and "mercadolivre.com.br" in href:
            href = "https://" + href.lstrip("/")
        return href
    except Exception:
        return ""


def _left_vehicle_vertical(requested_url: str, html: str) -> bool:
    """True quando a resposta indica que o ML saiu do vertical de veículos.

    Ex.: sem anúncios do termo, o ML pode redirecionar/sugerir itens de outras categorias.
    """
    canonical = _extract_canonical_or_og_url(html)

    # Se a canonical existe e NÃO é do vertical de veículos, aborta.
    if canonical and not _is_vehicle_search_vertical(canonical):
        return True

    return False


# Heurística anti-peças: mesmo dentro do host de veículos, podem aparecer itens de produto.
# Preferimos falsos negativos (0 resultados) a notificar "cabo", "pistão", etc.
_PART_KEYWORDS = {
    "cabo", "embreagem", "pistao", "pistão", "anel", "biela", "correia", "correia dentada",
    "filtro", "vela", "bobina", "amortecedor", "pastilha", "disco", "radiador",
    "farol", "lanterna", "retrovisor", "parachoque", "para-choque", "sensor",
    "bomba", "rolamento", "mangueira", "tampa", "retentor", "escapamento",
    "ponteira", "alternador", "arranque", "motor de arranque", "compressor",
    "condensador", "evaporador", "mola", "molas", "suspensao", "suspensão",
}

_VEHICLE_POSITIVE_TERMS = {
    "km", "quilometr", "ano", "manual", "automático", "automatico", "câmbio", "cambio",
    "gasolina", "etanol", "flex", "diesel", "híbrido", "hibrido", "elétrico", "eletrico",
    "hatch", "sedan", "cupê", "cupe", "suv", "picape", "pickup", "caminhonete", "perua", "wagon",
}


def _vehicle_relevance_score(text: str, title: str = "") -> int:
    """Score simples para decidir se um card parece anúncio de veículo.

    >=2: aceita
    <2: descarta (provável peça/acessório ou sugestão fora do escopo)
    """
    blob = (text or "").lower()
    ttitle = (title or "").lower()

    score = 0

    # sinais fortes: ano (4 dígitos) e km
    if re.search(r"\b(19\d{2}|20\d{2})\b", blob):
        score += 2
    if re.search(r"\b\d{1,3}(?:[\.,]\d{3})+\s*km\b|\b\d+\s*km\b", blob):
        score += 1

    # sinais moderados
    if any(term in blob for term in _VEHICLE_POSITIVE_TERMS):
        score += 1

    # penalidades (focadas no título)
    if any(k in ttitle for k in _PART_KEYWORDS):
        score -= 2

    # padrões muito comuns de peças
    if re.search(r"\b(kit|jg\.?|jogo)\b", ttitle):
        score -= 1

    return score


def _extract_tracking_destination(tracking_url: str) -> str:
    """Extrai o destino real de uma URL de tracking (click*/brand_ads).

    Se não for possível resolver com segurança, retorna string vazia.
    """
    if not tracking_url:
        return ""
    try:
        p = urlparse(tracking_url)
        qs = parse_qs(p.query or "")
        dest = ""
        for key in ("url", "u", "adurl", "dest", "redirect"):
            v = qs.get(key)
            if v:
                dest = v[0]
                break
        if not dest:
            return ""

        dest = _unescape_ml(dest).strip()

        # Algumas URLs vêm com múltiplas camadas de encoding.
        for _ in range(3):
            decoded = unquote(dest)
            if decoded == dest:
                break
            dest = decoded

        dest = dest.strip()
        if not dest:
            return ""

        if dest.startswith("//"):
            dest = "https:" + dest
        elif dest.startswith("/"):
            dest = "https://www.mercadolivre.com.br" + dest
        elif not dest.startswith("http"):
            # Ex.: "carro.mercadolivre.com.br/MLB-....-_JM"
            if "mercadolivre.com.br" in dest:
                dest = "https://" + dest.lstrip("/")
            else:
                return ""

        return dest
    except Exception:
        return ""



def _canonical_url_from_external_id(external_id: str) -> str:
    """Gera URL canônica curta a partir do MLB id (ex.: MLB6160123242)."""
    m = re.match(r"^MLB(\d+)$", (external_id or "").upper())
    if not m:
        return ""
    # Para veículos, este padrão é estável e bem curto.
    return f"https://carro.mercadolivre.com.br/MLB-{m.group(1)}-_JM"


def _normalize_ml_url(url: str, external_id: str) -> str:
    """Normaliza URL:
    - completa esquema quando vier sem
    - remove query/fragment
    - se for tracking (click*/brand_ads), tenta extrair o destino real

    Importante: NÃO assumimos que tracking = veículo.
    """
    url = (url or "").strip()
    if not url:
        return ""

    # completa esquema
    if url.startswith("//"):
        url = "https:" + url
    if url and not url.startswith("http"):
        if url.startswith("/"):
            url = "https://www.mercadolivre.com.br" + url
        else:
            url = "https://" + url.lstrip("/")

    if _is_tracking_url(url):
        dest = _extract_tracking_destination(url)
        if dest:
            return _strip_query_fragment(dest)
        # Se não conseguimos extrair o destino, mas já temos o MLB id,
        # devolve uma URL canônica curta e estável (melhor para dedupe e matching).
        canonical = _canonical_url_from_external_id(external_id)
        if canonical:
            return canonical
        return _strip_query_fragment(url)

    return _strip_query_fragment(url)


def _extract_external_id_from_url(url: str) -> str:
    # captura MLB-1234567890 e normaliza para MLB1234567890
    m = re.search(r"(MLB)-(\d+)", url or "")
    if m:
        return f"{m.group(1)}{m.group(2)}"
    # fallback: tenta MLB123 diretamente
    m2 = re.search(r"(MLB\d+)", url or "")
    if m2:
        return m2.group(1)
    return ""


def _extract_external_id_from_text(text: str) -> str:
    """Tenta achar MLB id em qualquer pedaço do card (HTML/atributos)."""
    if not text:
        return ""
    m = re.search(r"(MLB)-(\d{6,})", text)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    m2 = re.search(r"(MLB\d{6,})", text)
    if m2:
        return m2.group(1)
    return ""


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
        return int(v) if v is not None else None
    except Exception:
        return None


def _parse_polycard_items(html: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Extrai itens do bloco embutido de POLYCARD.
    No seu HTML, os campos aparecem assim:
    - metadata.id: "MLB6160123242"
    - metadata.url: "carro.mercadolivre.com.br\u002FMLB-6160123242-...."
    - components -> title.text
    - components -> price.current_price.value
    - pictures.pictures[0].id (para thumbnail)
    - components -> location.location.text (às vezes)
    """
    items: List[Dict[str, Any]] = []

    pattern = re.compile(
        r'"polycard"\s*:\s*\{.*?"metadata"\s*:\s*\{.*?"id"\s*:\s*"(MLB\d+)".*?"url"\s*:\s*"(.*?)".*?\}\s*,'
        r'.*?"pictures"\s*:\s*\{.*?"pictures"\s*:\s*\[\s*\{\s*"id"\s*:\s*"(.*?)".*?\}\s*\].*?\}\s*,'
        r'.*?"components"\s*:\s*\[(.*?)\]\s*',
        re.DOTALL
    )

    for m in pattern.finditer(html or ""):
        external_id = m.group(1)
        raw_url = _unescape_ml(m.group(2))
        pic_id = m.group(3)
        components = m.group(4)

        mt = re.search(r'"type"\s*:\s*"title".*?"text"\s*:\s*"(.*?)"', components, re.DOTALL)
        title = _unescape_ml(mt.group(1)) if mt else None

        mp = re.search(r'"type"\s*:\s*"price".*?"current_price"\s*:\s*\{.*?"value"\s*:\s*(\d+)', components, re.DOTALL)
        price = int(mp.group(1)) if mp else None

        mlc = re.search(r'"type"\s*:\s*"location".*?"text"\s*:\s*"(.*?)"', components, re.DOTALL)
        location = _unescape_ml(mlc.group(1)) if mlc else None

        url = raw_url
        if url and not url.startswith("http"):
            url = "https://" + url.lstrip("/")

        url = _normalize_ml_url(url, external_id)

        # Mantém apenas anúncios do vertical de veículos.
        if not _is_vehicle_host(url):
            continue

        # Extra: mesmo no host 'carro.*', o ML pode sugerir peças/acessórios quando não há resultados.
        blob = f"{title or ''} {_unescape_ml(components)}"
        if _vehicle_relevance_score(blob, title or "") < 2:
            continue


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

    # Trava a busca no vertical de veículos.
    search_url = _ensure_vehicle_search_url(search_url)

    html = _fetch_ml_search_with_shell_fallback(search_url, ctx, timeout=25)

    # Se o ML saiu do vertical (redirect/canonical fora de carro.*), não ingere nada.
    if _left_vehicle_vertical(search_url, html):
        return []


    # POLYCARD é o layout mais confiável hoje; preferimos ele como base
    poly_items = _parse_polycard_items(html, limit=50)
    poly_by_id = {p.get("external_id"): p for p in poly_items if p.get("external_id")}

    soup = BeautifulSoup(html, "lxml")
    items: List[Dict[str, Any]] = []

    cards = soup.select("li.ui-search-layout__item")
    if not cards:
        cards = soup.select("div.ui-search-result__wrapper")

    for c in cards[:50]:
        a = c.select_one("a.ui-search-link") or c.select_one("a")
        if not a or not a.get("href"):
            continue

        raw_url = a["href"]

        # Se for tracking patrocinado, tentamos recuperar o MLB id no HTML do card.
        card_html = str(c)
        external_id = _extract_external_id_from_url(raw_url)
        if not external_id and _is_tracking_url(raw_url):
            external_id = _extract_external_id_from_text(card_html)

        if not external_id:
            # Sem MLB id não tem dedupe/match; não vale ingerir.
            continue

        url = _normalize_ml_url(raw_url, external_id)

        # Mantém apenas anúncios do vertical de veículos.
        if not _is_vehicle_host(url):
            continue

        title_el = c.select_one("h2.ui-search-item__title") or c.select_one("h2")
        title = title_el.get_text(strip=True) if title_el else None

        # Heurística anti-peças: descarta cards que não parecem anúncio de veículo.
        blob = f"{title or ''} {card_html}"
        if _vehicle_relevance_score(blob, title or "") < 2:
            continue


        img = c.select_one("img")
        thumb = img.get("data-src") or img.get("src") if img else None
        thumb = _strip_query_fragment(thumb) if thumb else None

        price_el = c.select_one("span.andes-money-amount__fraction") or c.select_one("span.price-tag-fraction")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = parse_brl_price(price_text)

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

    # Se POLYCARD existir, ele vira a base (evita URL de tracking e layout instável).
    if poly_items:
        base: List[Dict[str, Any]] = list(poly_items)
        base_by_id = {b.get("external_id"): b for b in base if b.get("external_id")}

        for it in items:
            pid = it.get("external_id")
            if not pid:
                continue
            if pid not in base_by_id:
                base.append(it)
                base_by_id[pid] = it
            else:
                # completa campos faltantes no polycard
                cur = base_by_id[pid]
                for k in ("title", "thumbnail_url", "price", "location", "url"):
                    if not cur.get(k) and it.get(k):
                        cur[k] = it[k]
        items = base
    else:
        # Sem polycard: tenta mesclar qualquer coisa que vier (nada a fazer).
        pass

    # Último fallback: se ainda faltar preço em alguns anúncios, busca a página VIP (capado)
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
                pass

    return items
