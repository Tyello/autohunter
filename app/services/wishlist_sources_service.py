from sqlalchemy.orm import Session
from app.models.wishlist_filter import WishlistFilter
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