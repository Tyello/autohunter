from __future__ import annotations
import re

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter


@dataclass(frozen=True)
class FilterRule:
    field: str
    operator: str
    value: str


def _normalize_terms(query: str) -> list[str]:
    return [t.strip().lower() for t in (query or "").split() if t.strip()]


def _parse_decimal(value: str) -> Decimal | None:
    """
    Aceita:
      - "90000"
      - "90000.00"
      - "90.000,00" (pt-BR)
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


def text_match(query: str, listing: CarListing) -> bool:
    q = (query or "").lower().strip()
    terms = [t for t in q.split() if t]
    if not terms:
        return True

    # inclui URL porque às vezes o título vem vazio mas a URL tem o slug
    hay = " ".join([
        listing.title or "",
        listing.location or "",
        listing.url or "",
    ]).lower()

    # normaliza separadores comuns
    hay = re.sub(r"[-_/]+", " ", hay)

    return all(t in hay for t in terms)


def _apply_filters(listing: CarListing, filters: list[FilterRule]) -> bool:
    """
    MVP suportado:
      - source eq <valor>
      - price lte <valor>
      - price gte <valor>
    """
    for f in filters:
        field = (f.field or "").lower()
        op = (f.operator or "").lower()
        val = (f.value or "").strip()

        if field == "source":
            if op != "eq":
                # operador não suportado → ignora (MVP)
                continue
            if not listing.source:
                return False
            if listing.source.lower() != val.lower():
                return False

        elif field == "price":
            price = getattr(listing, "price", None)
            if price is None:
                return False

            target = _parse_decimal(val)
            if target is None:
                return False

            # price pode ser Decimal vindo do Numeric
            if op == "lte":
                if price > target:
                    return False
            elif op == "gte":
                if price < target:
                    return False
            else:
                continue  # operador desconhecido → ignora no MVP

        else:
            # campo não suportado no MVP → ignora
            continue

    return True


def _get_filters(wishlist: Wishlist) -> list[FilterRule]:
    # usa relationship se já carregou
    if getattr(wishlist, "filters", None) is not None:
        raw = list(wishlist.filters)
    else:
        raw = []

    return [FilterRule(f.field, f.operator, f.value) for f in raw]


def match_listings_for_wishlist(
    db: Session,
    wishlist: Wishlist,
    inserted_ids: Iterable,
) -> list[CarListing]:
    """
    Retorna os listings NOVOS (inserted_ids) que:
      - passam nos filtros da wishlist (price + source)
      - batem no texto de wishlist.query
    """
    ids = list(inserted_ids or [])
    if not ids:
        return []

    listings = db.query(CarListing).filter(CarListing.id.in_(ids)).all()

    filters = _get_filters(wishlist)
    terms = _normalize_terms(wishlist.query)

    matched: list[CarListing] = []
    for l in listings:
        if not _apply_filters(l, filters):
            continue
        if not text_match(l, terms):
            continue
        matched.append(l)

    return matched
