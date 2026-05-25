from datetime import datetime, timedelta, timezone

from app.models.system_log import SystemLog
from app.services.cross_source_dedupe_observability_service import build_cross_source_dedupe_shadow_report
from app.bot.admin_dedupe_shadow_report import render_cross_source_dedupe_shadow_report


def _add(db, message, payload=None, created_at=None):
    db.add(SystemLog(level="info", component="notifications_queue", message=message, payload=payload or {}, created_at=created_at or datetime.now(timezone.utc)))
    db.commit()


def test_service_empty_and_renderer_empty_state(db):
    out = build_cross_source_dedupe_shadow_report(db)
    assert out["events"]["shadow_hit"] == 0
    assert out["events"]["live_suppressed"] == 0
    assert out["events"]["evaluation_error"] == 0
    rendered = render_cross_source_dedupe_shadow_report(out)
    assert "Nenhum evento de shadow/live encontrado na janela." in rendered


def test_service_shadow_hits_aggregates_and_examples_limit(db):
    now = datetime.now(timezone.utc)
    for i in range(3):
        _add(db, "cross-source dedupe shadow hit", {"fingerprint": "fp-a", "current_source": "olx", "matched_source": "mercadolivre", "current_listing_id": f"cur-{i}", "matched_listing_id": f"mat-{i}", "wishlist_id": "wl1"}, now)
    _add(db, "cross-source dedupe shadow hit", {"fingerprint": "fp-b", "current_source": "mercadolivre", "matched_source": "olx", "wishlist_id": "wl2"}, now)

    out = build_cross_source_dedupe_shadow_report(db, hours=24, limit=2)
    assert out["events"]["shadow_hit"] == 4
    assert out["top_fingerprints"][0]["fingerprint"] == "fp-a"
    assert out["top_source_pairs"][0]["current_source"] == "olx"
    assert len(out["examples"]) == 2


def test_service_counts_suppressed_and_errors(db):
    _add(db, "cross-source dedupe suppressed", {"current_source": "olx", "matched_source": "mercadolivre"})
    _add(db, "cross-source dedupe evaluation error", {"err": "boom"})
    out = build_cross_source_dedupe_shadow_report(db)
    assert out["events"]["live_suppressed"] == 1
    assert out["events"]["evaluation_error"] == 1


def test_window_and_caps(db):
    now = datetime.now(timezone.utc)
    _add(db, "cross-source dedupe shadow hit", {"fingerprint": "in"}, now - timedelta(hours=2))
    _add(db, "cross-source dedupe shadow hit", {"fingerprint": "out"}, now - timedelta(hours=200))
    out = build_cross_source_dedupe_shadow_report(db, hours=0, limit=999)
    assert out["window_hours"] == 1
    assert out["limit"] == 50
    assert out["events"]["shadow_hit"] == 0
    out2 = build_cross_source_dedupe_shadow_report(db, hours=168, limit=1)
    assert out2["events"]["shadow_hit"] == 1
