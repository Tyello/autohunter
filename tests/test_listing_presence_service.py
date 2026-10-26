from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.car_listing import CarListing
from app.services.listing_presence_service import (
    mark_stale_listings_inactive,
    parse_presence_config,
    reconcile_search_presence,
)

KEY = "https://www.olx.com.br/autos?q=rs4"
OTHER_KEY = "https://www.olx.com.br/autos?q=civic"


def _cfg(**over):
    base = {"mode": "on", "page_capacity": 40, "missing_runs": 3, "stale_days": 30}
    base.update(over)
    return parse_presence_config({"inactive_reconcile": base})


def _mk(db, ext, *, source="olx", key=KEY, status="ativo", missing=0, last_seen=None):
    row = CarListing(
        id=uuid.uuid4(),
        source=source,
        external_id=ext,
        title=f"t{ext}",
        url=f"https://example.test/{source}/{ext}",
        currency="BRL",
        extras={},
        status=status,
        last_seen_search_key=key,
        missing_runs_count=missing,
    )
    if last_seen is not None:
        row.last_seen_at = last_seen
    db.add(row)
    db.commit()
    return row


def _reload(db, row):
    db.expire_all()
    return db.get(CarListing, row.id)


def _run(db, cfg, seen, *, key=KEY, source="olx", found=None):
    return reconcile_search_presence(
        db,
        source=source,
        search_key=key,
        seen_external_ids=seen,
        found=len(seen) if found is None else found,
        cfg=cfg,
    )


def test_config_defaults_to_off():
    assert parse_presence_config(None).mode == "off"
    assert parse_presence_config({}).mode == "off"
    assert parse_presence_config({"inactive_reconcile": {"mode": "bogus"}}).mode == "off"


def test_off_mode_is_noop(db):
    row = _mk(db, "a", key=None)
    stats = _run(db, parse_presence_config(None), ["a"])
    assert stats["mode"] == "off"
    assert _reload(db, row).last_seen_search_key is None


def test_seen_listing_is_tagged_with_search_key_and_counter_reset(db):
    row = _mk(db, "a", key=None, missing=2)
    _run(db, _cfg(), ["a"])
    row = _reload(db, row)
    assert row.last_seen_search_key == KEY
    assert row.missing_runs_count == 0


def test_absent_listing_from_complete_search_increments_counter(db):
    gone = _mk(db, "gone")
    kept = _mk(db, "kept")
    stats = _run(db, _cfg(), ["kept"])
    assert _reload(db, gone).missing_runs_count == 1
    assert _reload(db, kept).missing_runs_count == 0
    assert stats["missing_incremented"] == 1


def test_full_page_is_not_evidence_of_absence(db):
    # pagina cheia (found >= page_capacity): o anuncio pode so ter sido empurrado p/ a pagina 2
    gone = _mk(db, "gone")
    seen = [f"s{i}" for i in range(40)]
    stats = _run(db, _cfg(page_capacity=40), seen)
    assert _reload(db, gone).missing_runs_count == 0
    assert stats["complete"] is False


def test_missing_capacity_never_counts_absence(db):
    gone = _mk(db, "gone")
    cfg = parse_presence_config({"inactive_reconcile": {"mode": "on"}})
    _run(db, cfg, ["x"])
    assert _reload(db, gone).missing_runs_count == 0


def test_empty_result_is_never_evidence(db):
    # 0 itens pode ser falha de parse/bloqueio silencioso
    gone = _mk(db, "gone")
    stats = _run(db, _cfg(), [], found=0)
    assert _reload(db, gone).missing_runs_count == 0
    assert stats["skipped"] == "empty"


def test_other_search_and_other_source_are_untouched(db):
    other_search = _mk(db, "o1", key=OTHER_KEY)
    other_source = _mk(db, "o2", source="mercadolivre")
    untagged = _mk(db, "o3", key=None)
    _run(db, _cfg(), ["x"])
    assert _reload(db, other_search).missing_runs_count == 0
    assert _reload(db, other_source).missing_runs_count == 0
    assert _reload(db, untagged).missing_runs_count == 0


def test_threshold_marks_inactive_in_on_mode(db):
    row = _mk(db, "gone", missing=2)
    stats = _run(db, _cfg(missing_runs=3), ["x"])
    row = _reload(db, row)
    assert row.missing_runs_count == 3
    assert row.status == "inativo"
    assert stats["marked_inactive"] == 1


def test_dry_run_counts_but_does_not_change_status(db):
    row = _mk(db, "gone", missing=2)
    stats = _run(db, _cfg(mode="dry_run"), ["x"])
    row = _reload(db, row)
    assert row.status == "ativo"
    assert row.missing_runs_count == 3
    assert stats["would_mark_inactive"] == 1
    assert stats["marked_inactive"] == 0


def test_inactive_listing_seen_again_is_reactivated(db):
    # cobre o modo incremental "cut", em que o anuncio visto nao passa pelo upsert
    row = _mk(db, "back", status="inativo", missing=3)
    stats = _run(db, _cfg(), ["back"])
    row = _reload(db, row)
    assert row.status == "ativo"
    assert row.missing_runs_count == 0
    assert stats["reactivated"] == 1


def test_suspect_status_is_not_overwritten(db):
    row = _mk(db, "sus", status="suspeito", missing=2)
    _run(db, _cfg(), ["other"])
    assert _reload(db, row).status == "suspeito"


def test_stale_net_marks_only_old_active_rows_in_on_mode(db):
    now = datetime.now(timezone.utc)
    old = _mk(db, "old", key=None, last_seen=now - timedelta(days=45))
    fresh = _mk(db, "fresh", key=None, last_seen=now - timedelta(days=2))
    other_source = _mk(db, "os", source="mercadolivre", last_seen=now - timedelta(days=45))
    stats = mark_stale_listings_inactive(db, source="olx", cfg=_cfg(stale_days=30), now=now)
    assert _reload(db, old).status == "inativo"
    assert _reload(db, fresh).status == "ativo"
    assert _reload(db, other_source).status == "ativo"
    assert stats["marked_inactive"] == 1


def test_stale_net_dry_run_only_counts(db):
    now = datetime.now(timezone.utc)
    old = _mk(db, "old", key=None, last_seen=now - timedelta(days=45))
    stats = mark_stale_listings_inactive(db, source="olx", cfg=_cfg(mode="dry_run", stale_days=30), now=now)
    assert _reload(db, old).status == "ativo"
    assert stats["would_mark_inactive"] == 1
    assert stats["marked_inactive"] == 0


def test_stale_net_disabled_without_stale_days(db):
    now = datetime.now(timezone.utc)
    old = _mk(db, "old", key=None, last_seen=now - timedelta(days=400))
    cfg = parse_presence_config({"inactive_reconcile": {"mode": "on", "page_capacity": 40}})
    stats = mark_stale_listings_inactive(db, source="olx", cfg=cfg, now=now)
    assert _reload(db, old).status == "ativo"
    assert stats["skipped"] == "no_stale_days"
