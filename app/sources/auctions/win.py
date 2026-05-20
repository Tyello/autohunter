from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from dataclasses import replace
from typing import Iterable
from urllib.parse import urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.diagnostics import build_auction_source_fetch_diagnostics
from app.sources.auctions.parsing import absolute_url, external_id_from_url, normalize_item_type, normalize_title, parse_datetime_br, parse_int_br, parse_money_br

SOURCE_KEY = "win_auctions"
DEFAULT_LISTING_URL = "https://www.winleiloes.com.br/lotes/veiculo?tipo=veiculo&categoria_id=8"
ALLOWED_DOMAINS = {"winleiloes.com.br", "www.winleiloes.com.br"}
VALID_UFS = {"AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"}
_AUTOMOTIVE_BRANDS = {
    "CAOA CHERY", "FIAT", "VOLKSWAGEN", "VW", "TOYOTA", "HONDA", "HYUNDAI", "FORD", "RENAULT", "PEUGEOT", "CITROEN",
    "CHEVROLET", "NISSAN", "JEEP", "BMW", "AUDI", "MERCEDES", "MERCEDES-BENZ", "KIA", "VOLVO", "MITSUBISHI", "RAM"
}
_LAST_REASON: str | None = None
_LAST_FETCH_DIAGNOSTICS: dict | None = None

def get_last_reason() -> str | None: return _LAST_REASON
def get_last_fetch_diagnostics() -> dict | None: return _LAST_FETCH_DIAGNOSTICS

def validate_auction_source_url(url: str, allowed_domains: Iterable[str]) -> bool:
    return (urlparse(url).hostname or "").lower() in {d.lower() for d in allowed_domains}

def _strip_html(text: str) -> str: return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1).strip() if m else None

def normalize_win_status(text: str | None) -> str:
    v = (text or "").lower()
    if any(k in v for k in ("loteamento", "agendado", "agendada")): return "scheduled"
    if any(k in v for k in ("encerrado", "finalizado", "arrematado")): return "ended"
    if any(k in v for k in ("aberto", "aberta", "online", "andamento")): return "live"
    return "unknown"


def _extract_win_status(html: str, fallback: str | None) -> str:
    labels = (
        r"(?:situa[cç][aã]o|status)\s*:?\s*(aberto|aberta|online|em\s+andamento|encerrado|finalizado|em\s+loteamento|loteamento|agendad[oa])",
        r"\b(online\s+em\s+andamento|em\s+andamento|online|abert[oa]|em\s+loteamento|loteamento|encerrado|finalizado|agendad[oa])\b",
    )
    for pat in labels:
        val = _first_group(pat, html)
        if val:
            return normalize_win_status(val)
    return normalize_win_status(fallback)


