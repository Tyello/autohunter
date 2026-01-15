import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html
from app.scrapers.parsing import parse_brl_price


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


def scrape_mercadolivre(search_url: str) -> List[Dict[str, Any]]:
    """
    HTML público do Mercado Livre.
    """
    html = fetch_html(search_url)

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

        items.append({
            "source": "mercadolivre",
            "external_id": _extract_external_id_from_url(url),
            "title": title,
            "url": url,
            "thumbnail_url": thumb,
            "price": price,
            "currency": "BRL",
            "location": None,
        })

    # Se veio quase tudo sem title, cai pro POLYCARD (seu layout atual)
    empty_titles = sum(1 for i in items if not i.get("title"))
    if not items or empty_titles > (len(items) * 0.7):
        poly_items = _parse_polycard_items(html, limit=50)
        if poly_items:
            return poly_items

    return items
