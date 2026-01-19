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
    # inclui URL porque às vezes o título vem vazio, mas o slug ajuda
    return _norm(" ".join([
        listing.title or "",
        listing.location or "",
        listing.url or "",
    ]))


RULES: dict[str, SemanticRules] = {
    # Ajustes focados no seu caso (pode expandir depois, sem mexer em scraper)
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
    # tenta casar por name primeiro, depois por query
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

    # bloqueios primeiro (barato)
    for term in rules.blocked_any:
        if _norm(term) in hay:
            return False

    # required_all (AND)
    for term in rules.required_all:
        if _norm(term) not in hay:
            return False

    # required_any_groups (OR por grupo)
    for group in rules.required_any_groups:
        if not any(_norm(t) in hay for t in group):
            return False

    return True
