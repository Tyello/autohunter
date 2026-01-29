from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from sqlalchemy.orm import Session

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