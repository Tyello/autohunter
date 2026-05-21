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

_QUERY_STOPWORDS = {
    "ate",
    "entre",
    "de",
    "do",
    "da",
    "com",
    "em",
    "para",
    "flex",
}

_SHORT_AUTOMOTIVE_TOKENS = {
    "si", "gti", "gli", "x1", "x3", "x5", "c3", "c4", "208", "308", "l200", "s10", "q3", "a3", "a5",
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
    relevant_q_tokens = [t for t in non_year_q if t not in _QUERY_STOPWORDS and (len(t) > 1 or t in _SHORT_AUTOMOTIVE_TOKENS)]

    matched_tokens = [t for t in relevant_q_tokens if _term_satisfied(t, title_tokens, lot.year)]
    missing_tokens = [t for t in relevant_q_tokens if t not in matched_tokens]
    token_hits = len(matched_tokens)
    reasons: list[str] = []
    score = 0
    has_strong_text = False
    scoring_reason = "no_strong_text"
    if token_hits:
        score += min(60, token_hits * 18)
        reasons.append(f"título contém {token_hits} termo(s) da busca")
        has_strong_text = True
        scoring_reason = "token_overlap"

    q_norm = normalize(getattr(wishlist, "query", "") or "")
    title_norm = normalize((getattr(lot, "title", "") or "") + " " + (getattr(lot, "make", "") or "") + " " + (getattr(lot, "model", "") or ""))
    phrase_tokens = [t for t in tokens(q_norm) if t in relevant_q_tokens]
    phrase_norm = " ".join(phrase_tokens).strip()
    phrase_in_title = bool(phrase_norm and phrase_norm in title_norm)
    phrase_boost_allowed = phrase_in_title and (
        any(t in _SHORT_AUTOMOTIVE_TOKENS for t in phrase_tokens)
        or any(any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t) for t in phrase_tokens)
        or len(phrase_tokens) >= 3
    )
    if phrase_boost_allowed:
        score = max(score, 85)
        has_strong_text = True
        scoring_reason = "query_phrase_in_title"
        reasons.append("frase da busca detectada no título")

    if relevant_q_tokens and not missing_tokens:
        score = max(score, 70)
        has_strong_text = True
        if scoring_reason == "token_overlap":
            scoring_reason = "all_query_tokens_in_title"
        reasons.append("todos os termos relevantes da busca presentes")

    has_alnum_token = any(any(ch.isdigit() for ch in t) and any(ch.isalpha() for ch in t) for t in matched_tokens)
    if has_alnum_token and token_hits >= 2:
        score = max(score, 80)
        has_strong_text = True
        if scoring_reason != "query_phrase_in_title":
            scoring_reason = "alnum_plus_strong_token"
        reasons.append("token alfanumérico com suporte de termo forte")

    if has_alnum_token and token_hits >= 1 and len(relevant_q_tokens) >= 2:
        score = max(score, 65)
        has_strong_text = True
        if scoring_reason == "token_overlap":
            scoring_reason = "alnum_model_token_present"
        reasons.append("modelo alfanumérico relevante detectado")


    has_short_auto_token = any(t in _SHORT_AUTOMOTIVE_TOKENS for t in matched_tokens)
    if has_short_auto_token and token_hits >= 1 and len(relevant_q_tokens) >= 2:
        score = max(score, 65)
        has_strong_text = True
        if scoring_reason == "token_overlap":
            scoring_reason = "short_auto_token_present"
        reasons.append("token automotivo curto relevante detectado")
    non_generic_single_term = len(relevant_q_tokens) == 1 and relevant_q_tokens[0] not in _GENERIC_SINGLE_TERM_TOKENS
    if non_generic_single_term and relevant_q_tokens[0] in title_tokens:
        score = max(score, 60)
        reasons.append("match forte de modelo/termo único")
        has_strong_text = True
        if scoring_reason == "no_strong_text":
            scoring_reason = "single_model_term"

    years = [int(t) for t in q_tokens if len(t) == 4 and t.isdigit()]
    if years and lot.year is not None and any(y == int(lot.year) for y in years):
        score += 12
        reasons.append("ano compatível")

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
    reasons.append(f"scoring_reason={scoring_reason}")
    reasons.append(f"matched_tokens={matched_tokens}")
    reasons.append(f"missing_tokens={missing_tokens}")
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
