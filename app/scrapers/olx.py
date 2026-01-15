from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.scrapers.base import fetch_html, FetchBlocked


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
    # No HTML que você mandou, paginação aparece como &o=1, &o=2 etc.:contentReference[oaicite:4]{index=4}
    q = quote_plus(query.strip())
    return f"https://www.olx.com.br/brasil?q={q}&o={page}"


def _parse_brl_price_to_decimal(text: str) -> Optional[Decimal]:
    if not text:
        return None
    # exemplos no HTML/JSON: "R$ 79.900", "R$ 75.900":contentReference[oaicite:5]{index=5}
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
    No HTML que você mandou, os itens aparecem com chaves como:
    - subject
    - priceValue / price
    - friendlyUrl
    - listId
    - images (com urls)
    Exemplo visível no dump: listId, friendlyUrl, priceValue, subject, images...:contentReference[oaicite:6]{index=6}
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


def scrape_olx(search_url: str) -> list[OlxItem]:
    html = fetch_html(search_url)

    next_data = _extract_next_data_json(html)
    if not next_data:
        # fallback ultra simples: tentar card HTML
        return _fallback_parse_from_cards(html)

    items = _extract_items_from_next_data(next_data)
    return items


def _fallback_parse_from_cards(html: str) -> list[OlxItem]:
    """
    Fallback se __NEXT_DATA__ não estiver disponível.
    No HTML que você mandou dá pra ver card com imagem e estrutura de media.:contentReference[oaicite:7]{index=7}
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[OlxItem] = []

    # tenta achar links de cards
    for a in soup.select('a[data-testid="adcard-link"]'):
        href = a.get("href")
        if not href:
            continue

        title = (a.get_text(" ", strip=True) or "").strip()

        # tenta price em elementos próximos
        price = None
        price_text = None
        container = a.find_parent()
        if container:
            price_el = container.select_one(".olx-adcard__price")
            if price_el:
                price_text = price_el.get_text(strip=True)
                price = _parse_brl_price_to_decimal(price_text)

        # tenta achar imagem
        img = None
        if container:
            img_el = container.select_one("img")
            if img_el:
                img = img_el.get("src")

        # external_id: tenta extrair do final da url se houver número
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

    # dedupe
    seen = set()
    unique = []
    for it in out:
        if it.external_id in seen:
            continue
        seen.add(it.external_id)
        unique.append(it)
    return unique
