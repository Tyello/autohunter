from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from app.core.text_norm import tokens
from app.models.car_listing import CarListing
from app.models.wishlist import Wishlist


@dataclass(frozen=True)
class SemanticRules:
    """Regras simples e explícitas para endurecer matching por wishlist.

    - required_all: todos os termos devem estar presentes (token-level).
    - required_any_groups: para cada grupo, pelo menos 1 termo deve aparecer.
    - blocked_any: se qualquer termo aparecer, rejeita.
    """

    required_all: list[str]
    required_any_groups: list[list[str]]
    blocked_any: list[str]


def _norm_phrase(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _clean_url_for_rules(listing: CarListing) -> str:
    url = (listing.url or "").strip()
    url = _decode_url_escapes(url)
    url = _decode_url_escapes(url)
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").lower()

        if (listing.source or "").lower() == "mercadolivre":
            if host.startswith("click") or "brand_ads/clicks" in path:
                return ""
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        u = url.split("#")[0].split("?")[0]
        if (listing.source or "").lower() == "mercadolivre" and ("brand_ads/clicks" in u or "click" in u):
            return ""
        return u


def _hay_tokens(listing: CarListing) -> set[str]:
    """
    Tokeniza título + local + url (limpa). Isso evita falso positivo por substring.
    """
    u = _clean_url_for_rules(listing)
    return set(tokens(" ".join([
        listing.title or "",
        listing.location or "",
        u,
    ])))


def _hay_text(listing: CarListing) -> str:
    """Texto normalizado (para match de frases multi-palavra, ex: 'type r')."""
    u = _clean_url_for_rules(listing)
    s = " ".join([listing.title or "", listing.location or "", u])
    s = _norm_phrase(s)
    s = re.sub(r"[-_/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s



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
def _safe_url_for_semantic(listing: CarListing) -> str:
    """Evita usar URLs de tracking (ML click/brand_ads) como texto de match."""
    url = (listing.url or "").strip()
    if not url:
        return ""

    source = (listing.source or "").lower()

    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "")
        path_l = path.lower()

        if source == "mercadolivre":
            if ("mercadolivre.com.br" in host) and (host.startswith("click") or host.startswith("clk")):
                return ""
            if "brand_ads/clicks" in path_l:
                return ""

        # sem query/fragment, reduz ruído
        return f"{host}{path}"
    except Exception:
        u = url.split("#")[0].split("?")[0]
        if source == "mercadolivre" and ("click" in u and "mercadolivre.com.br" in u):
            return ""
        return u


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
    name = _norm_phrase(getattr(wishlist, "name", "") or "")
    query = _norm_phrase(getattr(wishlist, "query", "") or "")
    return name or query


def semantic_match(wishlist: Wishlist, listing: CarListing) -> bool:
    """
    Sem regra: True.
    Com regra: aplica token-level para termos e substring para frases multi-palavra.
    """

    key = _key(wishlist)
    rules = RULES.get(key)
    if not rules:
        return True

    hay_toks = _hay_tokens(listing)
    hay_txt = _hay_text(listing)

    # bloqueios primeiro (frases)
    for term in rules.blocked_any:
        t = _norm_phrase(term)
        if t and t in hay_txt:
            return False

    # required_all (tokens)
    for term in rules.required_all:
        t = _norm_phrase(term)
        if not t:
            continue
        # termos curtos tipo 'si' precisam ser token exato
        if t not in hay_toks:
            return False

    # required_any_groups
    for group in rules.required_any_groups:
        ok = False
        for term in group:
            t = _norm_phrase(term)
            if not t:
                continue
            if t in hay_toks:
                ok = True
                break
        if not ok:
            return False

    return True
