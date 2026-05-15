from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.text_norm import normalize, tokens
from app.models.auction_lot import AuctionLot
from app.models.wishlist import Wishlist
from app.services.matching_service import (
    _apply_filters_fast,
    _extract_city_state_from_location,
    _get_filters,
    _listing_city_state,
    _term_satisfied,
)


@dataclass(frozen=True)
class AuctionWishlistMatch:
    wishlist_id: str
    wishlist_query: str
    lot_id: str
    source: str
    title: str | None
    year: int | None
    mileage_km: int | None
    current_bid: Decimal | None
    status: str | None
    auction_end_at: object | None
    score: int
    reasons: list[str]
    risk_label: str = "auction"


_BAD_STATUSES = {"ended", "sold", "cancelled"}


def _lot_city_state(lot: AuctionLot) -> tuple[str | None, str | None]:
    city = normalize(getattr(lot, "city", None) or "") or None
    state = normalize(getattr(lot, "state", None) or "") or None
    if city and state:
        return city, state.upper()
    l_city, l_state = _extract_city_state_from_location(getattr(lot, "location", None))
    return city or l_city, (state.upper() if state else l_state)


def _wishlist_passes_on_lot(wishlist: Wishlist, lot: AuctionLot) -> bool:
    filters = _get_filters(wishlist)

    class _ListingLike:
        source = lot.source
        price = lot.current_bid
        year = lot.year
        mileage_km = lot.mileage_km
        doors = None
        color = getattr(lot, "color", None)
        seller_type = None
        body_type = None
        city, state = _lot_city_state(lot)
        location = lot.location

    # quick path for same filter contract as listings
    return _apply_filters_fast(_ListingLike(), filters, lot.year)


def _score_match(wishlist: Wishlist, lot: AuctionLot) -> tuple[int, list[str]]:
    q_tokens = [t for t in tokens(getattr(wishlist, "query", "") or "") if t]
    title_tokens = set(tokens((getattr(lot, "title", "") or "") + " " + (getattr(lot, "make", "") or "") + " " + (getattr(lot, "model", "") or "")))

    non_year_q = [t for t in q_tokens if not (len(t) == 4 and t.isdigit())]

    token_hits = sum(1 for t in non_year_q if _term_satisfied(t, title_tokens, lot.year))
    reasons: list[str] = []
    score = 0
    has_strong_text = False
    if token_hits:
        score += min(60, token_hits * 18)
        reasons.append(f"título contém {token_hits} termo(s) da busca")
        has_strong_text = True

    years = [int(t) for t in q_tokens if len(t) == 4 and t.isdigit()]
    if years and lot.year is not None and any(y == int(lot.year) for y in years):
        score += 12
        reasons.append("ano compatível")

    q_norm = normalize(getattr(wishlist, "query", "") or "")
    make = normalize(getattr(lot, "make", "") or "")
    model = normalize(getattr(lot, "model", "") or "")
    if make and make in q_norm:
        score += 10
        reasons.append("marca detectável")
        has_strong_text = True
    if model and model in q_norm:
        score += 8
        reasons.append("modelo detectável")
        has_strong_text = True

    status = (getattr(lot, "status", "") or "").lower().strip()
    if status in _BAD_STATUSES:
        score -= 20
        reasons.append(f"status penalizado ({status})")
    elif status:
        score += 6
        reasons.append(f"status {status}")

    if getattr(lot, "current_bid", None) is not None:
        score += 6
        reasons.append("lance atual disponível")

    if not has_strong_text:
        return 0, []
    return max(0, min(100, score)), reasons


def match_auction_lots_for_wishlist(db: Session, wishlist: Wishlist, source: str | None = None, limit: int = 10) -> list[AuctionWishlistMatch]:
    q = db.query(AuctionLot)
    if source:
        q = q.filter(AuctionLot.source == source)
    lots = q.order_by(AuctionLot.updated_at.desc()).limit(max(20, limit * 8)).all()

    out: list[AuctionWishlistMatch] = []
    for lot in lots:
        if not _wishlist_passes_on_lot(wishlist, lot):
            continue
        score, reasons = _score_match(wishlist, lot)
        if score <= 0:
            continue
        out.append(
            AuctionWishlistMatch(
                wishlist_id=str(wishlist.id),
                wishlist_query=wishlist.query,
                lot_id=str(lot.id),
                source=lot.source,
                title=lot.title,
                year=lot.year,
                mileage_km=lot.mileage_km,
                current_bid=lot.current_bid,
                status=lot.status,
                auction_end_at=lot.auction_end_at,
                score=score,
                reasons=reasons,
            )
        )

    out.sort(key=lambda m: m.score, reverse=True)
    return out[:limit]


def match_auction_lots_for_all_wishlists(db: Session, source: str | None = None, limit_per_wishlist: int = 5) -> dict[str, list[AuctionWishlistMatch]]:
    wishlists = db.query(Wishlist).filter(Wishlist.is_active.is_(True)).all()
    result: dict[str, list[AuctionWishlistMatch]] = {}
    for w in wishlists:
        matches = match_auction_lots_for_wishlist(db, w, source=source, limit=limit_per_wishlist)
        if matches:
            result[str(w.id)] = matches
    return result
