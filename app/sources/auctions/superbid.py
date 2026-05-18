from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

import httpx

from app.sources.auctions.base import NormalizedAuctionLot
from app.sources.auctions.parsing import absolute_url, external_id_from_url, normalize_title, parse_datetime_br, parse_money_br, parse_year_from_title

SOURCE_KEY = "superbid_auctions"
DEFAULT_LISTING_URL = "https://www.superbid.net/"
ALLOWED_DOMAINS = {"superbid.net", "www.superbid.net", "exchange.superbid.net"}
VALID_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
}

_LAST_REASON: str | None = None


def get_last_reason() -> str | None:
    return _LAST_REASON


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.I | re.S)
    return m.group(1).strip() if m else None


def _valid_source_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ALLOWED_DOMAINS


def normalize_superbid_status(text: str | None) -> str:
    low = (text or "").lower()
    if "em andamento" in low or "ao vivo" in low:
        return "live"
    if "pós-leilão" in low or "pos-leilao" in low or "pós leilão" in low:
        return "post_auction"
    if "mercado balc" in low or "compre j" in low:
        return "buy_now"
    if "tomada de pre" in low:
        return "quote"
    if "encerr" in low:
        return "ended"
    if "leil" in low and "aberto" in low:
        return "open"
    if "leil" in low:
        return "open"
    return "unknown"


def parse_superbid_location(raw: str | None) -> tuple[str | None, str | None, str | None]:
    clean = _strip_html(raw or "").strip(" :-,")
    if not clean:
        return None, None, None
    m = re.search(r"^(.+?)\s*(?:/|,|-)\s*([A-Za-z]{2})$", clean)
    if not m:
        return clean, None, clean
    city = m.group(1).strip()
    state = m.group(2).upper()
    return city, (state if state in VALID_UFS else None), clean


def infer_superbid_item_type(*texts: str | None) -> str:
    text = " ".join([x for x in texts if x]).lower()
    if any(k in text for k in ("motocicleta", " cg ", " cb ", "xre", "biz", "pcx", "fazer", "lander")) or re.search(r"\bmoto\b", text):
        return "motorcycle"
    if any(k in text for k in ("caminh", "ônibus", "onibus", "pesados")):
        return "truck"
    if any(k in text for k in ("máquinas pesadas", "maquinas pesadas", "agrícolas", "agricolas", "carregadeira", "escavadeira")):
        return "heavy_machinery"
    if any(k in text for k in ("carros", "carro", "auto", "veículo", "veiculo", "leves")):
        return "car"
    return "other"


def extract_superbid_external_id(url: str | None) -> str | None:
    if not url:
        return None
    p = urlparse(url)
    path = p.path.rstrip("/")
    slug = (path.split("/")[-1] if path else "").lower()
    nums = re.findall(r"\d{2,}", path)
    if nums:
        return nums[-1]
    if slug:
        return slug
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def filter_superbid_images(urls: list[str], listing_url: str) -> list[str]:
    out: list[str] = []
    for raw in urls:
        abs_url = urljoin(listing_url, raw)
        low = abs_url.lower()
        if any(x in low for x in ("logo", "icon", "banner", "sprite", "institucional")):
            continue
        if not re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", low):
            continue
        out.append(abs_url)
    return list(dict.fromkeys(out))


def _extract_superbid_candidate_blocks(html: str) -> list[str]:
    class_blocks = [blk for _, blk in re.findall(r'<(article|div)[^>]*class="[^"]*(?:card|lot|item|leilao|lote|event|product|asset)[^"]*"[^>]*>(.*?)</\1>', html, flags=re.I | re.S)]
    if class_blocks:
        return class_blocks

    keywords = r"carros|motos|caminh|onibus|ônibus|leilao|leilão|lote|lotes|item|asset|event"
    blocked = r"login|cadastro|ajuda|contato|sobre|privacidade|termos|pol[ií]tica|institucional|favoritos|minha-conta|account"
    blocks: list[str] = []
    seen: set[str] = set()
    for a in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=re.I | re.S):
        href = (a.group(1) or "").strip()
        anchor_text = _strip_html(a.group(2) or "")
        blob = f"{href} {anchor_text}"
        if re.search(blocked, blob, flags=re.I):
            continue
        if not re.search(keywords, blob, flags=re.I):
            continue
        if href in seen:
            continue
        seen.add(href)
        start = max(0, a.start() - 2000)
        end = min(len(html), a.end() + 2000)
        blocks.append(html[start:end])
    return blocks


