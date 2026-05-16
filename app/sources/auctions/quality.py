from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.sources.auctions.base import NormalizedAuctionLot


@dataclass
class AuctionLotQualityResult:
    ok: bool
    reason: str | None = None


_INVALID_TITLE_VALUES = {"sem título", "sem titulo", "-", "none"}
_INSTITUTIONAL_TITLE_TERMS = {
    "navegue pelas categorias",
    "navegue pelas modalidades",
    "agentes de venda autorizados",
    "entrar",
    "login",
    "cadastro",
    "minha conta",
    "favoritos",
    "venda direta",
    "search",
    "política",
    "politica",
    "termos",
    "institucional",
}
_BLOCKED_URL_PARTS = {
    "/login",
    "/cadastro",
    "/licitante/cadastro",
    "/lotes/search",
    "/leiloes/venda-direta",
    "/categorias/",
    "/leilao/todos",
    "/todos-eventos",
    "/wp-content/",
    "/account",
    "/favoritos",
}


def _normalize(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _is_valid_url(url: str | None) -> bool:
    if not url:
        return False
    candidate = url.strip()
    if not candidate or candidate == "-":
        return False
    parsed = urlparse(candidate)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_normalized_auction_lot_candidate(lot: NormalizedAuctionLot) -> AuctionLotQualityResult:
    if not (lot.source or "").strip():
        return AuctionLotQualityResult(ok=False, reason="missing_source")

    if not (lot.external_id or "").strip():
        return AuctionLotQualityResult(ok=False, reason="missing_external_id")

    if not _is_valid_url(lot.url):
        return AuctionLotQualityResult(ok=False, reason="invalid_url")

    normalized_url = _normalize(lot.url)
    if any(part in normalized_url for part in _BLOCKED_URL_PARTS):
        return AuctionLotQualityResult(ok=False, reason="institutional_url")
    if ".pdf" in normalized_url or "blog.superbid.net" in normalized_url:
        return AuctionLotQualityResult(ok=False, reason="pdf_or_blog_url")

    normalized_title = _normalize(lot.title)
    if not normalized_title:
        return AuctionLotQualityResult(ok=False, reason="missing_title")

    if normalized_title in _INVALID_TITLE_VALUES:
        return AuctionLotQualityResult(ok=False, reason="invalid_title")

    if any(term in normalized_title for term in _INSTITUTIONAL_TITLE_TERMS):
        return AuctionLotQualityResult(ok=False, reason="institutional_title")
    if normalized_title in {"canais", "sobre nós", "sobre nos"}:
        return AuctionLotQualityResult(ok=False, reason="institutional_title")
    if normalized_title.startswith("lance inicial:"):
        return AuctionLotQualityResult(ok=False, reason="title_is_bid_label")
    if any(
        term in normalized_title
        for term in (
            "superbid exchange - leilões",
            "superbid exchange - leiloes",
            "leilões de motos, carros, caminhões",
            "leiloes de motos, carros, caminhoes",
            "os melhores especialistas em trade",
        )
    ):
        return AuctionLotQualityResult(ok=False, reason="institutional_title")

    has_strong_signal = any(
        [
            lot.year is not None,
            lot.current_bid is not None,
            lot.initial_bid is not None,
            lot.auction_end_at is not None,
            bool((lot.lot_number or "").strip()),
        ]
    )
    allow_city_state_only = (lot.source or "").strip() in {"vip_auctions", "mega_auctions"}
    has_city_state_support = any(
        [
            bool((lot.city or "").strip()),
            bool((lot.state or "").strip()),
            lot.mileage_km is not None,
        ]
    )
    if not has_strong_signal and not (allow_city_state_only and has_city_state_support):
        return AuctionLotQualityResult(ok=False, reason="insufficient_lot_signals")

    return AuctionLotQualityResult(ok=True)
