"""O pipeline de scrape marca presenca/ausencia por busca (listing_presence_service) sem quebrar
quando a config esta desligada, e nunca derruba o scrape se o reconcile falhar."""

from __future__ import annotations

from decimal import Decimal

from app.models.car_listing import CarListing
from app.scheduler.jobs import scrape_ingest_match, scrape_ingest_match_many
from app.sources.types import ScrapeContext

URL = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q=rs4"


def _item(ext):
    return {
        "source": "olx",
        "external_id": ext,
        "url": f"https://www.olx.com.br/d/{ext}",
        "title": f"Audi RS4 {ext}",
        "price": Decimal("100000.00"),
        "year": 2010,
    }


def _quiet(monkeypatch):
    # system_logs.tags e ARRAY(Text) e o sqlite de teste nao tem bind p/ ele; so o retorno interessa
    monkeypatch.setattr("app.scheduler.jobs.log", lambda *a, **kw: None)
    monkeypatch.setattr("app.scheduler.jobs.emit_event", lambda *a, **kw: None)


def _ctx(mode):
    extra = {"inactive_reconcile": {"mode": mode, "page_capacity": 40, "missing_runs": 2}} if mode else {}
    return ScrapeContext(source="olx", extra=extra)


def _run(db, ctx, ids, many=False):
    fn = scrape_ingest_match_many if many else scrape_ingest_match
    kwargs = {"wishlists": []} if many else {}
    return fn(db, "scraper_olx", lambda u, ctx: [_item(i) for i in ids], URL, ctx=ctx, **kwargs)


def _row(db, ext):
    db.expire_all()
    return db.query(CarListing).filter_by(source="olx", external_id=ext).one()


def test_off_by_default_leaves_presence_columns_untouched(db, monkeypatch):
    _quiet(monkeypatch)
    assert _run(db, _ctx(None), ["a", "b"])["ok"] is True
    assert _row(db, "a").last_seen_search_key is None


def test_two_complete_runs_without_listing_mark_it_inactive(db, monkeypatch):
    _quiet(monkeypatch)
    ctx = _ctx("on")
    _run(db, ctx, ["a", "b"])
    assert _row(db, "b").last_seen_search_key == URL

    _run(db, ctx, ["a"])
    assert _row(db, "b").missing_runs_count == 1
    assert _row(db, "b").status == "ativo"

    _run(db, ctx, ["a"])
    assert _row(db, "b").status == "inativo"
    assert _row(db, "a").status == "ativo"

    # reaparece: o upsert devolve 'ativo' e zera o contador
    _run(db, ctx, ["a", "b"])
    assert _row(db, "b").status == "ativo"
    assert _row(db, "b").missing_runs_count == 0


def test_many_pipeline_also_reconciles(db, monkeypatch):
    _quiet(monkeypatch)
    ctx = _ctx("on")
    _run(db, ctx, ["a", "b"], many=True)
    _run(db, ctx, ["a"], many=True)
    _run(db, ctx, ["a"], many=True)
    assert _row(db, "b").status == "inativo"


def test_reconcile_failure_never_breaks_scrape(db, monkeypatch):
    _quiet(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("db exploded")

    monkeypatch.setattr("app.scheduler.jobs.reconcile_search_presence", boom)
    res = _run(db, _ctx("on"), ["a"])
    assert res["ok"] is True
    assert _row(db, "a").status == "ativo"
