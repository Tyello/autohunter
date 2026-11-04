"""Ausencia de anuncio so vale como evidencia quando o run PASSOU por inteiro.

Run com bloqueio (parcial ou total) nao pode contar "nao vi" para nenhum anuncio:
- wishlist_listing_activity (missing_runs_count / inactive) nao incrementa;
- presenca por busca (car_listings.missing_runs_count / status) nao muda;
- a rede de seguranca stale_days nao roda.
Sinais positivos (anuncio visto) continuam valendo.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.models.car_listing import CarListing
from app.models.source_config import SourceConfig
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_listing_activity import WishlistListingActivity
from app.scheduler import jobs
from app.services import source_configs_service
from app.services import source_execution_service as svc
from app.services.listing_activity_service import build_seen_identity, reconcile_listing_activity_for_source_run
from app.sources.types import ScrapeContext

from tests.test_source_execution_service import _plugin, _setup_run, _wishlist

PRESENCE = {"inactive_reconcile": {"mode": "on", "page_capacity": 40, "missing_runs": 1, "stale_days": 30}}


# ---------------------------------------------------------------- reconciliador (unidade)

def _mk_wishlist(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=900, username="u900", is_active=True, plan="free")
    db.add(u)
    db.commit()
    w = Wishlist(id=uuid.uuid4(), user_id=u.id, query="civic", is_active=True)
    db.add(w)
    db.commit()
    return w


def _mk_listing(db, ext):
    row = CarListing(id=uuid.uuid4(), source="olx", external_id=ext, title=ext, url=f"https://x.test/{ext}", currency="BRL", extras={})
    db.add(row)
    db.commit()
    return row


def test_apply_missing_false_records_seen_but_never_counts_absence(db):
    wl = _mk_wishlist(db)
    seen_l, gone_l = _mk_listing(db, "seen"), _mk_listing(db, "gone")
    both = [build_seen_identity(seen_l), build_seen_identity(gone_l)]
    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: both}, target_wishlist_ids=[wl.id], missing_threshold=1)
    db.commit()

    stats = reconcile_listing_activity_for_source_run(
        db,
        source_name="olx",
        wishlist_seen={wl.id: [build_seen_identity(seen_l)]},
        target_wishlist_ids=[wl.id],
        missing_threshold=1,
        apply_missing=False,
    )
    db.commit()

    assert stats.missing_incremented == 0 and stats.marked_inactive == 0
    gone = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id, source_listing_id="gone").one()
    assert gone.status == "active" and gone.missing_runs_count == 0
    assert stats.seen_upserts == 1


def test_apply_missing_default_still_inactivates(db):
    wl = _mk_wishlist(db)
    seen_l, gone_l = _mk_listing(db, "seen"), _mk_listing(db, "gone")
    both = [build_seen_identity(seen_l), build_seen_identity(gone_l)]
    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: both}, target_wishlist_ids=[wl.id], missing_threshold=1)
    db.commit()

    reconcile_listing_activity_for_source_run(db, source_name="olx", wishlist_seen={wl.id: [build_seen_identity(seen_l)]}, target_wishlist_ids=[wl.id], missing_threshold=1)
    db.commit()

    gone = db.query(WishlistListingActivity).filter_by(wishlist_id=wl.id, source_listing_id="gone").one()
    assert gone.status == "inactive"


# ---------------------------------------------------------------- run completo (integracao)

def _item(ext):
    return {
        "source": "olx",
        "external_id": ext,
        "url": f"https://olx.test/d/{ext}",
        "title": f"Civic {ext}",
        "price": Decimal("50000.00"),
        "year": 2015,
    }


class _World:
    """3 buscas/grupos; cada uma tem os anuncios `g<i>a` e `g<i>b`. `visible` define o que cada busca mostra."""

    def __init__(self, db, monkeypatch):
        # snapshot de config tem cache com TTL entre testes (olx de outro teste esconderia o extra daqui)
        source_configs_service._CACHE_BY_SOURCE.clear()
        self.db = db
        self.plugin = _plugin("olx")
        self.wishlists = [_wishlist(query=f"q{i}") for i in range(3)]
        self.urls = [self.plugin.build_url(w.query) for w in self.wishlists]
        db.add(SourceConfig(source="olx", is_enabled=True, sched_minutes=60, cooldown_minutes=0, rate_limit_seconds=0,
                            browser_fallback_enabled=True, extra=dict(PRESENCE)))
        db.commit()
        _setup_run(monkeypatch, source="olx", wishlists=self.wishlists, plugin=self.plugin)
        self.visible: dict[int, list[str]] = {i: [f"g{i}a", f"g{i}b"] for i in range(3)}
        self.blocked: set[int] = set()
        self.activity_calls: list[dict] = []
        monkeypatch.setattr(svc, "scrape_ingest_match", self._scrape)
        monkeypatch.setattr(jobs, "log", lambda *a, **k: None)
        monkeypatch.setattr(jobs, "emit_event", lambda *a, **k: None)

        def _spy(*a, **kw):
            self.activity_calls.append(kw)
            return SimpleNamespace(to_dict=lambda: {"ok": True})

        monkeypatch.setattr(svc, "reconcile_listing_activity_for_source_run", _spy)

    def _scrape(self, _db, job_name, _dispatch, url, *, ctx, wishlist=None, health=None):
        idx = self.urls.index(url)
        if idx in self.blocked:
            return {"ok": False, "reason": "blocked", "status_code": 200, "url": url, "error": "blocked"}
        ids = self.visible[idx]
        return jobs.scrape_ingest_match(_db, job_name, lambda u, c: [_item(i) for i in ids], url, ctx=ctx, wishlist=None, health=health)

    def run(self):
        return svc.run_source_for_all_wishlists(self.db, "olx", kind="scheduler", force=True, ignore_backoff=True)

    def listing(self, ext):
        self.db.expire_all()
        return self.db.query(CarListing).filter_by(source="olx", external_id=ext).one()


def test_clean_run_still_counts_absence_and_inactivates(db, monkeypatch):
    w = _World(db, monkeypatch)
    assert w.run()["status"] == "success"
    w.visible[0] = ["g0a"]  # g0b sumiu de uma busca completa
    res = w.run()

    assert res["status"] == "success"
    assert w.listing("g0b").status == "inativo", "run limpo continua valendo como evidencia de ausencia"
    assert w.activity_calls[-1].get("apply_missing", True) is True


def test_partial_block_run_does_not_count_absence_anywhere(db, monkeypatch):
    w = _World(db, monkeypatch)
    assert w.run()["status"] == "success"
    w.visible[0] = ["g0a"]  # g0b "sumiu" no grupo que passou ...
    w.blocked = {1}          # ... mas o run teve um grupo bloqueado

    res = w.run()

    assert res["status"] == "success"
    assert w.listing("g0b").status == "ativo", "ausencia em run parcial nao vale"
    assert w.listing("g0b").missing_runs_count == 0
    assert w.listing("g1a").status == "ativo" and w.listing("g1a").missing_runs_count == 0
    call = w.activity_calls[-1]
    assert call["apply_missing"] is False
    assert w.wishlists[1].id not in call["target_wishlist_ids"]
    assert {w.wishlists[0].id, w.wishlists[2].id} == set(call["target_wishlist_ids"])


def test_partial_block_run_skips_stale_safety_net(db, monkeypatch):
    w = _World(db, monkeypatch)
    assert w.run()["status"] == "success"
    calls = []
    monkeypatch.setattr(svc, "mark_stale_listings_inactive", lambda *a, **k: calls.append(1) or {})
    w.blocked = {1}

    assert w.run()["status"] == "success"
    assert calls == [], "stale_days so roda em run totalmente limpo"


def test_full_block_run_does_not_count_absence_for_groups_that_passed(db, monkeypatch):
    w = _World(db, monkeypatch)
    assert w.run()["status"] == "success"
    w.visible[0] = ["g0a"]
    w.blocked = {1, 2}  # 2 seguidos -> run bloqueado

    res = w.run()

    assert res["status"] == "blocked"
    assert w.listing("g0b").status == "ativo"
    assert w.listing("g0b").missing_runs_count == 0, "run bloqueado nao pode ter contado ausencia no grupo 0"


# ---------------------------------------------------------------- adiamento no pipeline

def test_pipeline_defers_presence_when_ctx_asks(db, monkeypatch):
    monkeypatch.setattr(jobs, "log", lambda *a, **k: None)
    monkeypatch.setattr(jobs, "emit_event", lambda *a, **k: None)
    pending: list = []
    ctx = ScrapeContext(source="olx", extra=dict(PRESENCE), defer_presence=True, _presence_pending=pending)
    url = "https://olx.test/s?q=rs4"

    jobs.scrape_ingest_match(db, "scraper_olx", lambda u, c: [_item("a"), _item("b")], url, ctx=ctx)
    jobs.scrape_ingest_match(db, "scraper_olx", lambda u, c: [_item("a")], url, ctx=ctx)

    db.expire_all()
    b = db.query(CarListing).filter_by(source="olx", external_id="b").one()
    assert b.last_seen_search_key is None and b.missing_runs_count == 0, "nada de presenca aplicado inline"
    assert [p["search_url"] for p in pending] == [url, url]
    assert pending[1]["found"] == 1 and pending[1]["seen_external_ids"] == ["a"]
