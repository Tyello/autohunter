from __future__ import annotations

import logging
from dataclasses import replace
import re
from typing import Iterable
from urllib.parse import urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.diagnostics import build_auction_source_fetch_diagnostics
from app.sources.auctions.parsing import absolute_url, external_id_from_url, normalize_item_type, normalize_title, parse_datetime_br, parse_int_br, parse_money_br, parse_year_from_title

SOURCE_KEY = "mega_auctions"
DEFAULT_LISTING_URL = "https://www.megaleiloes.com.br/veiculos/carros"
ALLOWED_DOMAINS = {"megaleiloes.com.br", "www.megaleiloes.com.br"}

VALID_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
}

logger = logging.getLogger(__name__)
_LAST_REASON: str | None = None
_LAST_FETCH_DIAGNOSTICS: dict | None = None

def get_last_reason() -> str | None:
    return _LAST_REASON

def get_last_fetch_diagnostics() -> dict | None:
    return _LAST_FETCH_DIAGNOSTICS


def validate_auction_source_url(url: str, allowed_domains: Iterable[str]) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {d.lower() for d in allowed_domains}


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1).strip() if m else None


def normalize_mega_status(text: str | None) -> str:
    val = (text or "").lower()
    if "aberto para lances" in val:
        return "open"
    if "em breve" in val:
        return "scheduled"
    return "unknown"


def parse_mega_praca_line(line: str | None) -> tuple[object | None, object | None]:
    if not line:
        return None, None
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4}\s*(?:às\s*)?\d{1,2}:\d{2})", line, flags=re.I)
    dt = parse_datetime_br(m.group(1)) if m else None
    money_match = re.search(r"R\$\s*[0-9.]+,[0-9]{2}", line, flags=re.I)
    value = parse_money_br(money_match.group(0) if money_match else line)
    return dt, value


def parse_mega_location(location: str | None) -> tuple[str | None, str | None, str | None]:
    if not location:
        return None, None, None
    clean = " ".join(location.strip().split())
    parts = [p.strip() for p in clean.split(",", 1)]
    if len(parts) != 2:
        return clean, None, clean
    city, uf = parts
    uf = uf.upper()
    if uf in {"SI", "NI"} or city.lower() in {"sem informação", "não informando"}:
        return None, None, clean
    return city, (uf if uf in VALID_UFS else None), clean


def parse_mega_compact_year(text: str | None) -> int | None:
    raw = text or ""
    m = re.search(r"\b((?:19|20)\d{2})\s*/\s*((?:19|20)\d{2})\b", raw)
    if m: return int(m.group(1))
    m = re.search(r"\b((?:19|20)\d{2})((?:19|20)\d{2})\b", raw)
    if m: return int(m.group(1))
    return parse_year_from_title(raw)

def infer_mega_item_type(title: str | None, url: str | None) -> str:
    t=(title or "").lower(); u=(url or "").lower()
    if "/veiculos/carros" in u or t.startswith("carro ") or " carro " in f" {t} ": return "car"
    if "/veiculos/motos" in u or t.startswith("moto ") or " moto " in f" {t} ": return "motorcycle"
    if any(k in t+u for k in ("caminh","onibus","ônibus","utilit","van")): return "truck"
    if any(k in t+u for k in ("imovel","imóvel","apartamento","terreno")): return "real_estate"
    if any(k in t+u for k in ("pesad","máquina","maquina")): return "heavy"
    return normalize_item_type(" ".join([title or "", url or ""]))

def parse_mega_listing_html(html: str, limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    cards = re.findall(r'<article[^>]*class="[^"]*(?:card|lot)[^"]*"[^>]*>(.*?)</article>', html, flags=re.I | re.S)
    if not cards:
        cards = re.findall(r'<div[^>]*class="[^"]*(?:card|lot)[^"]*"[^>]*>(.*?)</div>', html, flags=re.I | re.S)

    lots: list[NormalizedAuctionLot] = []
    for card in cards[:limit]:
        title = normalize_title(_strip_html(_first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card) or ""))
        if not title:
            title = normalize_title(_first_group(r'alt=["\']([^"\']+)["\']', card))
        href = _first_group(r'href=["\']([^"\']+)["\']', card)
        url = absolute_url(listing_url, href) if href and href.strip() != "-" else None
        if not url or url == "-":
            continue
        if any(
            blocked in url.lower()
            for blocked in ("/leiloes-judiciais", "/leiloes-extrajudiciais", "/como-funciona", "/cadastro", "/login", "/contato")
        ):
            continue
        raw_code = _strip_html(_first_group(r"\b(J\d{4,})\b", card) or "") or None
        external_id = raw_code or external_id_from_url(url) or _first_group(r"/([A-Z]\d{4,})/?$", href or "") or _first_group(r"/([A-Z]\d{4,})/?$", url) or url
        if not external_id:
            continue
        if not title:
            slug = (urlparse(url).path.rstrip("/").split("/")[-1] if url else "")
            guess = re.sub(r"[-_]+", " ", slug).strip()
            title = normalize_title(guess.title())

        location_text = _strip_html(_first_group(r"(?:Local|Cidade)\s*:?\s*</?[^>]*>\s*([^<]+)", card) or _first_group(r"([A-Za-zÀ-ÿ\s]+,\s*[A-Za-z]{2})", card) or "") or None
        city, state, location = parse_mega_location(location_text)
        status_text = _strip_html(_first_group(r"(?:Status)\s*:?\s*</?[^>]*>\s*([^<]+)", card) or _first_group(r"(Aberto para lances|Em breve)", card) or "")
        lot_number = parse_int_br(_first_group(r"Lote\s*(\d+)", card) or "")

        first_line = _first_group(r"1ª\s*Praça\s*:?\s*([^<]+)", card)
        second_line = _first_group(r"2ª\s*Praça\s*:?\s*([^<]+)", card)
        first_at, first_value = parse_mega_praca_line(first_line)
        second_at, second_value = parse_mega_praca_line(second_line)
        end_at = second_at or first_at

        make = _first_group(r"\bMoto\s+([A-Za-z]+)", title or "")
        year = parse_mega_compact_year(title)
        current_bid = parse_money_br(_first_group(r"(?:Valor atual|Lance atual|Valor)\s*:?\s*([^<]+)", card) or "")
        extras = {
            "first_praca_at": first_at.isoformat() if first_at else None,
            "first_praca_value": str(first_value) if first_value is not None else None,
            "second_praca_at": second_at.isoformat() if second_at else None,
            "second_praca_value": str(second_value) if second_value is not None else None,
            "judicial_type": _first_group(r"\b(Judicial|Extrajudicial)\b", card),
            "raw_code": raw_code,
            "views_count": parse_int_br(_first_group(r"(\d+)\s*visualiza", card) or ""),
            "bids_count": parse_int_br(_first_group(r"(\d+)\s*lances", card) or ""),
        }

        lots.append(NormalizedAuctionLot(
            source=SOURCE_KEY,
            external_id=external_id,
            url=url,
            title=title,
            item_type=infer_mega_item_type(title, url),
            make=make,
            year=year,
            city=city,
            state=state,
            location=location,
            status=normalize_mega_status(status_text),
            lot_number=str(lot_number) if lot_number is not None else None,
            auction_start_at=first_at,
            auction_end_at=end_at,
            initial_bid=first_value,
            current_bid=current_bid,
            extras={k: v for k, v in extras.items() if v is not None},
            raw_payload={"html_card": card[:1000]},
        ))
    return lots


