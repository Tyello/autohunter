from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html


@dataclass
class ChavesNaMaoItem:
    external_id: str
    title: str
    url: str
    thumbnail_url: Optional[str]
    price: Optional[Decimal]
    currency: str = "BRL"
    location: Optional[str] = None


def build_chavesnamao_search_url(query: str, page: int = 1) -> str:
    """
    O site tem páginas SSR bem mais "semânticas" por modelo, ex:
    - https://www.chavesnamao.com.br/carros/brasil/honda-civic/

    O parâmetro `?q=` na listagem nacional existe, mas na prática pode ser ignorado e
    acabar trazendo o topo do Brasil (luxo, etc.).

    Para o MVP, aplicamos um "resolver" simples que tenta mapear o termo para um slug
    de modelo (ex: "civic" -> "honda-civic"). Quando não houver match, cai no fallback
    `carros-usados/brasil/?q=...`.
    """

    raw = " ".join(query.lower().split())

    # Resolver mínimo (extensível). A ideia é priorizar páginas de modelo SSR.
    slug = None
    if "civic" in raw:
        slug = "honda-civic"

    if slug:
        url = f"https://www.chavesnamao.com.br/carros/brasil/{slug}/"
    else:
        q = quote_plus(query.strip())
        url = f"https://www.chavesnamao.com.br/carros-usados/brasil/?q={q}"

    if page and page > 1:
        sep = "&" if "?" in url else "?"
        url += f"{sep}pagina={page}"
    return url


_RE_PRICE = re.compile(r"R\$\s*([\d\.]+)")


def _parse_brl_price(text: str) -> Optional[Decimal]:
    if not text:
        return None
    m = _RE_PRICE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(".", "")
    try:
        return Decimal(raw)
    except Exception:
        return None


def _extract_location_from_anchor_text(text: str) -> Optional[str]:
    # exemplos visíveis no próprio texto do link: "Curitiba , PR" / "São Paulo , SP"
    m = re.search(r"([A-Za-zÀ-ÿ\s]+)\s*,\s*([A-Z]{2})\b", text)
    if not m:
        return None
    city = " ".join(m.group(1).split())
    uf = m.group(2)
    return f"{city}-{uf}" if city else uf


def scrape_chavesnamao(search_url: str, limit: int = 50) -> list[dict]:
    html = fetch_html(search_url)
    soup = BeautifulSoup(html, "html.parser")

    out: list[dict] = []

    # A página lista os anúncios como <a> com o título + preço no texto.
    # Nos dumps do site, os links vêm logo depois do H1.
    # Regra de ouro pra não puxar "similares"/conteúdo editorial:
    # anúncios têm URL com /carro/.../id-<digits>/
    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue

        if "/id-" not in href:
            continue

        text = (a.get_text(" ", strip=True) or "").strip()
        if "R$" not in text:
            continue

        url = href
        if url.startswith("/"):
            url = "https://www.chavesnamao.com.br" + url

        # external_id: tenta extrair último segmento numérico; senão usa a URL
        m = re.search(r"(\d{6,})", url)
        external_id = m.group(1) if m else url

        price = _parse_brl_price(text)
        location = _extract_location_from_anchor_text(text)

        # thumb: algumas páginas trazem <img> dentro do <a>
        thumb = None
        img = a.select_one("img")
        if img:
            thumb = img.get("src") or img.get("data-src")

        out.append(
            {
                "source": "chavesnamao",
                "external_id": str(external_id),
                "title": text.split("R$")[0].strip() or None,
                "url": url,
                "thumbnail_url": thumb,
                "price": price,
                "currency": "BRL",
                "location": location,
            }
        )

        if len(out) >= limit:
            break

    # dedupe interno
    seen = set()
    uniq: list[dict] = []
    for it in out:
        key = (it.get("source"), it.get("external_id"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    return uniq
