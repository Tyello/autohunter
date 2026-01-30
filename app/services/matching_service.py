from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence
from collections import defaultdict

from sqlalchemy.orm import Session

from app.core.text_norm import tokens, normalize
from app.models.car_listing import CarListing
from app.models.wishlist import Wishlist
from app.services.wishlist_semantic_rules import semantic_match


@dataclass(frozen=True)
class FilterRule:
    field: str
    operator: str
    value: str



# Stopwords leves para evitar que termos "a", "de", "até", "entre" bloqueiem matches.
# Sem NLP pesado: só robustez para o produto rodar 24/7 em hardware fraco.
_STOPWORDS = {
    "a","o","os","as","de","do","da","dos","das","e","em","no","na","nos","nas","para","por","com","sem",
    "ate","até","entre","apenas","so","só","somente","partir","apartir","desde","ano","year","anos",
    "valor","preco","preço","precos","preços",
}

_RE_YEAR_TOKEN = re.compile(r"^(19\d{2}|20\d{2})$")

def _is_year_token(t: str) -> bool:
    return bool(t) and bool(_RE_YEAR_TOKEN.match(t))

def _effective_terms(query: str) -> list[str]:
    ts = tokens(query or "")
    return [t for t in ts if t and t not in _STOPWORDS]

def _extract_year_from_url(url: str) -> int | None:
    if not url:
        return None
    m = re.search(r"(?:/|\b)(19\d{2}|20\d{2})(?:/|\b|\?|#)", url)
    if not m:
        return None
    try:
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            return y
    except Exception:
        return None
    return None

def _term_satisfied(term: str, hay_tokens: set[str], year: int | None) -> bool:
    if term in hay_tokens:
        return True
    if year is not None and _is_year_token(term):
        try:
            return int(term) == int(year)
        except Exception:
            return False
    return False

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
    # 1) tenta no título
    t = (listing.title or "")
    m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if m:
        try:
            y = int(m.group(1))
            if 1900 <= y <= 2100:
                return y
        except Exception:
            pass

    # 2) tenta na URL (muito comum em iCarros/webmotors/etc)
    y2 = _extract_year_from_url(getattr(listing, "url", "") or "")
    if y2:
        return y2

    return None

def text_match(query: str, listing: CarListing) -> bool:
    """Token-level AND match (robusto).

    Ajustes:
    - remove stopwords do query (evita match=0 por "a partir", "de", "até")
    - ignora ano solto no texto quando já existe outro termo (ex: "civic 1993" vira "civic")
    - quando um ano estiver no query e o título não trouxer, usa ano extraído do listing (título/URL)
    """
    terms = _effective_terms(query or "")
    if not terms:
        return True

    base = " ".join([listing.title or "", listing.location or ""]).strip()

    # fallback: se título veio vazio, usa URL como último recurso
    if not (listing.title or "").strip():
        base = (base + " " + (listing.url or "")).strip()

    hay_tokens = set(tokens(base))
    year = _extract_year(listing)

    # Se houver outros termos além de anos, não deixe um "1993" isolado matar o match.
    if any(not _is_year_token(t) for t in terms):
        terms = [t for t in terms if not _is_year_token(t)]

    return all(_term_satisfied(t, hay_tokens, year) for t in terms)

def _hay_for_listing(listing: CarListing) -> str:
    """Conteúdo de texto do anúncio usado para matching.

    Importante: não inclui URL por padrão (evita tokens de tracking),
    mas usa como fallback quando o título vem vazio.
    """
    base = " ".join([
        listing.title or "",
        listing.location or "",
    ]).strip()
    if not (listing.title or "").strip() and listing.url:
        base = (base + " " + listing.url).strip()
    return base


def _build_listing_ctx(listings: Sequence[CarListing]) -> dict:
    """Precomputações por listing para reduzir custo em loops."""
    ctx: dict = {}
    for l in listings:
        base = _hay_for_listing(l)
        ctx[l.id] = {
            "hay_tokens": set(tokens(base)),
            "year": _extract_year(l),
            "hay_norm": None,  # calculado sob demanda para semantic rules
        }
    return ctx


