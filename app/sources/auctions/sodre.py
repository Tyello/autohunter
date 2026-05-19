from __future__ import annotations

import hashlib
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.parsing import parse_datetime_br, parse_money_br, parse_year_from_title

SOURCE_KEY = "sodre_auctions"
DEFAULT_LISTING_URL = "https://www.sodresantoro.com.br/"
ALLOWED_DOMAINS = {"sodresantoro.com.br", "www.sodresantoro.com.br", "leilao.sodresantoro.com.br"}
VALID_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
}

_LAST_REASON: str | None = None


def get_last_reason() -> str | None:
    return _LAST_REASON


def validate_auction_source_url(url: str, allowed_domains: Iterable[str]) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {d.lower() for d in allowed_domains}


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1).strip() if m else None


def normalize_sodre_status(raw: str | None) -> str:
    text = (raw or "").lower()
    if "ao vivo" in text:
        return "live"
    if "aberto" in text:
        return "open"
    if "encerrad" in text:
        return "ended"
    if "em breve" in text or "futuro" in text or "agendad" in text:
        return "scheduled"
    return "unknown"


def parse_sodre_location(raw: str | None) -> tuple[str | None, str | None, str | None]:
    clean = _strip_html(raw or "").strip(" :-,")
    if not clean:
        return None, None, None
    m = re.search(r"^(.+?)\s*(?:/|,|-)\s*([A-Za-z]{2})$", clean)
    if not m:
        return clean, None, clean
    city = m.group(1).strip()
    state = m.group(2).upper()
    return city, (state if state in VALID_UFS else None), clean


def infer_sodre_item_type(*texts: str | None) -> str:
    text = " ".join(x for x in texts if x).lower()
    if "moto" in text:
        return "motorcycle"
    if any(k in text for k in ("caminh", "ônibus", "onibus", "pesad", "frota")):
        return "truck"
    if any(k in text for k in ("carro", "veículo", "veiculo", "veículos", "veiculos", "leves")):
        return "car"
    return "other"


def extract_sodre_external_id(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    nums = re.findall(r"\d{2,}", path)
    if nums:
        return nums[-1]
    if slug:
        return slug.lower()
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def filter_sodre_images(urls: list[str], listing_url: str) -> list[str]:
    out: list[str] = []
    for raw in urls:
        abs_url = urljoin(listing_url, raw)
        low = abs_url.lower()
        if any(x in low for x in ("logo", "icon", "sprite", "banner", "institucional")):
            continue
        if not re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", low):
            continue
        out.append(abs_url)
    return list(dict.fromkeys(out))




def _extract_sodre_candidate_blocks(html: str) -> list[str]:
    class_blocks = [
        blk
        for _, blk in re.findall(
            r'<(article|div)[^>]*class="[^"]*(?:card|lot|item|leilao|leilão)[^"]*"[^>]*>(.*?)</\1>',
            html,
            flags=re.I | re.S,
        )
    ]
    if class_blocks:
        return class_blocks

    keywords = r"lote|lotes|leilao|leilão|anuncio|anúncio|veiculo|veículo|veiculo-usado|carro|moto|caminhao|caminhão|onibus|ônibus"
    anchors = list(re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=re.I | re.S))
    blocks: list[str] = []
    seen_href: set[str] = set()

    for a in anchors:
        href = (a.group(1) or "").strip()
        anchor_text = _strip_html(a.group(2) or "")
        blob = f"{href} {anchor_text}".lower()
        if not re.search(keywords, blob, flags=re.I):
            continue
        if href in seen_href:
            continue
        seen_href.add(href)
        start = max(0, a.start() - 2000)
        end = min(len(html), a.end() + 2000)
        blocks.append(html[start:end])

    return blocks

