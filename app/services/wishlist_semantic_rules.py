from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.car_listing import CarListing
from app.models.wishlist import Wishlist


@dataclass(frozen=True)
class SemanticRules:
    """Regras simples e explícitas para endurecer matching por wishlist.

    - required_all: todos os termos devem estar presentes.
    - required_any_groups: para cada grupo, pelo menos 1 termo deve aparecer.
    - blocked_any: se qualquer termo aparecer, rejeita.
    """

    required_all: list[str]
    required_any_groups: list[list[str]]
    blocked_any: list[str]


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[-_/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _hay(listing: CarListing) -> str:
    # Não inclui URL por padrão (evita tokens de tracking e falsos positivos).
    parts = [listing.title or "", listing.location or ""]

    # fallback: se título vazio, usar URL pode ajudar (slug)
    if not (listing.title or "").strip():
        parts.append(listing.url or "")

    return _norm(" ".join(parts))


RULES: dict[str, SemanticRules] = {
    "civic si": SemanticRules(
        required_all=["civic", "si"],
        required_any_groups=[],
        blocked_any=["type r", "typer"],
    ),
    "civic hatch": SemanticRules(
        required_all=["civic"],
        required_any_groups=[["hatch", "hatchback"]],
        blocked_any=["type r", "typer", "sedan"],
    ),
}


def _key(wishlist: Wishlist) -> str:
    name = _norm(getattr(wishlist, "name", "") or "")
    query = _norm(getattr(wishlist, "query", "") or "")
    return name or query


def semantic_match(wishlist: Wishlist, listing: CarListing) -> bool:
    """Aplica regras semânticas específicas quando existirem.

    Por padrão (sem regra cadastrada), retorna True.
    """
    key = _key(wishlist)
    rules = RULES.get(key)
    if not rules:
        return True

    hay = _hay(listing)

    for term in rules.blocked_any:
        if _norm(term) in hay:
            return False

    for term in rules.required_all:
        if _norm(term) not in hay:
            return False

    for group in rules.required_any_groups:
        if not any(_norm(t) in hay for t in group):
            return False

    return True