def _norm_sem(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[-_/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _semantic_key(wishlist: Wishlist) -> str:
    # mantém compat com wishlist_semantic_rules: usa name se existir, senão query
    name = _norm_sem(getattr(wishlist, "name", "") or "")
    return name or _norm_sem(getattr(wishlist, "query", "") or "")


def match_listings_for_wishlists(
    wishlists: Sequence[Wishlist],
    listings: Sequence[CarListing],
) -> dict:
    """Batch matching: avalia vários anúncios contra várias wishlists.

    Performance:
    - listings já vêm carregados (1 query na camada de job)
    - tokenização e extração de ano são precomputadas por listing
    - evita N queries (uma por wishlist) no fluxo do scheduler
    """
    if not wishlists or not listings:
        return {}

    # Import local para evitar import circular
    from app.services.wishlist_semantic_rules import RULES as SEM_RULES

    listing_ctx = _build_listing_ctx(listings)

    # prepara termos e filtros por wishlist
    prepared = []
    for w in wishlists:
        terms = _effective_terms(getattr(w, "query", "") or "")
        filters = _get_filters(w)

        if any(not _is_year_token(t) for t in terms):
            terms = [t for t in terms if not _is_year_token(t)]

        rules = SEM_RULES.get(_semantic_key(w))
        if rules:
            # normaliza termos 1x
            sem = {
                "blocked": [_norm_sem(t) for t in (rules.blocked_any or [])],
                "req_all": [_norm_sem(t) for t in (rules.required_all or [])],
                "req_any": [[_norm_sem(t) for t in (g or [])] for g in (rules.required_any_groups or [])],
            }
        else:
            sem = None

        prepared.append((w, terms, filters, sem))

    out = defaultdict(list)

    for (w, terms, filters, sem) in prepared:
        for l in listings:
            lctx = listing_ctx.get(l.id) or {}

            # filtros
            if filters:
                if not _apply_filters_fast(l, filters, lctx.get("year")):
                    continue

            # texto (AND por tokens)
            if terms:
                hay_tokens = lctx.get("hay_tokens") or set()
                if not all(_term_satisfied(t, hay_tokens, lctx.get('year')) for t in terms):
                    continue

            # semantic rules (quando existir)
            if sem:
                hay_norm = lctx.get("hay_norm")
                if hay_norm is None:
                    hay_norm = _norm_sem(_hay_for_listing(l))
                    lctx["hay_norm"] = hay_norm

                if any(t and t in hay_norm for t in sem["blocked"]):
                    continue
                if any(t and t not in hay_norm for t in sem["req_all"]):
                    continue
                ok_groups = True
                for g in sem["req_any"]:
                    if g and not any(t in hay_norm for t in g):
                        ok_groups = False
                        break
                if not ok_groups:
                    continue

            out[w.id].append(l)

    return dict(out)


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


def _apply_filters_fast(listing: CarListing, filters: list[FilterRule], year: int | None) -> bool:
    """Versão mais rápida de _apply_filters.

    Usa `year` pré-computado (ou None) para evitar regex repetido do ano.
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
            if not _cmp(Decimal(price), op, target):
                return False
            continue

        if field == "year":
            if year is None:
                return False
            try:
                ty = int(val)
            except Exception:
                return False
            if not _cmp_int(int(year), op, ty):
                return False
            continue

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

def explain_match(wishlist: Wishlist, listing: CarListing) -> str:
    """Retorna o primeiro motivo de não-match (ou 'ok').

    Útil para debug via /admin matchdebug.
    """
    filters = _get_filters(wishlist)
    year = _extract_year(listing)

    for f in filters:
        field = (f.field or "").lower()
        op = (f.operator or "").lower()
        val = (f.value or "").strip()

        if field == "source":
            src = (listing.source or "").lower()
            target = val.lower()
            if op == "eq" and src != target:
                return "filter_source"
            if op == "neq" and src == target:
                return "filter_source"
            continue

        if field == "price":
            price = getattr(listing, "price", None)
            if price is None:
                return "filter_price_missing"
            target = _parse_decimal(val)
            if target is None:
                return "filter_price_bad_value"
            if not _cmp(Decimal(price), op, target):
                return "filter_price_cmp"
            continue

        if field == "year":
            if year is None:
                return "filter_year_missing"
            try:
                ty = int(val)
            except Exception:
                return "filter_year_bad_value"
            if not _cmp_int(int(year), op, ty):
                return "filter_year_cmp"
            continue

    terms = _effective_terms(getattr(wishlist, "query", "") or "")
    if any(not _is_year_token(t) for t in terms):
        terms = [t for t in terms if not _is_year_token(t)]

    if terms:
        hay_tokens = set(tokens(_hay_for_listing(listing)))
        if not all(_term_satisfied(t, hay_tokens, year) for t in terms):
            return "text_terms"

    if not semantic_match(wishlist, listing):
        return "semantic"

    return "ok"