def parse_sodre_listing_html(html: str, limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    cards = _extract_sodre_candidate_blocks(html)
    lots: list[NormalizedAuctionLot] = []
    seen_keys: set[str] = set()
    for card in cards:
        href = _first_group(r'href=["\']([^"\']+)["\']', card)
        if not href:
            continue
        url = urljoin(listing_url, href)
        ext_id = extract_sodre_external_id(url)
        if not ext_id:
            continue
        dedupe_key = f"{url}|{ext_id}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        title = _strip_html(_first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card) or "") or None
        if not title:
            title = _strip_html(_first_group(r">\s*([^<]{6,120})\s*</a>", card) or "") or None
        full_text = _strip_html(card)
        category = _first_group(r"(?:categoria|leilão|leilao)\s*: ?\s*([^\n<|]+)", card)
        raw_status = _first_group(r"(?:status\s*:?)\s*(Ao vivo|Aberto(?:s)?|Encerrado(?:s)?|Em breve|Futuro|Agendado)", card) or _first_group(r"\b(Ao vivo|Aberto(?:s)?|Encerrado(?:s)?|Em breve|Futuro|Agendado)\b", card)
        raw_location = _first_group(r"(?:Local|Cidade)\s*: ?\s*([^<\n]+)", card) or _first_group(r"([A-Za-zÀ-ÿ\s]+(?:/|,|-)\s*[A-Za-z]{2})", full_text)
        city, state, location = parse_sodre_location(raw_location)
        initial_raw = _first_group(r"(?:Lance\s*inicial|Valor\s*inicial|Lance\s*m[ií]nimo|Avaliaç[aã]o)\s*: ?\s*(R\$\s*[0-9.]+,[0-9]{2})", card)
        current_raw = _first_group(r"(?:Lance\s*atual|Maior\s*lance|Valor\s*atual)\s*: ?\s*(R\$\s*[0-9.]+,[0-9]{2})", card)
        start_raw = _first_group(r"(?:In[ií]cio|Data\s*do\s*leil[aã]o|Abertura|Ao vivo em|Data/hora do evento)\s*: ?\s*([^<\n]+)", card)
        end_raw = _first_group(r"(?:Encerramento|Encerra|Fim|T[eé]rmino|Data/hora de encerramento)\s*: ?\s*([^<\n]+)", card)
        lot_number = _first_group(r"Lote\s*: ?\s*(\d+)", card) or _first_group(r"\bLote\s+(\d+)\b", card)

        images = filter_sodre_images(re.findall(r"<(?:img|source)[^>]+(?:src|data-src)=[\"']([^\"']+)[\"']", card, flags=re.I), listing_url)
        auction_start_at = parse_datetime_br(start_raw)
        auction_end_at = parse_datetime_br(end_raw)

        extras = {
            "raw_status": raw_status,
            "raw_location": location,
            "source_category": _strip_html(category or "") or None,
            "listing_kind": "auction_lot",
            "event_title": title,
            "auction_date": start_raw,
            "end_date": end_raw,
        }
        make = (title.split()[0] if title else None)
        lots.append(NormalizedAuctionLot(
            source=SOURCE_KEY,
            external_id=ext_id,
            title=title,
            url=url,
            lot_number=lot_number,
            item_type=infer_sodre_item_type(title, category, full_text),
            make=make,
            year=parse_year_from_title(title),
            city=city,
            state=state,
            location=location,
            initial_bid=parse_money_br(initial_raw),
            current_bid=parse_money_br(current_raw),
            status=normalize_sodre_status(raw_status),
            auction_start_at=auction_start_at,
            auction_end_at=auction_end_at,
            thumbnail_url=(images[0] if images else None),
            images=images or None,
            extras={k: v for k, v in extras.items() if v is not None},
            raw_payload={"html_card": card[:1000]},
        ))
        if len(lots) >= limit:
            break
    return lots


def fetch_sodre_lots(limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    global _LAST_REASON
    _LAST_REASON = None
    if not validate_auction_source_url(listing_url, ALLOWED_DOMAINS):
        _LAST_REASON = "invalid_source_url"
        return []
    with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as client:
        resp = client.get(listing_url)
        if getattr(resp, "status_code", None) == 403:
            _LAST_REASON = "forbidden_403"
            return []
        resp.raise_for_status()
    lots = parse_sodre_listing_html(resp.text, limit=limit, listing_url=listing_url)
    if lots:
        return lots
    if re.search(r"__NEXT_DATA__|react-root|vue|angular|api", resp.text, flags=re.I):
        _LAST_REASON = "requires_js_or_internal_endpoint"
    else:
        _LAST_REASON = "no_public_lot_cards_found"
    return []


def parse_sodre_detail_html(html: str, url: str) -> NormalizedAuctionLot:
    ext = _first_group(r"/lote/(\d+)/", url) or extract_sodre_external_id(url)
    auction_id = _first_group(r"/leilao/(\d+)/", url)
    title = _strip_html(_first_group(r"<h1[^>]*>(.*?)</h1>", html) or _first_group(r"<title[^>]*>(.*?)</title>", html) or "") or None
    imgs = filter_sodre_images(re.findall(r"<(?:img|source)[^>]+(?:src|data-src)=['\"]([^'\"]+)['\"]", html, flags=re.I), url)
    extras = {"auction_id": auction_id} if auction_id else {}
    if not any([title, imgs]):
        extras["skip_reason"] = "insufficient_detail_signals"
    return NormalizedAuctionLot(source=SOURCE_KEY, external_id=ext or url, title=title, url=url, item_type=infer_sodre_item_type(title, html), year=parse_year_from_title(title), initial_bid=parse_money_br(_first_group(r"Lance\s*inicial[^R]*(R\$\s*[0-9.]+,[0-9]{2})", html) or ""), current_bid=parse_money_br(_first_group(r"(?:Lance\s*atual|Maior\s*lance)[^R]*(R\$\s*[0-9.]+,[0-9]{2})", html) or ""), status=normalize_sodre_status(_first_group(r"(Ao vivo|Aberto|Encerrado|Em breve)", html)), thumbnail_url=imgs[0] if imgs else None, images=imgs or None, extras=extras or None, raw_payload={"html_card": html[:1000]})
