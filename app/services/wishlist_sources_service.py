from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.models.wishlist_filter import WishlistFilter
from app.models.wishlist import Wishlist
from app.sources import list_sources


def allowed_sources_for_wishlist(db: Session, wishlist_id) -> set[str]:
    filters = (
        db.query(WishlistFilter)
        .filter(WishlistFilter.wishlist_id == wishlist_id)
        .all()
    )

    eq_sources = {f.value for f in filters if f.field == "source" and f.operator == "eq"}

    if eq_sources:
        return set(eq_sources)

    # defaults (MVP): todas as fontes "implementadas" (scrape != None)
    # que suportam monitoramento. Fontes SPA/placeholder ficam fora.
    return {p.name for p in list_sources() if p.supports_wishlist_monitoring and p.scrape is not None}


def allowed_sources_for_wishlists(db: Session, wishlists: Sequence[Wishlist]) -> dict:
    """Calcula allowed sources para várias wishlists com 1 query.

    Regra MVP:
    - Se houver algum filtro (field='source' and operator='eq'), só permite esses.
    - Caso contrário, libera as fontes padrão (plugins implementados e monitoráveis).

    Isso elimina N+1 queries no scheduler.
    """
    if not wishlists:
        return {}

    ids = [w.id for w in wishlists if getattr(w, "id", None)]
    if not ids:
        return {}

    defaults = {p.name for p in list_sources() if p.supports_wishlist_monitoring and p.scrape is not None}

    rows = (
        db.query(WishlistFilter)
        .filter(WishlistFilter.wishlist_id.in_(ids))
        .all()
    )
    eq_map = defaultdict(set)
    for f in rows or []:
        if (f.field or "") == "source" and (f.operator or "") == "eq" and f.value:
            eq_map[f.wishlist_id].add(f.value)

    out: dict = {}
    for w in wishlists:
        allowed = eq_map.get(w.id)
        out[w.id] = set(allowed) if allowed else set(defaults)

    return out


def get_eligible_wishlists_for_source(db: Session, source: str) -> tuple[list[Wishlist], dict[str, int]]:
    """Return only source-eligible active wishlists with operational stats.

    Eligibility rules:
    - inactive wishlists are excluded
    - wishlist with source eq filters only matches explicitly listed sources
    - wishlist without source eq filters is eligible only for default monitorable sources
    """
    src = (source or "").strip().lower()
    defaults = {p.name for p in list_sources() if p.supports_wishlist_monitoring and p.scrape is not None}

    source_filter_exists = exists().where(
        and_(
            WishlistFilter.wishlist_id == Wishlist.id,
            WishlistFilter.field == "source",
            WishlistFilter.operator == "eq",
        )
    )
    source_filter_matches = exists().where(
        and_(
            WishlistFilter.wishlist_id == Wishlist.id,
            WishlistFilter.field == "source",
            WishlistFilter.operator == "eq",
            WishlistFilter.value == src,
        )
    )

    if src in defaults:
        eligibility_predicate = or_(~source_filter_exists, source_filter_matches)
    else:
        eligibility_predicate = source_filter_matches

    total_wishlists = int(db.query(func.count(Wishlist.id)).scalar() or 0)
    active_wishlists = int(db.query(func.count(Wishlist.id)).filter(Wishlist.is_active.is_not(False)).scalar() or 0)

    eligible = (
        db.query(Wishlist)
        .options(joinedload(Wishlist.filters))
        .filter(Wishlist.is_active.is_not(False))
        .filter(eligibility_predicate)
        .all()
    )

    stats = {
        "total_wishlists": total_wishlists,
        "active_wishlists": active_wishlists,
        "eligible_wishlists": len(eligible),
        "filtered_by_disabled": max(0, total_wishlists - active_wishlists),
        "filtered_by_source_binding": max(0, active_wishlists - len(eligible)),
        "filtered_by_plan": 0,
        "filtered_by_user_state": 0,
    }
    return eligible, stats
