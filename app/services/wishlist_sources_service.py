from sqlalchemy.orm import Session
from app.models.wishlist_filter import WishlistFilter


def allowed_sources_for_wishlist(db: Session, wishlist_id) -> set[str]:
    filters = (
        db.query(WishlistFilter)
        .filter(WishlistFilter.wishlist_id == wishlist_id)
        .all()
    )

    eq_sources = {f.value for f in filters if f.field == "source" and f.operator == "eq"}

    if eq_sources:
        return set(eq_sources)

    return {"mercadolivre", "olx"}