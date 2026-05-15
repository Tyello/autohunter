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
ALLOWED_DOMAINS = {"sodresantoro.com.br", "www.sodresantoro.com.br"}
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


def parse_sodre_listing_html(html: str, limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    cards = re.findall(r"<(article|div)[^>]*class=\"[^\"]*(?:card|lot|item|leilao|leilão)[^\"]*\"[^>]*>(.*?)</\1>", html, flags=re.I | re.S)
    lots: list[NormalizedAuctionLot] = []
    for _, card in cards:
        href = _first_group(r'href=["\']([^"\']+)["\']', card)
        if not href:
            continue
        url = urljoin(listing_url, href)
        ext_id = extract_sodre_external_id(url)
        if not ext_id:
            continue
        title = _strip_html(_first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card) or "") or None
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
        resp.raise_for_status()
    lots = parse_sodre_listing_html(resp.text, limit=limit, listing_url=listing_url)
    if lots:
        return lots
    if re.search(r"__NEXT_DATA__|react-root|vue|angular|api", resp.text, flags=re.I):
        _LAST_REASON = "requires_js_or_internal_endpoint"
    else:
        _LAST_REASON = "no_public_lot_cards_found"
    return []
