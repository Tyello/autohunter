from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.services import source_execution_service as svc


class _ActivityStats:
    def to_dict(self):
        return {"ok": True}


def _plugin(name="mercadolivre", *, role="primary", supports_wishlist=True):
    return SimpleNamespace(
        name=name,
        scrape=lambda _url, ctx=None: [],
        build_url=lambda q: f"https://example.test/search?q={q}",
        supports_wishlist_monitoring=supports_wishlist,
        fetch_mode="http",
        default_extra={"operational_role": role},
    )


def _wishlist(query="civic si"):
    return SimpleNamespace(id=uuid.uuid4(), query=query)


def _setup_run(monkeypatch, *, source="mercadolivre", plugin=None, wishlists=None, scrape_result=None):
    plugin = plugin or _plugin(source)
    wishlists = [_wishlist()] if wishlists is None else wishlists
    scrape_result = scrape_result or {
        "ok": True,
        "found": 0,
        "inserted": 0,
        "matched": 0,
        "queued": 0,
        "already_notified": 0,
        "reason_buckets": {},
        "thumb_present": 0,
        "runtime_impl": "v2_canary",
        "adapter_meta": {"raw_count": 0, "normalized_count": 0},
    }
    monkeypatch.setattr(svc, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(svc, "get_source", lambda _src: plugin if _src == source else None)
    monkeypatch.setattr(svc, "_wishlist_eligibility_snapshot", lambda _db, _src: (wishlists, {"active_wishlists": len(wishlists)}))
    monkeypatch.setattr(svc, "scrape_ingest_match", lambda *_args, **_kwargs: dict(scrape_result))
    monkeypatch.setattr(svc, "reconcile_listing_activity_for_source_run", lambda *_args, **_kwargs: _ActivityStats())
    monkeypatch.setattr(svc, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(svc, "emit_event", lambda *_args, **_kwargs: None)
    return plugin


def _add_cfg(db, source="mercadolivre", *, enabled=True, extra=None):
    db.add(
        SourceConfig(
            source=source,
            is_enabled=enabled,
            sched_minutes=60,
            cooldown_minutes=0,
            rate_limit_seconds=0,
            browser_fallback_enabled=True,
            extra=extra or {"impl": "v1", "mercadolivre_v2_canary_enabled": True},
        )
    )


def _last_run(db, source="mercadolivre"):
    return db.query(SourceRun).filter(SourceRun.source == source).order_by(SourceRun.created_at.desc()).first()


def test_primary_zero_found_with_positive_baseline_flags_suspicious_without_error(db, monkeypatch):
    _add_cfg(db)
    db.add(
        SourceRun(
            source="mercadolivre",
            kind="scheduler",
            status="success",
            items_found=7,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db.commit()
    _setup_run(monkeypatch)

    res = svc.run_source_for_all_wishlists(db, "mercadolivre", kind="scheduler", force=True, ignore_backoff=True)

    assert res["status"] == "success"
    assert res["suspicious_zero_results"] is True
    assert res["zero_result_reason"] == "found_zero_with_recent_positive_baseline"
    assert res["zero_result_baseline_found"] == 7
    assert res["zero_result_runtime_impl"] == "v2_canary"
    assert res["run_summary"]["suspicious_zero_results"] is True
    assert "zero_result_suspect" in "\n".join(res["run_summary"].get("notes") or [])

    run = _last_run(db)
    assert run.status == "success"
    assert run.items_found == 0
    assert run.payload["suspicious_zero_results"] is True
    assert run.payload["run_summary"]["suspicious_zero_results"] is True


def test_zero_found_without_positive_baseline_does_not_flag_suspicious(db, monkeypatch):
    _add_cfg(db)
    db.commit()
    _setup_run(monkeypatch)

    res = svc.run_source_for_all_wishlists(db, "mercadolivre", kind="scheduler", force=True, ignore_backoff=True)

    assert res["status"] == "success"
    assert res.get("suspicious_zero_results") is not True
    assert _last_run(db).payload.get("suspicious_zero_results") is not True


def test_positive_found_does_not_flag_suspicious(db, monkeypatch):
    _add_cfg(db)
    db.add(SourceRun(source="mercadolivre", kind="scheduler", status="success", items_found=4))
    db.commit()
    scrape_result = {
        "ok": True,
        "found": 3,
        "inserted": 1,
        "matched": 1,
        "queued": 0,
        "already_notified": 0,
        "reason_buckets": {},
        "thumb_present": 1,
        "runtime_impl": "v2_canary",
    }
    _setup_run(monkeypatch, scrape_result=scrape_result)

    res = svc.run_source_for_all_wishlists(db, "mercadolivre", kind="scheduler", force=True, ignore_backoff=True)

    assert res["found"] == 3
    assert res.get("suspicious_zero_results") is not True


def test_disabled_or_no_wishlists_does_not_flag_suspicious(db, monkeypatch):
    source = "disabled_primary"
    _add_cfg(db, source=source, enabled=False, extra={})
    db.add(SourceRun(source=source, kind="scheduler", status="success", items_found=5))
    db.commit()
    payload = svc._zero_result_observability_payload(
        db=db,
        source=source,
        plugin=_plugin(source),
        cfg=db.query(SourceConfig).filter(SourceConfig.source == source).one(),
        total_found=0,
        total_wishlists=1,
        groups_count=1,
        group_summaries=[{"url": "u", "found": 0}],
        runtime_impl="v2_canary",
    )
    assert payload.get("suspicious_zero_results") is not True

    enabled = "enabled_primary"
    _add_cfg(db, source=enabled, enabled=True, extra={})
    db.add(SourceRun(source=enabled, kind="scheduler", status="success", items_found=5))
    db.commit()
    payload = svc._zero_result_observability_payload(
        db=db,
        source=enabled,
        plugin=_plugin(enabled),
        cfg=db.query(SourceConfig).filter(SourceConfig.source == enabled).one(),
        total_found=0,
        total_wishlists=0,
        groups_count=0,
        group_summaries=[],
        runtime_impl="v2_canary",
    )
    assert payload.get("suspicious_zero_results") is not True
