from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Iterable
from urllib.parse import urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.diagnostics import build_auction_source_fetch_diagnostics
from app.sources.auctions.parsing import absolute_url, external_id_from_url, normalize_item_type, normalize_title, parse_datetime_br, parse_int_br, parse_money_br, parse_year_from_title

SOURCE_KEY = "win_auctions"
DEFAULT_LISTING_URL = "https://www.winleiloes.com.br/lotes/veiculo?tipo=veiculo&categoria_id=8"
ALLOWED_DOMAINS = {"winleiloes.com.br", "www.winleiloes.com.br"}
VALID_UFS = {"AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"}
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
    if "andamento" in v: return "live"
    if "loteamento" in v: return "scheduled"
    if "encerrado" in v: return "ended"
    return "unknown"

def parse_win_location(text: str | None) -> tuple[str | None, str | None, str | None]:
    if not text: return None, None, None
    clean = _strip_html(text).strip(" :,-")
    m = re.search(r"^(.+?)\s*/\s*([A-Za-z]{2})$", clean)
    if not m: return clean or None, None, clean or None
    city, state = m.group(1).strip(), m.group(2).upper()
    city_l = city.lower()
    invalid = city_l in {"com","www","http","https"} or "." in city_l or "/" in city_l or len(city_l) < 3
    if invalid: city = None
    st = state if state in VALID_UFS else None
    if city and st: return city, st, f"{city}/{st}"
    if st: return None, st, st
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
    if any(k in txt for k in ("imóvel","imovel","terreno","casa","apartamento","prédio","predio","propriedade rural","fazenda","sítio","sitio")): return "real_estate"
    if any(k in txt for k in ("moto"," cg "," biz "," fan "," titan")): return "motorcycle"
    if any(k in txt for k in ("caminh","ônibus","onibus")): return "truck"
    if any(k in txt for k in ("pesad","carreta","bitrem")): return "heavy"
    if any(k in txt for k in ("suv","pickup","caminhonete","utilit","carro","automóvel","automovel","veículo leve","veiculo leve","sedan","hatch")): return "car"
    if re.search(r"\b(volkswagen|vw|chevrolet|fiat|ford|toyota|honda|hyundai|renault|jeep|nissan|peugeot|citroen)\b", txt):
        return "car"
    if any(k in txt for k in ("máquina","maquina")): return "heavy"
    if any(k in txt for k in ("imóvel","imovel","apartamento","terreno","casa")): return "real_estate"
    if any(k in txt for k in ("carro","automóvel","automovel","veículo leve","veiculo leve","sedan","hatch","suv","pickup")): return "car"
    return normalize_item_type(txt)

def _valid_win_title(title: str | None) -> str | None:
    if not title: return None
    low = title.strip().lower()
    if low in {"lance inicial","descrição","descricao","bem","lote"} or low.startswith("lance inicial:"): return None
    if re.fullmatch(r"[a-zà-ÿ\s]{2,40}/[a-z]{2}", low): return None
    if re.fullmatch(r"[a-zà-ÿ\s]{2,30}", low) and low in {"descrição do lote","informações do lote","informacoes do lote"}: return None
    return title

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
    current_bid = lot.current_bid or parse_money_br(_first_group(r"Lance\s*Atual\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", html) or "")
    clean_html = _strip_html(html)
    item_type = infer_win_item_type(title, clean_html, lot.item_type)
    year = lot.year
    if item_type in {"car", "motorcycle", "truck", "heavy"}:
        year = year or parse_year_from_title(" ".join([title or "", clean_html]))
    elif item_type == "real_estate":
        year = None
    mileage = parse_int_br(_first_group(r"([0-9.]{2,7})\s*km", html) or "")
    raw_loc = _first_group(r"([A-Za-zÀ-ÿ\s]{2,40}/[A-Za-z]{2})", html)
    city, state, location = parse_win_location(raw_loc or lot.location)
    status = normalize_win_status(_first_group(r"(Online\s+Em\s+Andamento|Em\s+Andamento|Online\s+Em\s+Loteamento|Em\s+Loteamento|Encerrado)", html) or lot.status)
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
        city=city or lot.city,
        state=state or lot.state,
        location=location or lot.location,
        status=status,
        item_type=item_type,
        thumbnail_url=lot.thumbnail_url or (imgs[0] if imgs else None),
        images=lot.images or (imgs or None),
        extras=extras,
    )

def parse_win_listing_html(html: str, limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    cards = re.findall(r'<article[^>]*class="[^"]*(?:card|item|lot|leilao)[^"]*"[^>]*>(.*?)</article>', html, flags=re.I | re.S) or re.findall(r'<div[^>]*class="[^"]*(?:card|item|lot|leilao)[^"]*"[^>]*>(.*?)</div>', html, flags=re.I | re.S)
    lots=[]
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
        if len(lots)>=limit: break
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
        if enrich and lots: lots=[_enrich_win_detail(client, l) for l in lots]
    if lots: return lots
    html = (_LAST_FETCH_DIAGNOSTICS or {}).get("html_preview","")
    r = "no_public_lot_cards_found"
    if any(k in html.lower() for k in ["login","cadastro","forbidden","access denied"]):
        r = "blocked_or_login_required"
    elif any(k in html.lower() for k in ["__next_data__","react","webpack"]):
        r = "requires_js_or_endpoint_study"
    _LAST_REASON=r
    if _LAST_FETCH_DIAGNOSTICS is not None:
        _LAST_FETCH_DIAGNOSTICS["reason"] = r
    return []
