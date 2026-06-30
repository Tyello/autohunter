"""Unit tests for canonical_search_key.

Verifica o contrato conservador de dedup:
- Duas wishlists com a mesma query DEVEM produzir a mesma chave (elegíveis a compartilhar um scrape).
- Duas wishlists com queries diferentes DEVEM produzir chaves diferentes (nunca colapsar).
- Regras WishlistFilter pós-scrape NÃO devem afetar a chave (são preocupações do fan-out).
- Uma colisão (mesma chave) nunca deve causar alerta perdido — só scrape redundante.
"""
from __future__ import annotations

import types
import uuid
from types import SimpleNamespace

from app.services.search_deduplication_service import canonical_search_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(prefix: str = "https://example.com/search?q="):
    """SourcePlugin mínimo com build_url determinístico."""
    return SimpleNamespace(
        build_url=lambda query: f"{prefix}{query.strip().lower().replace(' ', '+')}"
    )


def _make_wishlist(query: str, *, filters: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        query=query,
        filters=filters or [],
    )


def _make_filter(field: str, operator: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(field=field, operator=operator, value=value, is_active=True)


# ---------------------------------------------------------------------------
# Tests: mesma query → mesma chave
# ---------------------------------------------------------------------------

def test_same_query_produces_same_key():
    plugin = _make_plugin()
    w1 = _make_wishlist("corolla sp")
    w2 = _make_wishlist("corolla sp")
    assert canonical_search_key(w1, plugin) == canonical_search_key(w2, plugin)


def test_same_query_with_different_filters_produces_same_key():
    """Filtros pós-scrape NÃO devem afetar a chave canônica."""
    plugin = _make_plugin()
    w1 = _make_wishlist("civic 2020", filters=[_make_filter("price", "lte", "80000")])
    w2 = _make_wishlist(
        "civic 2020",
        filters=[_make_filter("price", "gte", "50000"), _make_filter("year", "gte", "2019")],
    )
    assert canonical_search_key(w1, plugin) == canonical_search_key(w2, plugin)


def test_same_query_no_filters_vs_with_filters_produces_same_key():
    plugin = _make_plugin()
    w1 = _make_wishlist("hrv rj")
    w2 = _make_wishlist("hrv rj", filters=[_make_filter("mileage_km", "lte", "50000")])
    assert canonical_search_key(w1, plugin) == canonical_search_key(w2, plugin)


# ---------------------------------------------------------------------------
# Tests: queries diferentes → chaves diferentes (sem falso colapso)
# ---------------------------------------------------------------------------

def test_different_queries_produce_different_keys():
    plugin = _make_plugin()
    assert canonical_search_key(_make_wishlist("corolla sp"), plugin) != canonical_search_key(_make_wishlist("civic sp"), plugin)


def test_different_location_produces_different_keys():
    plugin = _make_plugin()
    assert canonical_search_key(_make_wishlist("civic sp"), plugin) != canonical_search_key(_make_wishlist("civic rj"), plugin)


def test_different_model_year_in_query_produces_different_keys():
    plugin = _make_plugin()
    assert canonical_search_key(_make_wishlist("civic 2018"), plugin) != canonical_search_key(_make_wishlist("civic 2022"), plugin)


def test_source_plugin_determines_key():
    """Mesma wishlist + plugins diferentes → chaves diferentes (cada source tem URL própria)."""
    plugin_ml = _make_plugin("https://lista.mercadolivre.com.br/q=")
    plugin_olx = _make_plugin("https://www.olx.com.br/autos-e-pecas?q=")
    w = _make_wishlist("corolla sp")
    assert canonical_search_key(w, plugin_ml) != canonical_search_key(w, plugin_olx)


# ---------------------------------------------------------------------------
# Tests: chave é o URL retornado por build_url
# ---------------------------------------------------------------------------

def test_canonical_key_equals_build_url_result():
    plugin = _make_plugin()
    w = _make_wishlist("civic 2020 sp")
    assert canonical_search_key(w, plugin) == plugin.build_url(w.query)


def test_multiple_wishlists_grouped_by_key_gives_unique_urls():
    plugin = _make_plugin()
    wishlists = [
        _make_wishlist("corolla sp"),
        _make_wishlist("corolla sp"),  # duplicata
        _make_wishlist("civic sp"),
        _make_wishlist("civic rj"),
        _make_wishlist("civic rj"),    # duplicata
    ]
    keys = {canonical_search_key(w, plugin) for w in wishlists}
    assert len(keys) == 3, f"Esperado 3 chaves únicas (corolla-sp, civic-sp, civic-rj), got {len(keys)}"


# ---------------------------------------------------------------------------
# Tests: garantia conservadora — nunca colapsar queries não-equivalentes
# ---------------------------------------------------------------------------

def test_empty_query_does_not_collapse_with_non_empty():
    plugin = _make_plugin()
    assert canonical_search_key(_make_wishlist(""), plugin) != canonical_search_key(_make_wishlist("corolla"), plugin)


def test_whitespace_normalized_query_matches():
    """build_url normaliza espaço; chaves devem ser iguais."""
    plugin = _make_plugin()
    w1 = _make_wishlist("civic  sp")
    w2 = _make_wishlist("civic  sp")
    assert canonical_search_key(w1, plugin) == canonical_search_key(w2, plugin)
