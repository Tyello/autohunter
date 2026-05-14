from __future__ import annotations

import logging
import re
from typing import Any, Iterable
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


VALID_UFS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}


def _sanitize_location_text(value: str | None) -> str | None:
    if not value:
        return None
    clean = _strip_html(value).strip(" :,-")
    lowered = clean.lower()
    if not clean or "<" in clean or ">" in clean:
        return None
    if "local do lote" in lowered or clean.lower() == "local":
        return None
    return clean


def _sanitize_uf(value: str | None) -> str | None:
    if not value:
        return None
    clean = _strip_html(value).strip().upper()
    if clean in VALID_UFS:
        return clean
    return None


def _extract_vip_lot_number(text: str | None) -> str | None:
    if not text:
        return None
    raw = text.strip()
    if '": "' in raw and "lote" not in raw.lower():
        return None
    m = re.search(r"^\D*(\d{1,8})\D*$", raw)
    if m:
        return m.group(1)
    m = re.search(r"\bLote\b\s*[:\-]?\s*(\d{1,8})\b", text, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r'"lote"\s*:\s*"(\d{1,8})"', text, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r"\blote\b\s*:\s*\"?(\d{1,8})\"?", text, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r"\blote\s+(\d{1,8})\b", text, flags=re.I)
    if m:
        return m.group(1)
    return None


def _filter_vip_lot_images(images: list[str]) -> list[str]:
    blocked_tokens = ("logo", "footer", "whatsapp", "wapp", "aleibras", "leilao-seguro", "comitente", "images/vipleiloes")
    preferred = "armazupvipleiloesprd.blob.core.windows.net/uploads/"
    filtered: list[str] = []
    for img in images:
        lowered = img.lower()
        if any(token in lowered for token in blocked_tokens):
            continue
        if img not in filtered:
            filtered.append(img)
    filtered.sort(key=lambda url: (0 if preferred in url.lower() else 1))
    return filtered


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
    patterns = (r"\bLances\b\s*[:\-]?\s*(\d{1,5})\b", r"\b(\d{1,5})\s+lances\b")
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


def fetch_vip_lot_detail(url: str, timeout: float = 15.0) -> dict[str, Any]:
    if not validate_auction_source_url(url, ALLOWED_DOMAINS):
        raise ValueError("invalid_detail_url")
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return parse_vip_lot_detail_html(resp.text, base_url=url)


def parse_vip_lot_detail_html(html: str, base_url: str | None = None) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    detail["initial_bid"] = parse_money_br(_extract_label_value(html, "Lance inicial") or _extract_label_value(html, "Valor inicial") or _extract_label_value(html, "Inicial"))
    detail["current_bid"] = parse_money_br(_extract_label_value(html, "Lance atual") or _extract_label_value(html, "Valor atual") or _extract_label_value(html, "Atual"))
    detail["auction_start_at"] = parse_datetime_br(_extract_label_value(html, "Início") or _extract_label_value(html, "Data de início"))
    detail["auction_end_at"] = parse_datetime_br(_extract_label_value(html, "Término") or _extract_label_value(html, "Encerramento") or _extract_label_value(html, "Fim"))
    detail["location"] = _sanitize_location_text(_extract_label_value(html, "Local") or _extract_label_value(html, "Pátio"))
    detail["city"] = _sanitize_location_text(_extract_label_value(html, "Cidade"))
    detail["state"] = _sanitize_uf(_extract_label_value(html, "UF"))
    if detail.get("location") and (not detail.get("city") or not detail.get("state")):
        city, state = _extract_city_state(detail["location"])
        detail["city"] = detail["city"] or _sanitize_location_text(city)
        detail["state"] = detail["state"] or _sanitize_uf(state)
    detail["condition"] = _extract_label_value(html, "Condição") or _extract_label_value(html, "Observação") or _extract_label_value(html, "Estado")
    detail["document_type"] = _extract_label_value(html, "Documento") or _extract_label_value(html, "Tipo de documento")
    raw_lot_number = _extract_label_value(html, "Lote")
    detail["lot_number"] = _extract_vip_lot_number(raw_lot_number) or _extract_vip_lot_number(html)
    detail["total_bids"] = _extract_total_bids_vip(html, _strip_html(html))
    images = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    filtered = []
    for img in images:
        full = urljoin(base_url or "", img)
        if full not in filtered and (full.startswith("http://") or full.startswith("https://")):
            filtered.append(full)
    filtered = _filter_vip_lot_images(filtered)
    if filtered:
        detail["thumbnail_url"] = filtered[0]
        detail["images"] = filtered
        detail["image_count"] = len(filtered)
    return {k: v for k, v in detail.items() if v is not None}


def apply_vip_detail(lot: NormalizedAuctionLot, detail: dict[str, Any]) -> NormalizedAuctionLot:
    protected = {"city", "state", "location", "lot_number", "thumbnail_url", "images", "image_count"}
    for key, value in detail.items():
        if value is None:
            continue
        if key in protected:
            if key == "state":
                value = _sanitize_uf(str(value))
                if value is None:
                    continue
            if key in {"city", "location"}:
                value = _sanitize_location_text(str(value))
                if value is None:
                    continue
            if key == "lot_number":
                value = _extract_vip_lot_number(str(value))
                if value is None:
                    continue
            if key in {"images"}:
                if not isinstance(value, list):
                    continue
                value = _filter_vip_lot_images(value)
                if not value:
                    continue
            if key == "thumbnail_url":
                if not isinstance(value, str):
                    continue
                thumb = _filter_vip_lot_images([value])
                if not thumb:
                    continue
                value = thumb[0]
        setattr(lot, key, value)
    if lot.images:
        lot.images = _filter_vip_lot_images(list(lot.images))
        if lot.images and (not lot.thumbnail_url or lot.thumbnail_url not in lot.images):
            lot.thumbnail_url = lot.images[0]
    return lot


def enrich_vip_lot_detail(lot: NormalizedAuctionLot) -> NormalizedAuctionLot:
    try:
        detail = fetch_vip_lot_detail(str(lot.url or ""))
        return apply_vip_detail(lot, detail)
    except Exception as exc:
        extras = dict(lot.extras or {})
        warnings = list(extras.get("parser_warnings") or [])
        warnings.append(f"vip_detail_failed:{type(exc).__name__}")
        extras["parser_warnings"] = warnings
        lot.extras = extras
        return lot


def fetch_vip_lots(limit: int = 50, listing_url: str = DEFAULT_LISTING_URL, enrich: bool = False) -> list[NormalizedAuctionLot]:
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
        lot = NormalizedAuctionLot(source=SOURCE_KEY, external_id=str(external_id), url=url, title=title, lot_number=lot_number, item_type=item_type, year=year, mileage_km=mileage_km, make=make, city=city, state=state, location=location, initial_bid=initial_bid, current_bid=current_bid, total_bids=total_bids, status=_normalize_status_vip(status_text), auction_start_at=auction_start_at, extras={"plate_final": plate_final} if plate_final else {}, raw_payload={"html_card": merged[:1000]})
        lots.append(enrich_vip_lot_detail(lot) if enrich else lot)
    logger.info("auction_source_finished", extra={"source": SOURCE_KEY, "fetched": len(lots), "enrich": enrich})
    return lots
