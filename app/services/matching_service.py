from __future__ import annotations

import re

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse, urlunparse

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



def _decode_url_escapes(url: str) -> str:
    """Conserta URLs com escapes literais (ex: https:\u002F\u002Fclick1...)."""
    u = (url or "").strip()
    if not u:
        return ""
    u = (
        u.replace("\\u002F", "/")
         .replace("\\u003A", ":")
         .replace("\\u003D", "=")
         .replace("\\u0026", "&")
         .replace("\\/", "/")
    )
    if re.search(r"\\u[0-9a-fA-F]{4}", u):
        try:
            u = u.encode("utf-8", "ignore").decode("unicode_escape")
        except Exception:
            pass
        u = u.replace("\\/", "/")
    return u
def _safe_url_for_match(listing: CarListing) -> str:
    """Evita falsos positivos causados por URLs gigantes de tracking (ex.: click1/brand_ads)."""
    url = (listing.url or "").strip()
    url = _decode_url_escapes(url)
    url = _decode_url_escapes(url)
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


def _clean_url_for_match(listing: CarListing) -> str:
    """
    Evita falso-positivo por URL de tracking (ex: click1.mercadolivre...).
    Retorna apenas host+path, sem query/fragment.
    """
    url = (listing.url or "").strip()
    if not url:
        return ""

    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").lower()

        if (listing.source or "").lower() == "mercadolivre":
            if host.startswith("click") or "brand_ads/clicks" in path:
                # tracking: não entra no matching
                return ""

        # canonical sem query/fragment
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        # fallback: remove query/fragment
        u = url.split("#")[0].split("?")[0]
        if (listing.source or "").lower() == "mercadolivre" and ("brand_ads/clicks" in u or "click" in u):
            return ""
        return u


def text_match(query: str, listing: CarListing) -> bool:
    """Token-level AND match.

    Motivo: substring contains() é fraco (gera falsos positivos com termos curtos como 'si').
    """

    terms = tokens(query or "")
    if not terms:
        return True

    url_for_match = _clean_url_for_match(listing)

    hay_tokens = set(tokens(" ".join([
            listing.title or "",
            listing.location or "",
            url_for_match,
    ])))

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
                continue
            if not listing.source:
                return False
            if listing.source.lower() != val.lower():
                return False

        if field == "price":
            if listing.price is None:
                return False
            target = _parse_decimal(val)
            if target is None:
                continue
            if op == "lte" and Decimal(str(listing.price)) > target:
                return False
            if op == "gte" and Decimal(str(listing.price)) < target:
                return False

    return True


def match_listing_to_wishlist(db: Session, wishlist: Wishlist, listing: CarListing) -> bool:
    # 1) semantic rules (hardening por wishlist)
    if not semantic_match(wishlist, listing):
        return False

    # 2) token-level match
    if not text_match(wishlist.query or "", listing):
        return False

    # 3) filtros explícitos
    filters = db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id).all()
    frules = [FilterRule(f.field, f.operator, f.value) for f in filters]
    return _apply_filters(listing, frules)
