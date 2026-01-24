from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable
from urllib.parse import urlparse

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


def _normalize_terms(query: str) -> list[str]:
    # kept for backward compat; prefer app.core.text_norm.tokens for new usage
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


def _safe_url_for_match(listing: CarListing) -> str:
    """Evita falsos positivos causados por URLs gigantes de tracking (ex.: click1/brand_ads)."""
    url = (listing.url or "").strip()
    if not url:
        return ""

    source = (listing.source or "").lower()

    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "")
        path_l = path.lower()

        # Mercado Livre: ignore totalmente URLs de tracking patrocinado, pois podem conter "si" por acaso
        if source == "mercadolivre":
            if ("mercadolivre.com.br" in host) and (host.startswith("click") or host.startswith("clk")):
                return ""
            if "brand_ads/clicks" in path_l:
                return ""

        # Para matching, queremos algo estável e "curto": host+path, sem query/fragment
        return f"{host}{path}"
    except Exception:
        # fallback simples
        u = url.split("#")[0].split("?")[0]
        # se parecer tracking do ML, ignora
        if source == "mercadolivre" and ("click" in u and "mercadolivre.com.br" in u):
            return ""
        return u


def text_match(query: str, listing: CarListing) -> bool:
    """Token-level AND match.

    Motivo: substring contains() é fraco (e gera falsos positivos com termos curtos como 'si').
    """

    terms = tokens(query or "")
    if not terms:
        return True

    hay_tokens = set(
        tokens(
            " ".join(
                [
                    listing.title or "",
                    listing.location or "",
                    _safe_url_for_match(listing),
                ]
            )
        )
    )

    return all(t in hay_tokens for t in terms)


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
    """Retorna os listings NOVOS (inserted_ids) que:

    - passam nos filtros da wishlist (price + source)
    - batem no texto da wishlist.query
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

        # Texto da wishlist precisa bater integralmente (AND de termos).
        # Isso evita "Civic" trazer LXR/EXR quando a intenção é "Civic SI".
        if not text_match(wishlist.query, l):
            continue

        # Regras semânticas específicas por wishlist.
        if not semantic_match(wishlist, l):
            continue

        matched.append(l)

    return matched
