from __future__ import annotations

import logging
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.parsing import (
    extract_state_from_location,
    normalize_item_type,
    normalize_status,
    parse_datetime_br,
    parse_int_br,
    parse_money_br,
    parse_year_from_title,
)

SOURCE_KEY = "vip_auctions"
ALLOWED_DOMAINS = {"vipleiloes.com.br", "www.vipleiloes.com.br", "www2.vipleiloes.com.br"}
BLOCKED_DOMAINS = {"vipleiloes.club"}
DEFAULT_LISTING_URL = "https://www.vipleiloes.com.br/"

logger = logging.getLogger(__name__)
_LAST_REASON: str | None = None


def get_last_reason() -> str | None:
    return _LAST_REASON


def validate_auction_source_url(url: str, allowed_domains: Iterable[str]) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in BLOCKED_DOMAINS:
        return False
    return hostname in {d.lower() for d in allowed_domains}


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1) if m else None


def _extract_label_value(card: str, label: str) -> str | None:
    m = re.search(rf"(?:>|\b){label}\b\s*[:\-]?\s*(?:</?[^>]+>\s*)*([^<\n]+)", card, flags=re.I)
    return m.group(1).strip() if m else None


def _extract_city_state(location: str | None) -> tuple[str | None, str | None]:
    if not location:
        return None, None
    state = extract_state_from_location(location)
    city = location
    if state and "/" in location:
        city = location.split("/")[0].strip()
    return city, state


def _extract_mileage(text: str) -> int | None:
    m = re.search(r"(\d{1,3}(?:\.\d{3})+)\s*km", text, flags=re.I)
    return parse_int_br(m.group(1)) if m else None


def _extract_cards(html: str) -> list[str]:
    cards = re.findall(r'<article[^>]*class="[^"]*card[^"]*"[^>]*>(.*?)</article>', html, flags=re.I | re.S)
    if cards:
        return cards
    return re.findall(r'<div[^>]*class="[^"]*card[^"]*"[^>]*>(.*?)</div>', html, flags=re.I | re.S)


def fetch_vip_lots(limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    global _LAST_REASON
    _LAST_REASON = None
    if not validate_auction_source_url(listing_url, ALLOWED_DOMAINS):
        _LAST_REASON = "invalid_source_url"
        return []

    with httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as client:
        resp = client.get(listing_url)
        resp.raise_for_status()
        html = resp.text

    cards = _extract_cards(html)
    if not cards:
        _LAST_REASON = "no_public_lot_cards_found"
        return []

    lots: list[NormalizedAuctionLot] = []
    for idx, card in enumerate(cards[:limit]):
        title = _strip_html(_first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card) or "") or None
        href = _first_group(r'href="([^"]+)"', card)
        url = urljoin(listing_url, href) if href else None
        status_text = _extract_label_value(card, "Status") or _strip_html(_first_group(r'class="[^"]*status[^"]*"[^>]*>(.*?)</', card) or "")
        current_bid = parse_money_br(_extract_label_value(card, "Valor Atual"))
        initial_bid = parse_money_br(_extract_label_value(card, "Valor inicial"))
        lot_number = _first_group(r"\bLote\b\s*(?:</?[^>]+>\s*)*(\d+)", card) or _extract_label_value(card, "Lote")
        location = _extract_label_value(card, "Local")
        total_bids = parse_int_br(_first_group(r"\bLances\b\s*(?:</?[^>]+>\s*)*([\d.]+)", card) or _extract_label_value(card, "Lances"))
        auction_start_at = parse_datetime_br(_extract_label_value(card, "Início"))
        year = parse_year_from_title(title)
        mileage_km = _extract_mileage(_strip_html(card))
        city, state = _extract_city_state(location)
        item_type = normalize_item_type(f"{title or ''} {_strip_html(card)}")
        external_id = lot_number or _first_group(r"data-lot-id=\"([^\"]+)\"", card) or f"vip-{idx+1}"

        lots.append(
            NormalizedAuctionLot(
                source=SOURCE_KEY,
                external_id=str(external_id),
                url=url,
                title=title,
                lot_number=lot_number,
                item_type=item_type,
                year=year,
                mileage_km=mileage_km,
                city=city,
                state=state,
                location=location,
                initial_bid=initial_bid,
                current_bid=current_bid,
                total_bids=total_bids,
                status=normalize_status(status_text),
                auction_start_at=auction_start_at,
                raw_payload={"html_card": card[:1000]},
            )
        )
    logger.info("auction_source_finished", extra={"source": SOURCE_KEY, "fetched": len(lots)})
    return lots