def parse_superbid_listing_html(html: str, limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    blocks = _extract_superbid_candidate_blocks(html)
    lots: list[NormalizedAuctionLot] = []
    seen: set[str] = set()
    blocked = r"login|cadastro|ajuda|contato|sobre|privacidade|termos|pol[ií]tica|institucional|favoritos|minha-conta|account"
    href_signal = r"carros|motos|caminh|onibus|ônibus|leilao|leilão|lote|lotes|item|asset|event|\d{2,}"
    for card in blocks:
        href = None
        for candidate in re.findall(r'href=["\']([^"\']+)["\']', card, flags=re.I):
            blob = candidate.lower()
            if re.search(blocked, blob, flags=re.I):
                continue
            if re.search(href_signal, blob, flags=re.I):
                href = candidate
                break
        if not href:
            href = _first_group(r'href=["\']([^"\']+)["\']', card)
        if not href:
            continue
        url = urljoin(listing_url, href)
        lower_url = url.lower()
        if any(
            blocked_url in lower_url
            for blocked_url in ("/categorias/", "/leilao/todos", "/todos-eventos", "/wp-content/", "/lotes/search", "/leiloes/venda-direta")
        ):
            continue
        if ".pdf" in lower_url or "blog.superbid.net" in lower_url:
            continue
        ext = extract_superbid_external_id(url)
        if not ext:
            continue
        dedupe = f"{url}|{ext}"
        if dedupe in seen:
            continue
        seen.add(dedupe)

        title = _strip_html(_first_group(r"<h[1-6][^>]*>(.*?)</h[1-6]>", card) or "")
        full_text = _strip_html(card)
        if not title:
            inferred_title = _first_group(r"([A-Za-zÀ-ÿ0-9\-\s]{6,120}\b(?:19\d{2}|20\d{2})\b)", full_text)
            title = _strip_html(inferred_title or "") or _strip_html(_first_group(r"<a[^>]*>(.*?)</a>", card) or "")
        blocked_titles = {
            "agentes de venda autorizados",
            "navegue pelas categorias",
            "navegue pelas modalidades de vendas",
        }
        lower_title = (title or "").strip().lower()
        if any(blocked in lower_title for blocked in blocked_titles) or any(
            blocked in lower_title
            for blocked in (
                "superbid exchange - leilões",
                "superbid exchange - leiloes",
                "canais",
                "sobre nós",
                "sobre nos",
                "os melhores especialistas em trade",
            )
        ):
            continue
        category = _first_group(r"(?:categoria)\s*:?\s*([^<\n|]+)", card)
        modality = _first_group(r"(?:modalidade)\s*:?\s*([^<\n|]+)", card)
        raw_status = _first_group(r"(?:status)\s*:?\s*([^<\n|]+)", card) or _first_group(r"\b(Em andamento|Ao vivo|Leilão aberto|Pós-leilão|Mercado Balcão|Compre Já|Tomada de Preço|Encerrado)\b", full_text)
        raw_location = _first_group(r"(?:local)\s*:?\s*([^<\n|]+)", card) or _first_group(r"([A-Za-zÀ-ÿ\s]+(?:/|,|-)\s*[A-Za-z]{2})", full_text)
        city, state, location = parse_superbid_location(raw_location)

        initial_raw = _first_group(r"(?:Lance\s*inicial|Valor\s*inicial|Lance\s*m[ií]nimo|Pre[cç]o\s*inicial)\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", card)
        current_raw = _first_group(r"(?:Lance\s*atual|Maior\s*lance|Valor\s*atual|Oferta\s*atual)\s*:?\s*(R\$\s*[0-9.]+,[0-9]{2})", card)
        start_raw = _first_group(r"(?:In[ií]cio|Abertura|Data\s*do\s*leil[aã]o|Come[cç]a\s*em)\s*:?\s*([^<\n]+)", card)
        end_raw = _first_group(r"(?:Encerra|Encerramento|T[eé]rmino|Finaliza\s*em)\s*:?\s*([^<\n]+)", card)
        lot_number = _first_group(r"\bLote\s*: ?\s*(\d+)\b", card) or _first_group(r"\bLote\s+(\d+)\b", card)
        if "/evento/" in lower_url:
            has_event_signal = any([
                bool(start_raw or end_raw),
                bool(initial_raw or current_raw),
                bool(raw_status),
                bool(raw_location),
                bool(parse_year_from_title(title)),
                bool(lot_number),
            ])
            if not has_event_signal:
                continue

        imgs = filter_superbid_images(re.findall(r"<(?:img|source)[^>]+(?:src|data-src)=[\"']([^\"']+)[\"']", card, flags=re.I), listing_url)
        make = title.split()[0] if title else None

        extras = {
            "raw_status": raw_status,
            "raw_location": location,
            "source_category": _strip_html(category or "") or None,
            "listing_kind": "auction_lot",
            "modality": _strip_html(modality or "") or None,
            "event_title": title or None,
            "start_date": start_raw or None,
            "end_date": end_raw or None,
        }

        lots.append(NormalizedAuctionLot(
            source=SOURCE_KEY,
            external_id=ext,
            title=title or None,
            url=url,
            lot_number=lot_number,
            item_type=infer_superbid_item_type(title, category, modality, full_text),
            make=make,
            year=parse_year_from_title(title),
            city=city,
            state=state,
            location=location,
            initial_bid=parse_money_br(initial_raw),
            current_bid=parse_money_br(current_raw),
            status=normalize_superbid_status((raw_status or "") + " " + (modality or "")),
            auction_start_at=parse_datetime_br(start_raw),
            auction_end_at=parse_datetime_br(end_raw),
            thumbnail_url=(imgs[0] if imgs else None),
            images=imgs or None,
            extras={k: v for k, v in extras.items() if v is not None},
            raw_payload={"html_card": card[:1000]},
        ))
        if len(lots) >= limit:
            break
    return lots


def fetch_superbid_lots(limit: int = 50, listing_url: str = DEFAULT_LISTING_URL) -> list[NormalizedAuctionLot]:
    global _LAST_REASON
    _LAST_REASON = None
    if not _valid_source_url(listing_url):
        _LAST_REASON = "invalid_source_url"
        return []
    with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as c:
        resp = c.get(listing_url)
        resp.raise_for_status()
    lots = parse_superbid_listing_html(resp.text, limit=limit, listing_url=listing_url)
    if lots:
        return lots
    if ("exchange.superbid.net" in listing_url) or re.search(r"__NEXT_DATA__|react-root|vue|angular|api", resp.text, flags=re.I):
        _LAST_REASON = "requires_js_or_internal_endpoint"
    else:
        _LAST_REASON = "no_public_lot_cards_found"
    return []
