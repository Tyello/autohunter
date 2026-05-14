from __future__ import annotations

import logging
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.parsing import (
    extract_state_from_location,
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


def _normalize_status_vip(text: str | None) -> str:
    val = (text or "").strip().lower()
    if "dou-lhe duas" in val or "dou lhe duas" in val:
        return "live"
    if "ao vivo" in val:
        return "live"
    if "em preg" in val:
        return "live"
    if "aberto para lance" in val:
        return "open"
    if "vend" in val:
        return "sold"
    if "condicional" in val:
        return "conditional"
    return normalize_status(text)


def _infer_item_type(title: str | None, make: str | None, mileage_km: int | None, card_text: str) -> str:
    text = f"{title or ''} {card_text}".lower()
    moto_tokens = ("moto", "motocicleta", " cg ", " biz ", " fan ", " twister", " xre")
    if any(token in f" {text} " for token in moto_tokens):
        return "motorcycle"
    truck_tokens = ("axor", "caminh", "carreta", "truck", "bau", "baú", "cavalo mec")
    if any(token in text for token in truck_tokens):
        return "truck"
    if title and (make or mileage_km is not None):
        return "car"
    return "other"


def _extract_total_bids_vip(card_html: str, card_text: str) -> int | None:
    patterns = (
        r"\bLances\b\s*[:\-]?\s*(\d{1,5})\b",
        r"\b(\d{1,5})\s+lances\b",
    )
    for source in (card_html, card_text):
        for pattern in patterns:
            m = re.search(pattern, source, flags=re.I)
            if not m:
                continue
            total_bids = parse_int_br(m.group(1))
            if total_bids is None or total_bids < 0 or total_bids > 10000:
                return None
            return total_bids
    return None


def _extract_external_id(href: str | None) -> str | None:
    if not href:
        return None
    slug = href.rstrip("/").split("/")[-1]
    if not slug:
        return None
    m = re.search(r"(\d+)$", slug)
    return m.group(1) if m else slug


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

    grouped: dict[str, list[str]] = {}
    for card in cards:
        href = _first_group(r'href="([^"]*/evento/anuncio/[^"]+)"', card)
        if not href:
            continue
        key = href.split("?", 1)[0]
        grouped.setdefault(key, []).append(card)

    if not grouped:
        _LAST_REASON = "no_public_lot_cards_found"
        return []

    lots: list[NormalizedAuctionLot] = []
    for href, chunks in list(grouped.items())[:limit]:
        merged = "\n".join(chunks)
        merged_text = _strip_html(merged)

        title = _strip_html(_first_group(r'<[^>]*class="[^"]*anc-title[^"]*"[^>]*>.*?<h1[^>]*>(.*?)</h1>', merged) or "") or None
        make = _strip_html(_first_group(r'<[^>]*class="[^"]*anc-info[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>', merged) or "") or None
        make = make.title() if make else None
        status_text = _strip_html(_first_group(r'class="[^"]*(?:situacao|crd-status)[^"]*"[^>]*>(.*?)</', merged) or "")
        mileage_km = _extract_mileage(merged_text)
        lot_number = _first_group(r"\bLote\b\s*(?:</?[^>]+>\s*)*(\d+)", merged) or _extract_label_value(merged, "Lote")
        location = _extract_label_value(merged, "Local")
        city, state = _extract_city_state(location)
        current_bid = parse_money_br(_extract_label_value(merged, "Valor Atual"))
        initial_bid = parse_money_br(_extract_label_value(merged, "Valor inicial"))
        total_bids = _extract_total_bids_vip(merged, merged_text)
        auction_start_at = parse_datetime_br(_extract_label_value(merged, "Início"))
        year = parse_year_from_title(title)
        url = urljoin(listing_url, href)
        external_id = _extract_external_id(href) or lot_number or f"vip-{len(lots) + 1}"

        plate_final = _first_group(r"placa\s*final\s*(?:</?[^>]+>\s*)*([a-z0-9]+)", merged)
        item_type = _infer_item_type(title, make, mileage_km, merged_text)

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
                make=make,
                city=city,
                state=state,
                location=location,
                initial_bid=initial_bid,
                current_bid=current_bid,
                total_bids=total_bids,
                status=_normalize_status_vip(status_text),
                auction_start_at=auction_start_at,
                extras={"plate_final": plate_final} if plate_final else {},
                raw_payload={"html_card": merged[:1000]},
            )
        )
    logger.info("auction_source_finished", extra={"source": SOURCE_KEY, "fetched": len(lots)})
    return lots
