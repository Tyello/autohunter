from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.wishlist import Wishlist
from app.services.auction_matching_service import AuctionWishlistMatch, match_auction_lots_for_all_wishlists, match_auction_lots_for_wishlist


@dataclass(frozen=True)
class AuctionPreviewResult:
    matches: list[AuctionWishlistMatch]
    warning: str | None = None


def build_auction_alert_previews_for_enabled_wishlists(
    db: Session, source: str | None = None, limit: int = 5, eligible_sources: set[str] | None = None
) -> list[AuctionWishlistMatch]:
    by = match_auction_lots_for_all_wishlists(
        db, source=source, limit_per_wishlist=limit, include_auctions_only=True, eligible_sources=eligible_sources
    )
    all_matches: list[AuctionWishlistMatch] = []
    for matches in by.values():
        all_matches.extend(matches)
    all_matches.sort(key=lambda m: m.score, reverse=True)
    return all_matches[:limit]


def build_auction_alert_previews_for_wishlist(
    db: Session,
    wishlist_id,
    force: bool = False,
    source: str | None = None,
    limit: int = 5,
    eligible_sources: set[str] | None = None,
) -> AuctionPreviewResult:
    try:
        target_id = wishlist_id if isinstance(wishlist_id, uuid.UUID) else uuid.UUID(str(wishlist_id))
    except Exception:
        return AuctionPreviewResult(matches=[], warning="Wishlist não encontrada.")

    wishlist = db.query(Wishlist).filter(Wishlist.id == target_id).first()
    if not wishlist:
        return AuctionPreviewResult(matches=[], warning="Wishlist não encontrada.")
    if not force and not bool(getattr(wishlist, "include_auctions", False)):
        return AuctionPreviewResult(
            matches=[],
            warning=(
                f"Esta busca não está habilitada para leilões. Use /admin auctions wishlist {wishlist.id} enable para habilitar "
                "ou rode com --force para diagnóstico."
            ),
        )
    matches = match_auction_lots_for_wishlist(db, wishlist, source=source, limit=limit, eligible_sources=eligible_sources)
    return AuctionPreviewResult(matches=matches, warning=None)
