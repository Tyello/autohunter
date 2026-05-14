from __future__ import annotations

import logging
import re
import time
from typing import Iterable
from urllib.parse import urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.parsing import (
    extract_state_from_location,
    normalize_item_type,
    normalize_status,
    parse_int_br,
    parse_money_br,
    parse_year_from_title,
)

SOURCE_KEY = "copart_auctions"
ALLOWED_DOMAINS = {"copart.com.br", "www.copart.com.br"}
VEHICLE_FINDER_URL = "https://www.copart.com.br/vehicleFinder"

logger = logging.getLogger(__name__)
_LAST_REASON: str | None = None


def get_last_reason() -> str | None:
    return _LAST_REASON


def validate_auction_source_url(url: str, allowed_domains: Iterable[str]) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {d.lower() for d in allowed_domains}



def _extract_static_cards(html: str, limit: int) -> list[NormalizedAuctionLot]:
    cards = re.findall(r'<article[^>]*class="[^"]*(?:lot|vehicle)[^"]*"[^>]*>(.*?)</article>', html, flags=re.I | re.S)
    lots: list[NormalizedAuctionLot] = []
    for idx, card in enumerate(cards[:limit]):
        title = _first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card)
        href = _first_group(r'href="([^"]+)"', card)
        ext = _first_group(r'data-lot-id="([^"]+)"', card) or _first_group(r"Lote\s*#?\s*(\w+)", card) or f"static-{idx+1}"
        location = _strip_html(_first_group(r'class="[^"]*location[^"]*"[^>]*>(.*?)</', card) or "") or None
        category = _strip_html(_first_group(r'class="[^"]*category[^"]*"[^>]*>(.*?)</', card) or "")
        lots.append(NormalizedAuctionLot(source=SOURCE_KEY, external_id=str(ext), url=href, title=_strip_html(title or "") or None, item_type=normalize_item_type(category), year=parse_year_from_title(title), location=location, state=extract_state_from_location(location), status="auction", raw_payload={"html_card": card[:1000]}))
    return lots


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1) if m else None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def fetch_copart_lots(limit: int = 50) -> list[NormalizedAuctionLot]:
    global _LAST_REASON
    _LAST_REASON = None
    if not validate_auction_source_url(VEHICLE_FINDER_URL, ALLOWED_DOMAINS):
        _LAST_REASON = "invalid_source_url"
        return []
    logger.info("auction_source_started", extra={"source": SOURCE_KEY, "limit": limit})
    time.sleep(0.2)
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as client:
            resp = client.get(VEHICLE_FINDER_URL)
            resp.raise_for_status()
            html = resp.text
    except Exception:
        logger.exception("auction_source_failed", extra={"source": SOURCE_KEY})
        raise

    lots = _extract_static_cards(html, limit=limit)
    if lots:
        logger.info("auction_source_finished", extra={"source": SOURCE_KEY, "fetched": len(lots)})
        return lots
    has_js_bootstrap = "__NEXT_DATA__" in html or "webpack" in html.lower() or "vehicleFinder" in html
    _LAST_REASON = "requires_js_or_internal_endpoint" if has_js_bootstrap else "no_public_lot_cards_found"
    logger.info("auction_source_finished", extra={"source": SOURCE_KEY, "fetched": 0, "reason": _LAST_REASON})
    return []
