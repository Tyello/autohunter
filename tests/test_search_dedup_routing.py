"""Testa o roteamento canônico no tick recorrente.

Garante que:
1. run_source_for_all_wishlists chama scrape_ingest_match(wishlist=None) — nunca
   scrape_ingest_match_many — no caminho recorrente.
2. Wishlists com mesma query resultam em UM único scrape (dedup por canonical key).
3. Wishlists com queries distintas resultam em scrapes separados.
4. O wishlist=None passado é sempre None (fan-out via inverted index, não per-wishlist).
5. scrape_ingest_match_many permanece no módulo (não foi deletada) para uso on-demand.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.source_config import SourceConfig
from app.services import source_execution_service as svc


# ---------------------------------------------------------------------------
# Helpers (espelho exato de test_source_execution_service.py)
# ---------------------------------------------------------------------------

class _ActivityStats:
    def to_dict(self):
        return {"ok": True}


def _plugin(name="mercadolivre"):
    return SimpleNamespace(
        name=name,
        scrape=lambda _url, ctx=None: [],
        build_url=lambda q: f"https://example.test/search?q={q.replace(' ', '+')}",
        supports_wishlist_monitoring=True,
        fetch_mode="http",
        default_extra={"operational_role": "primary"},
    )


def _wishlist(query="civic sp"):
    return SimpleNamespace(id=uuid.uuid4(), query=query)


def _base_result():
    return {
        "ok": True,
        "found": 0,
        "inserted": 0,
        "matched": 0,
        "queued": 0,
        "already_notified": 0,
        "reason_buckets": {},
        "thumb_present": 0,
        "seen_identities_by_wishlist": {},
        "runtime_impl": "v2_canary",
        "adapter_meta": {"raw_count": 0, "normalized_count": 0},
    }


def _add_cfg(db, source="mercadolivre"):
    db.add(SourceConfig(
        source=source,
        is_enabled=True,
        sched_minutes=60,
    ))
    db.commit()


def _setup(monkeypatch, *, source="mercadolivre", plugin=None, wishlists=None):
    p = plugin or _plugin(source)
    ws = wishlists if wishlists is not None else [_wishlist()]
    result = _base_result()
    monkeypatch.setattr(svc, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(svc, "get_source", lambda _src: p if _src == source else None)
    monkeypatch.setattr(svc, "_wishlist_eligibility_snapshot", lambda _db, _src: (ws, {"active_wishlists": len(ws)}))
    monkeypatch.setattr(svc, "reconcile_listing_activity_for_source_run", lambda *_a, **_kw: _ActivityStats())
    monkeypatch.setattr(svc, "log", lambda *_a, **_kw: None)
    monkeypatch.setattr(svc, "emit_event", lambda *_a, **_kw: None)
    return result


def _run(db, source="mercadolivre"):
    return svc.run_source_for_all_wishlists(db, source, kind="scheduler", force=True, ignore_backoff=True)


# ---------------------------------------------------------------------------
# Test: tick chama scrape_ingest_match(wishlist=None), não scrape_ingest_match_many
# ---------------------------------------------------------------------------

def test_tick_calls_scrape_ingest_match_not_many(monkeypatch, db):
    result = _setup(monkeypatch, wishlists=[_wishlist("civic sp")])

    calls_sim = []
    calls_many = []
    monkeypatch.setattr(svc, "scrape_ingest_match", lambda *a, **kw: (calls_sim.append(kw), result)[1])
    monkeypatch.setattr(svc, "scrape_ingest_match_many", lambda *a, **kw: (calls_many.append(kw), result)[1])

    _add_cfg(db)
    _run(db)

    assert len(calls_sim) >= 1, "scrape_ingest_match deve ser chamado pelo tick"
    assert len(calls_many) == 0, "scrape_ingest_match_many NÃO deve ser chamado pelo tick recorrente"


def test_tick_passes_wishlist_none(monkeypatch, db):
    """O tick SEMPRE passa wishlist=None (fan-out via inverted index)."""
    result = _setup(monkeypatch, wishlists=[_wishlist("corolla sp")])

    wishlist_args = []
    monkeypatch.setattr(svc, "scrape_ingest_match", lambda *a, **kw: (wishlist_args.append(kw.get("wishlist")), result)[1])

    _add_cfg(db)
    _run(db)

    assert all(w is None for w in wishlist_args), f"wishlist deve ser None em todos os calls, got: {wishlist_args}"


# ---------------------------------------------------------------------------
# Test: dedup por canonical key
# ---------------------------------------------------------------------------

def test_duplicate_query_wishlists_produce_one_scrape(monkeypatch, db):
    """3 wishlists com a mesma query → exatamente 1 call ao scraper."""
    query = "civic sp"
    wishlists = [_wishlist(query), _wishlist(query), _wishlist(query)]
    result = _setup(monkeypatch, wishlists=wishlists)

    call_urls = []
    monkeypatch.setattr(svc, "scrape_ingest_match", lambda *a, **kw: (call_urls.append(a[3]), result)[1])

    _add_cfg(db)
    _run(db)

    assert len(call_urls) == 1, f"Esperado 1 scrape, got {len(call_urls)}: {call_urls}"


def test_distinct_queries_produce_separate_scrapes(monkeypatch, db):
    """3 wishlists com queries distintas → 3 scrapes separados."""
    wishlists = [_wishlist("civic sp"), _wishlist("corolla sp"), _wishlist("hrv rj")]
    result = _setup(monkeypatch, wishlists=wishlists)

    call_urls = []
    monkeypatch.setattr(svc, "scrape_ingest_match", lambda *a, **kw: (call_urls.append(a[3]), result)[1])

    _add_cfg(db)
    _run(db)

    assert len(call_urls) == 3, f"Esperado 3 scrapes, got {len(call_urls)}: {call_urls}"
    assert len(set(call_urls)) == 3, "URLs dos scrapes devem ser únicas"


def test_mixed_queries_dedup_correctly(monkeypatch, db):
    """2 wishlists com query A e 2 com query B → 2 scrapes."""
    wishlists = [
        _wishlist("civic sp"),
        _wishlist("civic sp"),   # dedup com o anterior
        _wishlist("corolla rj"),
        _wishlist("corolla rj"), # dedup com o anterior
    ]
    result = _setup(monkeypatch, wishlists=wishlists)

    call_urls = []
    monkeypatch.setattr(svc, "scrape_ingest_match", lambda *a, **kw: (call_urls.append(a[3]), result)[1])

    _add_cfg(db)
    _run(db)

    assert len(call_urls) == 2, f"Esperado 2 scrapes, got {len(call_urls)}: {call_urls}"
    assert len(set(call_urls)) == 2


# ---------------------------------------------------------------------------
# Test: scrape_ingest_match_many ainda existe (NÃO foi deletada)
# ---------------------------------------------------------------------------

def test_scrape_ingest_match_many_still_exists():
    """A função por-wishlist deve existir para uso on-demand (buscar agora)."""
    from app.scheduler.jobs import scrape_ingest_match_many
    assert callable(scrape_ingest_match_many)
