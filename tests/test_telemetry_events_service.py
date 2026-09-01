from __future__ import annotations

import uuid

from app.models.telemetry_event import TelemetryEvent
from app.services.telemetry_events_service import emit_event


def test_emit_event_inserts_row_with_generated_fingerprint(db):
    row = emit_event(db, level="info", event_type="pipeline_summary", source="olx", message="ok")
    db.commit()

    assert row.id is not None
    assert row.fingerprint
    fetched = db.query(TelemetryEvent).filter(TelemetryEvent.id == row.id).one()
    assert fetched.event_type == "pipeline_summary"
    assert fetched.source == "olx"


def test_emit_event_uses_provided_fingerprint(db):
    row = emit_event(db, level="warn", event_type="http_blocked", fingerprint="custom-fp")
    db.commit()
    assert row.fingerprint == "custom-fp"


def test_emit_event_stores_tags_in_memory(db):
    # ARRAY(Text) columns aren't exercised against SQLite in this suite; verify
    # the in-memory assignment without a DB round-trip (no flush/commit).
    row = emit_event(db, level="error", event_type="parse_failed", tags=["scrape", "parse"])
    assert row.tags == ["scrape", "parse"]
    db.rollback()


def test_emit_event_stores_evidence(db):
    row = emit_event(
        db,
        level="error",
        event_type="parse_failed",
        source="webmotors",
        evidence={"url": "https://example.com"},
    )
    db.commit()

    fetched = db.query(TelemetryEvent).filter(TelemetryEvent.id == row.id).one()
    assert fetched.evidence == {"url": "https://example.com"}


def test_emit_event_links_optional_foreign_keys(db):
    wishlist_id = uuid.uuid4()
    row = emit_event(db, level="info", event_type="pipeline_summary", wishlist_id=wishlist_id)
    assert row.wishlist_id == wishlist_id


def test_emit_event_does_not_commit(db):
    emit_event(db, level="info", event_type="pipeline_summary")
    db.rollback()
    assert db.query(TelemetryEvent).count() == 0
