from decimal import Decimal
from typing import Iterable

from app.models.wishlist_filter import WishlistFilter
from app.models.car_listing import CarListing


def text_match(query: str, listing: CarListing) -> bool:
    q = query.lower().strip()
    hay = " ".join([listing.title or "", listing.location or ""]).lower()
    terms = [t for t in q.split() if t]
    return all(t in hay for t in terms)


def apply_filters(filters: Iterable[WishlistFilter], listing: CarListing) -> bool:
    for f in filters:
        field = f.field
        op = f.operator
        val = f.value

        if field == "price":
            if listing.price is None:
                return False
            price = Decimal(listing.price)
            target = Decimal(val)

            if op == "lte" and not (price <= target): return False
            if op == "lt" and not (price < target): return False
            if op == "gte" and not (price >= target): return False
            if op == "gt" and not (price > target): return False
            if op == "eq" and not (price == target): return False
            if op == "neq" and not (price != target): return False

        elif field == "source":
            # val: "mercadolivre" ou "olx"
            if op == "eq" and not (listing.source == val): return False
            if op == "neq" and not (listing.source != val): return False

        else:
            # MVP: campo desconhecido não passa
            return False

    return True
