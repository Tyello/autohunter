from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.text_norm import tokens
from app.models.car_listing import CarListing
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.wishlist_semantic_rules import semantic_match


@dataclass(frozen=True)
class FilterRule:
    field: str
    operator: str
    value: str


def _parse_decimal(value: str) -> Decimal | None:
    """Aceita:
      - "90000"
      - "90000.00"
      - "90.000,00" (pt-BR)
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


def _extract_year(listing: CarListing) -> int | None:
    # se o model já tiver year, usa
    y = getattr(listing, "year", None)
    try:
        if y is not None:
            y = int(y)
            if 1900 <= y <= 2100:
                return y
    except Exception:
        pass

    # fallback: parse do título
    t = (listing.title or "")
    m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if not m:
        return None
    try:
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            return y
    except Exception:
        return None
    return None


def text_match(query: str, listing: CarListing) -> bool:
    """Token-level AND match.

    Motivo: substring contains() é fraco (e gera falsos positivos com termos curtos como 'si').

    Importante: não usa URL como hay por padrão (evita tokens de tracking tipo click1/brand_ads).
    """
    terms = tokens(query or "")
    if not terms:
        return True

    base = " ".join(
        [
            listing.title or "",
            listing.location or "",
        ]
    ).strip()

    # fallback: se título veio vazio, usa URL como último recurso
    if not (listing.title or "").strip():
        base = (base + " " + (listing.url or "")).strip()

    hay_tokens = set(tokens(base))
    return all(t in hay_tokens for t in terms)


def _cmp(a: Decimal, op: str, b: Decimal) -> bool:
    if op == "lt":
        return a < b
    if op == "lte":
        return a <= b
    if op == "gt":
        return a > b
    if op == "gte":
        return a >= b
    if op == "eq":
        return a == b
    if op == "neq":
        return a != b
    return True  # operador desconhecido → ignora


def _cmp_int(a: int, op: str, b: int) -> bool:
    if op == "lt":
        return a < b
    if op == "lte":
        return a <= b
    if op == "gt":
        return a > b
    if op == "gte":
        return a >= b
    if op == "eq":
        return a == b
    if op == "neq":
        return a != b
    return True


def _apply_filters(listing: CarListing, filters: list[FilterRule]) -> bool:
    """Aplica filtros da wishlist.

    Suportado:
      - source eq/neq <valor>
      - price lt/lte/gt/gte/eq/neq <valor>
      - year  lt/lte/gt/gte/eq/neq <valor>  (extraído do listing.year ou do título)
    """
    for f in filters:
        field = (f.field or "").lower()
        op = (f.operator or "").lower()
        val = (f.value or "").strip()

        if field == "source":
            if not listing.source:
                return False
            src = listing.source.lower()
            target = val.lower()
            if op == "eq" and src != target:
                return False
            if op == "neq" and src == target:
                return False
            continue

        if field == "price":
            price = getattr(listing, "price", None)
            if price is None:
                return False

            target = _parse_decimal(val)
            if target is None:
                return False

            # price pode ser Decimal vindo do Numeric
            if not _cmp(Decimal(price), op, target):
                return False
            continue

        if field == "year":
            y = _extract_year(listing)
            if y is None:
                return False
            try:
                ty = int(val)
            except Exception:
                return False
            if not _cmp_int(y, op, ty):
                return False
            continue

        # campo desconhecido → ignora (para não quebrar quando você evoluir)
        continue

    return True


def _get_filters(wishlist: Wishlist) -> list[FilterRule]:
    # usa relationship se já carregou
    raw = list(getattr(wishlist, "filters", None) or [])
    return [FilterRule(f.field, f.operator, f.value) for f in raw]


def match_listings_for_wishlist(
    db: Session,
    wishlist: Wishlist,
    inserted_ids: Iterable,
) -> list[CarListing]:
    """Retorna os listings NOVOS (inserted_ids) que:

    - passam nos filtros da wishlist (price/year/source)
    - batem no texto da wishlist.query (AND de tokens)
    - passam nas regras semânticas (quando existirem)
    """
    ids = list(inserted_ids or [])
    if not ids:
        return []

    listings = db.query(CarListing).filter(CarListing.id.in_(ids)).all()
    filters = _get_filters(wishlist)

    matched: list[CarListing] = []
    for l in listings:
        if not _apply_filters(l, filters):
            continue

        if not text_match(wishlist.query, l):
            continue

        if not semantic_match(wishlist, l):
            continue

        matched.append(l)

    return matched


def match_listing_to_wishlist(db: Session, wishlist: Wishlist, listing: CarListing) -> bool:
    """Avalia 1 listing contra 1 wishlist.

    O fluxo principal do produto usa :func:`match_listings_for_wishlist` (batch)
    porque trabalha com IDs inseridos. Mas para testes e para pontos do código
    que já chamavam um matcher unitário, esse helper evita duplicação.

    Observação: o `db` é aceito para manter assinatura histórica, porém não é
    necessário para a lógica (os filtros vêm da própria wishlist).
    """

    filters = _get_filters(wishlist)
    if not _apply_filters(listing, filters):
        return False

    if not text_match(wishlist.query, listing):
        return False

    if not semantic_match(wishlist, listing):
        return False

    return True