def fetch_mega_lots(limit: int = 50, listing_url: str = DEFAULT_LISTING_URL, enrich: bool = False) -> list[NormalizedAuctionLot]:
    global _LAST_REASON, _LAST_FETCH_DIAGNOSTICS
    _LAST_REASON = None
    _LAST_FETCH_DIAGNOSTICS = None
    if not validate_auction_source_url(listing_url, ALLOWED_DOMAINS):
        _LAST_REASON = "invalid_source_url"
        return []
    with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as client:
        resp = client.get(listing_url)
        resp.raise_for_status()
        _LAST_FETCH_DIAGNOSTICS = build_auction_source_fetch_diagnostics(resp, resp.text, listing_url)
        lots = parse_mega_listing_html(resp.text, limit=limit, listing_url=listing_url)
        if enrich and lots:
            out=[]
            for lot in lots:
                detail_applied=False
                d_reason=[]
                try:
                    d=client.get(lot.url)
                    d.raise_for_status()
                    parsed=parse_mega_detail_html(d.text, lot.url)
                    detail_applied=True
                    if parsed.current_bid is None and parsed.initial_bid is None: d_reason.append("detail_without_bid_signals")
                    if not parsed.thumbnail_url: d_reason.append("detail_without_image_signals")
                    extras=dict(lot.extras or {})
                    extras.update({"detail_fetch_applied": True, "detail_parse_applied": detail_applied})
                    if d_reason: extras["detail_reason"]=d_reason
                    lot=replace(lot, title=parsed.title or lot.title, year=parsed.year or lot.year, city=parsed.city or lot.city, state=parsed.state or lot.state, status=parsed.status or lot.status, initial_bid=lot.initial_bid or parsed.initial_bid, current_bid=lot.current_bid or parsed.current_bid, thumbnail_url=lot.thumbnail_url or parsed.thumbnail_url, images=lot.images or parsed.images, extras=extras)
                except Exception:
                    extras=dict(lot.extras or {})
                    extras.update({"detail_fetch_applied": False, "detail_parse_applied": False})
                    lot=replace(lot, extras=extras)
                out.append(lot)
            lots=out
    if lots:
        return lots
    _LAST_REASON = "no_public_lot_cards_found"
    return []


def parse_mega_detail_html(html: str, url: str) -> NormalizedAuctionLot:
    clean_url = re.sub(r"[?&]utm_[^=&]+=[^&]+", "", url).rstrip("?&")
    title = normalize_title(_strip_html(_first_group(r"<h1[^>]*>(.*?)</h1>", html) or _first_group(r"<title[^>]*>(.*?)</title>", html) or ""))
    external_id = _first_group(r"\b(J\d{4,})\b", html) or external_id_from_url(clean_url)
    city = state = None
    m = re.search(r"/veiculos/carros/([a-z-]+)/([a-z-]+)/", clean_url, flags=re.I)
    if m:
        state = m.group(1).upper()
        city = m.group(2).replace('-', ' ').title()
    imgs = re.findall(r"<meta[^>]+property=['\"]og:image['\"][^>]+content=['\"]([^'\"]+)", html, flags=re.I)
    return NormalizedAuctionLot(source=SOURCE_KEY, external_id=external_id or clean_url, url=clean_url, title=title, item_type=infer_mega_item_type(title, clean_url), year=parse_mega_compact_year(title), city=city, state=state, initial_bid=parse_money_br(_first_group(r"Lance\s*inicial[^R]*(R\$\s*[0-9.]+,[0-9]{2})", html) or ""), current_bid=parse_money_br(_first_group(r"(?:Lance\s*atual|Maior\s*lance)[^R]*(R\$\s*[0-9.]+,[0-9]{2})", html) or ""), thumbnail_url=absolute_url(clean_url, imgs[0]) if imgs else None, images=[absolute_url(clean_url, i) for i in imgs] or None, status=normalize_mega_status(_first_group(r"(Aberto para lances|Em breve)", html)), raw_payload={"html_card": html[:1000]})