def _parse_br_dt(raw: str) -> object | None:
    clean = (raw or "").strip()
    m = re.search(r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})(?:\s+([0-9]{1,2}:[0-9]{2}))?", clean)
    if m:
        d = m.group(1)
        t = m.group(2)
        if len(d.split("/")[-1]) == 2:
            d = f"{d[:-2]}20{d[-2:]}"
        if t:
            try:
                return datetime.strptime(f"{d} {t}", "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return parse_datetime_br(d)
    return parse_datetime_br(clean)


def _extract_win_auction_dates(html: str) -> tuple[object | None, object | None]:
    end_at = None
    start_at = None
    end_patterns = (
        r"(?:encerramento|fim\s+do\s+leil[aã]o|data\s+final|encerra(?:\s*em)?|t[eé]rmino)\s*:?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}(?:\s*(?:[àa-]|\s)\s*[0-9]{1,2}:[0-9]{2})?)",
    )
    start_patterns = (
        r"(?:in[ií]cio|data\s+do\s+leil[aã]o|leil[aã]o\s+em|abertura)\s*:?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}(?:\s*(?:[àa-]|\s)\s*[0-9]{1,2}:[0-9]{2})?)",
    )
    for pat in end_patterns:
        raw = _first_group(pat, html)
        if raw:
            date = _first_group(r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", raw)
            hhmm = _first_group(r"([0-9]{1,2}:[0-9]{2})", raw)
            end_at = _parse_br_dt(f"{date} {hhmm}" if date and hhmm else (date or raw))
            if end_at:
                break
    for pat in start_patterns:
        raw = _first_group(pat, html)
        if raw:
            date = _first_group(r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", raw)
            hhmm = _first_group(r"([0-9]{1,2}:[0-9]{2})", raw)
            start_at = _parse_br_dt(f"{date} {hhmm}" if date and hhmm else (date or raw))
            if start_at:
                break
    return end_at, start_at


def is_reliable_win_location(city: str | None, state: str | None, location: str | None) -> bool:
    city_clean = (city or "").strip()
    state_clean = (state or "").strip().upper()
    location_clean = (location or "").strip()
    city_upper = re.sub(r"\s+", " ", city_clean.upper())
    city_lower = city_clean.lower()

    if not city_clean or not state_clean or state_clean not in VALID_UFS:
        return False
    if "/" in city_clean or len(city_clean) < 3:
        return False
    if any(tok in city_lower for tok in ("www", "http", "https")) or "." in city_lower:
        return False
    if city_lower == "com" or city_lower.endswith(".com"):
        return False
    if any(brand in city_upper for brand in _AUTOMOTIVE_BRANDS):
        return False
    if location_clean:
        normalized_location = re.sub(r"\s*/\s*", "/", location_clean)
        if normalized_location != f"{city_clean}/{state_clean}":
            return False
    return True

def parse_win_location(text: str | None) -> tuple[str | None, str | None, str | None]:
    if not text: return None, None, None
    clean = _strip_html(text).strip(" :,-")
    m = re.search(r"^(.+?)\s*/\s*([A-Za-z]{2})$", clean)
    if not m: return clean or None, None, clean or None
    city, state = m.group(1).strip(), m.group(2).upper()
    st = state if state in VALID_UFS else None
    normalized = f"{city}/{st}" if city and st else None
    if is_reliable_win_location(city, st, normalized):
        return city, st, normalized
    return None, None, None

def parse_win_external_id_from_url(url: str | None) -> str | None:
    if not url: return None
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    numeric = re.search(r"(?:-|/)(\d{3,})(?:$|\D)", path) or re.search(r"(\d{3,})$", slug)
    if numeric: return numeric.group(1)
    if slug: return slug.lower()
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

extract_win_external_id = parse_win_external_id_from_url

def infer_win_item_type(*texts: str | None) -> str:
    txt = " ".join(t for t in texts if t).lower()
    real_estate_terms = ("imóvel","imovel","terreno","apartamento","casa","fazenda","sítio","sitio","propriedade rural","prédio","predio")
    motorcycle_terms = ("moto","motocicleta"," cg "," biz "," fan "," titan"," bros "," xre "," pop "," yamaha "," fazer "," factor "," crypton ")
    truck_terms = ("caminhão","caminhao","ônibus","onibus","cargo","atego","accelo","constellation")
    heavy_terms = ("carreta","bitrem","pesado")
    car_models = ("hilux","corolla","civic","hb20","onix","ranger","s10","compass","renegade","kicks","sandero","gol","kombi","uno","palio","fiesta","fox","saveiro","strada","toro")
    car_terms = ("carro","automóvel","automovel","veículo leve","veiculo leve","sedan","hatch","suv","pickup","caminhonete","utilitário","utilitario")
    generic_brands = ("toyota","volkswagen","vw","chevrolet","fiat","ford","honda","hyundai","renault","jeep","nissan","peugeot","citroen","mitsubishi","bmw","audi","mercedes","kia","volvo","land rover","ram")

    if any(k in txt for k in real_estate_terms):
        return "real_estate"
    if any(k in txt for k in motorcycle_terms):
        return "motorcycle"
    if any(k in txt for k in truck_terms):
        return "truck"
    if any(k in txt for k in heavy_terms):
        return "heavy"
    if any(k in txt for k in car_models):
        return "car"
    if any(k in txt for k in car_terms):
        return "car"
    if any(k in txt for k in generic_brands):
        return "car"
    if any(k in txt for k in ("máquina","maquina")):
        return "heavy"
    return normalize_item_type(txt)

def _valid_win_title(title: str | None) -> str | None:
    if not title: return None
    low = title.strip().lower()
    if low in {"lance inicial","descrição","descricao","bem","lote"} or low.startswith("lance inicial:"): return None
    if re.fullmatch(r"[a-zà-ÿ\s]{2,40}/[a-z]{2}", low): return None
    if re.fullmatch(r"[a-zà-ÿ\s]{2,30}", low) and low in {"descrição do lote","informações do lote","informacoes do lote"}: return None
    return title


def _extract_vehicle_year_from_text(text: str | None) -> int | None:
    if not text:
        return None
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
    if not years:
        return None
    current_year = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).year
    valid = [y for y in years if 1900 <= y <= current_year + 1]
    if not valid:
        return None
    if len(valid) >= 2 and 0 <= (valid[1] - valid[0]) <= 2:
        return valid[0]
    return valid[0]

def _enrich_win_detail(client: httpx.Client, lot: NormalizedAuctionLot) -> NormalizedAuctionLot:
    if not lot.url or "/item/" not in lot.url.lower() or "/detalhes" not in lot.url.lower(): return lot
    try:
        r = client.get(lot.url)
        r.raise_for_status()
    except Exception:
        return lot
    html = r.text
    title = _valid_win_title(lot.title)
    detail_title = normalize_title(_first_group(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html) or "")
    if not title: title = _valid_win_title(detail_title)
    if not title: title = _valid_win_title(normalize_title(_strip_html(_first_group(r"<title[^>]*>(.*?)</title>", html) or "")))
    if not title:
        for pat in (r"<h1[^>]*>(.*?)</h1>", r"<h2[^>]*>(.*?)</h2>", r"<h3[^>]*>(.*?)</h3>"):
            title = _valid_win_title(normalize_title(_strip_html(_first_group(pat, html) or "")))
            if title: break
    if not title:
        title = _valid_win_title(normalize_title(_strip_html(_first_group(r"(?:Descrição|Descricao|Bem|Lote)\s*:?\s*</[^>]+>\s*<[^>]+>([^<]+)", html) or "")))
    if not title and lot.url:
        slug = urlparse(lot.url).path.rstrip("/").split("/")[-2] if "/detalhes" in lot.url else ""
        title = _valid_win_title(normalize_title(re.sub(r"[-_]+", " ", slug)))
    initial_bid = lot.initial_bid or parse_money_br(_first_group(r"Lance\s*Inicial\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", html) or "")
    current_bid = lot.current_bid or parse_money_br(
        _first_group(r"(?:Lance\s*Atual|Lance\s*Vencedor|Maior\s*Lance|[UÚ]ltimo\s*Lance)\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", html) or ""
    )
    clean_html = _strip_html(html)
    primary_text = " ".join(p for p in [title, lot.url, lot.item_type] if p)
    item_type = infer_win_item_type(primary_text)
    if item_type == "other":
        item_type = infer_win_item_type(clean_html, lot.item_type)
    year = lot.year
    if item_type in {"car", "motorcycle", "truck", "heavy"}:
        year = year or _extract_vehicle_year_from_text(" ".join([title or "", clean_html]))
    elif item_type == "real_estate":
        year = None
    mileage = parse_int_br(_first_group(r"([0-9.]{2,7})\s*km", html) or "")
    raw_loc = _first_group(r"([A-Za-zÀ-ÿ\s]{2,40}/[A-Za-z]{2})", html)
    city, state, location = parse_win_location(raw_loc)
    if not is_reliable_win_location(city, state, location):
        city, state, location = parse_win_location(lot.location)
    status = _extract_win_status(html, lot.status)
    end_at, start_at = _extract_win_auction_dates(html)
    imgs = re.findall(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, flags=re.I)
    if not imgs:
        imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    imgs = [absolute_url(lot.url, i) for i in imgs if re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", i, flags=re.I)]
    extras = dict(lot.extras or {})
    if mileage is not None: extras["mileage_km"] = mileage
    current_year = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).year
    if year is not None and (year < 1900 or year > current_year + 1):
        year = None
    return replace(
        lot,
        title=title,
        initial_bid=initial_bid,
        current_bid=current_bid,
        year=year,
        city=city,
        state=state,
        location=location,
        status=status,
        auction_end_at=lot.auction_end_at or end_at,
        auction_start_at=lot.auction_start_at or start_at,
        item_type=item_type,
        thumbnail_url=lot.thumbnail_url or (imgs[0] if imgs else None),
        images=lot.images or (imgs or None),
        extras=extras,
    )

def parse_win_listing_html(html: str, limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    detail_pat = re.compile(r'(?:https?://(?:www\.)?winleiloes\.com\.br)?/item/\d+/detalhes(?:\?[^"\']*)?', flags=re.I)
    found_urls: list[str] = []
    for m in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
        if detail_pat.search(m):
            found_urls.append(m)
    for m in detail_pat.findall(html):
        found_urls.append(m)
    normalized_detail_urls: list[str] = []
    seen_urls = set()
    for u in found_urls:
        url = absolute_url(listing_url, u)
        if not url:
            continue
        if url.endswith("/detalhes?page=1"):
            url = url.replace("?page=1", "")
        url = re.sub(r"\?page=1$", "", url, flags=re.I)
        if not validate_auction_source_url(url, ALLOWED_DOMAINS):
            continue
        if "/item/" not in url.lower() or "/detalhes" not in url.lower():
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        normalized_detail_urls.append(url)

    card_by_detail_url: dict[str, str] = {}
    cards = re.findall(r'<article[^>]*class="[^"]*(?:card|item|lot|leilao)[^"]*"[^>]*>(.*?)</article>', html, flags=re.I | re.S) or re.findall(r'<div[^>]*class="[^"]*(?:card|item|lot|leilao)[^"]*"[^>]*>(.*?)</div>', html, flags=re.I | re.S)
    lots = []
    for card in cards:
        href = _first_group(r'href=["\']([^"\']+)["\']', card)
        title = _valid_win_title(normalize_title(_strip_html(_first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card) or ""))) or _valid_win_title(normalize_title(_first_group(r'alt=["\']([^"\']+)["\']', card)))
        url = absolute_url(listing_url, href) if href else None
        if url and url.endswith("/detalhes?page=1"):
            url = url.replace("?page=1", "")
        if not url: continue
        low_url=url.lower()
        if any(block in low_url for block in ("/licitante/cadastro/login","/lotes/search","/leiloes/venda-direta","/login","/cadastro")) and "/item/" not in low_url: continue
        if "/leilao/" in low_url and "/lotes" in low_url and "/item/" not in low_url: continue
        external_id = parse_win_external_id_from_url(url) or external_id_from_url(url)
        if not external_id: continue
        loc = next((c for c in re.findall(r"\b([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s]{1,40}/[A-Za-z]{2})\b", card, flags=re.I) if "lote" not in c.lower()), None)
        city,state,location = parse_win_location(loc)
        raw_status = _strip_html(_first_group(r"(Online\s+Em\s+Andamento|Em\s+Andamento|Online\s+Em\s+Loteamento|Em\s+Loteamento|Encerrado)", card) or "") or None
        auction_date = _first_group(r"Data\s*:?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", card)
        first_lot_time = _first_group(r"Primeiro\s*lote\s*a\s*partir\s*das\s*:?\s*([0-9]{1,2}:[0-9]{2})", card)
        lots.append(NormalizedAuctionLot(source=SOURCE_KEY, external_id=external_id, title=title, url=url, item_type=infer_win_item_type(title, card), city=city, state=state, location=location, status=normalize_win_status(raw_status), auction_start_at=parse_datetime_br(f"{auction_date} {first_lot_time}" if auction_date and first_lot_time else auction_date), initial_bid=parse_money_br(_first_group(r"Lance\s*Inicial\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", card) or ""), current_bid=parse_money_br(_first_group(r"Lance\s*Atual\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", card) or ""), extras={"auction_date": auction_date, "first_lot_time": first_lot_time}, raw_payload={"html_card": card[:1000]}))
        if "/item/" in low_url and "/detalhes" in low_url:
            card_by_detail_url[url] = card
        if len(lots) >= limit:
            break

    existing_urls = {str(l.url or "") for l in lots}
    for detail_url in normalized_detail_urls:
        if len(lots) >= limit or detail_url in existing_urls:
            continue
        external_id = parse_win_external_id_from_url(detail_url) or external_id_from_url(detail_url)
        if not external_id:
            continue
        card = card_by_detail_url.get(detail_url, "")
        lots.append(
            NormalizedAuctionLot(
                source=SOURCE_KEY,
                external_id=external_id,
                title=None,
                url=detail_url,
                item_type="other",
                raw_payload={"html_card": card[:1000] if card else None},
            )
        )
    return lots

def fetch_win_lots(limit: int = 50, listing_url: str = DEFAULT_LISTING_URL, enrich: bool = False) -> list[NormalizedAuctionLot]:
    global _LAST_REASON, _LAST_FETCH_DIAGNOSTICS
    _LAST_REASON=None
    _LAST_FETCH_DIAGNOSTICS=None
    if not validate_auction_source_url(listing_url, ALLOWED_DOMAINS): _LAST_REASON="invalid_source_url"; return []
    with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent":"AutoHunter/1.0 (+experimental)"}) as client:
        resp = client.get(listing_url); resp.raise_for_status()
        lots = parse_win_listing_html(resp.text, limit=limit, listing_url=listing_url)
        _LAST_FETCH_DIAGNOSTICS = build_auction_source_fetch_diagnostics(resp, resp.text, listing_url)
        if enrich and lots:
            enriched = [_enrich_win_detail(client, l) for l in lots]
            enriched_useful = [l for l in enriched if l.title or l.initial_bid or l.current_bid or l.year]
            if not enriched_useful and any("/item/" in (str(l.url or "").lower()) and "/detalhes" in (str(l.url or "").lower()) for l in lots):
                _LAST_REASON = "detail_urls_found_but_enrich_failed"
                if _LAST_FETCH_DIAGNOSTICS is not None:
                    _LAST_FETCH_DIAGNOSTICS["reason"] = _LAST_REASON
            lots = enriched
    if lots: return lots
    diag = _LAST_FETCH_DIAGNOSTICS or {}
    html = (diag.get("html_preview") or "")
    hints = diag.get("hints") or {}
    r = "no_public_lot_cards_found"
    if any(k in html.lower() for k in ["login","cadastro","forbidden","access denied"]):
        r = "blocked_or_login_required"
    elif hints.get("lot_detail_candidates"):
        r = "parser_found_detail_urls"
    elif hints.get("has_script_tags") and hints.get("possible_js_app"):
        r = "no_detail_urls_found_requires_endpoint_study"
    _LAST_REASON=r
    if _LAST_FETCH_DIAGNOSTICS is not None:
        _LAST_FETCH_DIAGNOSTICS["reason"] = r
    return []
    def _parse_br_dt(raw: str) -> object | None:
        clean = (raw or "").strip()
        m = re.search(r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})(?:\s+([0-9]{1,2}:[0-9]{2}))?", clean)
        if m:
            d = m.group(1)
            t = m.group(2)
            if len(d.split("/")[-1]) == 2:
                d = f"{d[:-2]}20{d[-2:]}"
            if t:
                try:
                    return datetime.strptime(f"{d} {t}", "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            return parse_datetime_br(d)
        return parse_datetime_br(clean)
