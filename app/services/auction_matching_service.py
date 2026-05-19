from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.text_norm import normalize, tokens
from app.models.auction_lot import AuctionLot
from app.models.wishlist import Wishlist
from app.services.auction_source_categories_service import get_auction_allowed_item_types, normalize_item_type
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
    initial_bid: Decimal | None
    total_bids: int | None
    status: str | None
    auction_end_at: object | None
    city: str | None
    state: str | None
    url: str | None
    score: int
    reasons: list[str]
    risk_label: str = "auction"


def _auction_alert_rank_score(match: AuctionWishlistMatch) -> int:
    bonus = 0
    if getattr(match, "current_bid", None) is not None:
        bonus += 10
    if getattr(match, "initial_bid", None) is not None:
        bonus += 5
    if getattr(match, "auction_end_at", None) is not None:
        bonus += 3
    return int(getattr(match, "score", 0) or 0) + bonus


def _dt_value(value: object | None) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.min


def sort_auction_matches_for_alerting(matches: list[AuctionWishlistMatch]) -> list[AuctionWishlistMatch]:
    return sorted(
        matches,
        key=lambda m: (
            _auction_alert_rank_score(m),
            1 if getattr(m, "current_bid", None) is not None else 0,
            1 if getattr(m, "initial_bid", None) is not None else 0,
            1 if getattr(m, "auction_end_at", None) is not None else 0,
            _dt_value(getattr(m, "auction_end_at", None)),
            1 if bool(getattr(m, "url", None)) else 0,
            _dt_value(getattr(m, "updated_at", None)),
            _dt_value(getattr(m, "created_at", None)),
        ),
        reverse=True,
    )


_BAD_STATUSES = {"ended", "sold", "cancelled"}
_GENERIC_SINGLE_TERM_TOKENS = {
    "carro",
    "carros",
    "automatico",
    "automatic",
    "manual",
    "completo",
    "basico",
    "flex",
    "1.0",
    "2.0",
}


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

    non_generic_single_term = len(non_year_q) == 1 and non_year_q[0] not in _GENERIC_SINGLE_TERM_TOKENS
    if non_generic_single_term and non_year_q[0] in title_tokens:
        score = max(score, 60)
        reasons.append("match forte de modelo/termo único")
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


def match_auction_lots_for_wishlist(
    db: Session,
    wishlist: Wishlist,
    source: str | None = None,
    limit: int = 10,
    eligible_sources: set[str] | None = None,
) -> list[AuctionWishlistMatch]:
    q = db.query(AuctionLot)
    if source:
        q = q.filter(AuctionLot.source == source)
    if eligible_sources is not None:
        q = q.filter(AuctionLot.source.in_(sorted(eligible_sources)))
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
                initial_bid=lot.initial_bid,
                total_bids=lot.total_bids,
                status=lot.status,
                auction_end_at=lot.auction_end_at,
                city=lot.city,
                state=lot.state,
                url=lot.url,
                score=score,
                reasons=reasons,
            )
        )

    out = sort_auction_matches_for_alerting(out)
    return out[:limit]


def debug_auction_lot_candidates_for_wishlist(
    db: Session,
    wishlist: Wishlist,
    *,
    source: str | None = None,
    eligible_sources: set[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    q = db.query(AuctionLot)
    if source:
        q = q.filter(AuctionLot.source == source)
    if eligible_sources is not None:
        q = q.filter(AuctionLot.source.in_(sorted(eligible_sources)))
    lots = q.order_by(AuctionLot.updated_at.desc()).limit(max(20, limit * 8)).all()

    rows: list[dict] = []
    for lot in lots:
        lot_item_type = normalize_item_type(getattr(lot, "item_type", None))
        allowed_item_types = sorted(get_auction_allowed_item_types(db, lot.source))
        passes_filters = _wishlist_passes_on_lot(wishlist, lot)
        score, reasons = _score_match(wishlist, lot)
        if lot_item_type is not None and lot_item_type not in set(allowed_item_types):
            reject_reason = "item_type_not_allowed"
        elif not passes_filters:
            reject_reason = "filters_not_matched"
        elif score <= 0:
            reject_reason = "text_score_zero"
        else:
            reject_reason = "ok"
        rows.append(
            {
                "source": lot.source,
                "external_id": lot.external_id,
                "title": lot.title,
                "item_type": lot.item_type,
                "item_type_normalized": lot_item_type,
                "allowed_item_types": allowed_item_types,
                "year": lot.year,
                "current_bid": lot.current_bid,
                "updated_at": lot.updated_at,
                "passes_filters": passes_filters,
                "score": score,
                "reasons": reasons,
                "reject_reason": reject_reason,
            }
        )
    return rows[: max(1, limit)]


def match_auction_lots_for_all_wishlists(
    db: Session,
    source: str | None = None,
    limit_per_wishlist: int = 5,
    include_auctions_only: bool = True,
    eligible_sources: set[str] | None = None,
) -> dict[str, list[AuctionWishlistMatch]]:
    wishlists_q = db.query(Wishlist).filter(Wishlist.is_active.is_(True))
    if include_auctions_only:
        wishlists_q = wishlists_q.filter(Wishlist.include_auctions.is_(True))
    wishlists = wishlists_q.all()
    result: dict[str, list[AuctionWishlistMatch]] = {}
    for w in wishlists:
        matches = match_auction_lots_for_wishlist(
            db, w, source=source, limit=limit_per_wishlist, eligible_sources=eligible_sources
        )
        if matches:
            result[str(w.id)] = matches
    return result
