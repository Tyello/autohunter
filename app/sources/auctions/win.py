from __future__ import annotations

import hashlib
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.parsing import absolute_url, external_id_from_url, normalize_title, parse_datetime_br, parse_money_br

SOURCE_KEY = "win_auctions"
DEFAULT_LISTING_URL = "https://winleiloes.com.br/"
ALLOWED_DOMAINS = {"winleiloes.com.br", "www.winleiloes.com.br"}

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


def normalize_win_status(text: str | None) -> str:
    val = (text or "").lower()
    if "andamento" in val:
        return "live"
    if "loteamento" in val:
        return "scheduled"
    if "encerrado" in val:
        return "ended"
    return "unknown"


def parse_win_location(text: str | None) -> tuple[str | None, str | None, str | None]:
    if not text:
        return None, None, None
    clean = _strip_html(text).strip(" :,-")
    m = re.search(r"^(.+?)\s*/\s*([A-Za-z]{2})$", clean)
    if not m:
        return clean or None, None, clean or None
    city = m.group(1).strip()
    state = m.group(2).upper()
    return city, (state if state in VALID_UFS else None), clean


def extract_win_external_id(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    numeric = re.search(r"(?:-|/)(\d{3,})(?:$|\D)", path) or re.search(r"(\d{3,})$", slug)
    if numeric:
        return numeric.group(1)
    if slug:
        return slug.lower()
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def infer_win_item_type(*texts: str | None) -> str:
    text = " ".join(t for t in texts if t).lower()
    if "moto" in text:
        return "motorcycle"
    if "pesad" in text:
        return "truck"
    if "veícul" in text or "veicul" in text or "leves" in text:
        return "car"
    return "other"


def parse_win_listing_html(html: str, limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    cards = re.findall(r'<article[^>]*class="[^"]*(?:card|item|lot|leilao)[^"]*"[^>]*>(.*?)</article>', html, flags=re.I | re.S)
    if not cards:
        cards = re.findall(r'<div[^>]*class="[^"]*(?:card|item|lot|leilao)[^"]*"[^>]*>(.*?)</div>', html, flags=re.I | re.S)
    lots: list[NormalizedAuctionLot] = []
    for card in cards:
        href = _first_group(r'href=["\']([^"\']+)["\']', card)
        title = normalize_title(_strip_html(_first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card) or ""))
        if not title:
            title = normalize_title(_first_group(r'alt=["\']([^"\']+)["\']', card))
        url = absolute_url(listing_url, href) if href else None
        if not url:
            continue
        low_url = url.lower()
        if any(
            block in low_url
            for block in ("/licitante/cadastro/login", "/lotes/search", "/leiloes/venda-direta", "/login", "/cadastro")
        ) and "/item/" not in low_url:
            continue
        # Prefer canonical item detail URLs when available, but keep compatibility
        # with legacy cards while still blocking known institutional/navigation paths.
        if "/leilao/" in low_url and "/lotes" in low_url and "/item/" not in low_url:
            continue
        external_id = extract_win_external_id(url) or external_id_from_url(url)
        if not external_id:
            continue
        if title and re.search(r"^\s*lance\s+inicial\s*:", title, flags=re.I):
            title = None
        loc_candidates = re.findall(r"\b([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{1,40}/[A-Za-z]{2})\b", card, flags=re.I)
        location_text = None
        for cand in loc_candidates:
            if "lote" not in cand.lower():
                location_text = cand
                break
        city, state, location = parse_win_location(location_text)
        raw_status = _strip_html(_first_group(r"(Online\s+Em\s+Andamento|Em\s+Andamento|Online\s+Em\s+Loteamento|Em\s+Loteamento|Encerrado)", card) or "") or None
        auction_date = _first_group(r"Data\s*:?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", card)
        first_lot_time = _first_group(r"Primeiro\s*lote\s*a\s*partir\s*das\s*:?\s*([0-9]{1,2}:[0-9]{2})", card)
        auction_start_at = parse_datetime_br(f"{auction_date} {first_lot_time}" if auction_date and first_lot_time else auction_date)
        initial_bid = parse_money_br(_first_group(r"Lance\s*Inicial\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", card) or "")
        current_bid = parse_money_br(_first_group(r"Lance\s*Atual\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", card) or "")
        source_category = _strip_html(_first_group(r"(?:categoria|category)\s*:?\s*([^<]+)", card) or "") or None
        listing_kind = "auction_event" if auction_date or "leilão" in (title or "").lower() else "lot"
        extras = {
            "auction_date": auction_date,
            "first_lot_time": first_lot_time,
            "source_category": source_category,
            "raw_status": raw_status,
            "raw_location": location,
            "listing_kind": listing_kind,
        }
        lots.append(NormalizedAuctionLot(
            source=SOURCE_KEY,
            external_id=external_id,
            title=title,
            url=url,
            item_type=infer_win_item_type(title, source_category, card),
            city=city,
            state=state,
            location=location,
            status=normalize_win_status(raw_status),
            auction_start_at=auction_start_at,
            auction_end_at=None,
            initial_bid=initial_bid,
            current_bid=current_bid,
            extras={k: v for k, v in extras.items() if v is not None},
            raw_payload={"html_card": card[:1000]},
        ))
        if len(lots) >= limit:
            break
    return lots


def fetch_win_lots(limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    global _LAST_REASON
    _LAST_REASON = None
    if not validate_auction_source_url(listing_url, ALLOWED_DOMAINS):
        _LAST_REASON = "invalid_source_url"
        return []
    with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as client:
        resp = client.get(listing_url)
        resp.raise_for_status()
    lots = parse_win_listing_html(resp.text, limit=limit, listing_url=listing_url)
    if lots:
        return lots
    _LAST_REASON = "no_public_lot_cards_found"
    return []
