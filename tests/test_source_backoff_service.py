from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.source_state import SourceState
from app.services.source_backoff_service import (
    is_source_allowed,
    mark_blocked,
    mark_bug,
    mark_error,
    mark_skipped,
    mark_success,
)


def test_is_source_allowed_creates_state_when_missing(db):
    availability = is_source_allowed(db, "olx")
    assert availability.is_allowed is True
    assert db.query(SourceState).filter(SourceState.source == "olx").one()


def test_mark_success_clears_backoff_and_counters(db):
    mark_error(db, "olx", base_cooldown_minutes=5, error="boom")
    db.commit()

    mark_success(db, "olx")
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.consecutive_failures == 0
    assert st.consecutive_blocks == 0
    assert st.next_allowed_at is None
    assert st.last_status == "success"


def test_mark_success_with_rate_limit_sets_next_allowed_at(db):
    mark_success(db, "olx", rate_limit_seconds=60)
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.next_allowed_at is not None
    naive_now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert st.next_allowed_at.replace(tzinfo=None) > naive_now


def test_mark_skipped_records_reason(db):
    mark_skipped(db, "olx", "already_recent")
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.last_status == "skipped:already_recent"


def test_mark_blocked_sets_backoff_and_is_not_allowed_after(db):
    minutes = mark_blocked(db, "olx", base_cooldown_minutes=10, http_status=403, url="https://x")
    db.commit()
    db.expire_all()

    assert minutes >= 10
    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    st.next_allowed_at = st.next_allowed_at.replace(tzinfo=timezone.utc)
    availability = is_source_allowed(db, "olx")
    assert availability.is_allowed is False
    assert availability.reason == "backoff"


def test_mark_blocked_escalates_exponentially_with_consecutive_blocks(db):
    m1 = mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()
    m2 = mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()
    m3 = mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()

    assert m1 == 10
    assert m2 == 20
    assert m3 == 40


def test_mark_blocked_respects_max_backoff_minutes(db):
    for _ in range(6):
        minutes = mark_blocked(db, "olx", base_cooldown_minutes=10, max_backoff_minutes=30)
        db.commit()
    assert minutes == 30


def test_mark_error_escalates_and_resets_blocks(db):
    mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()

    mark_error(db, "olx", base_cooldown_minutes=5, error="timeout")
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.consecutive_blocks == 0
    assert st.consecutive_failures == 1
    assert st.last_status == "error"


def test_mark_error_truncates_long_error_message(db):
    mark_error(db, "olx", base_cooldown_minutes=5, error="x" * 2000)
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert len(st.last_error) == 800


def test_mark_bug_uses_short_fixed_retry_without_exponential_escalation(db):
    mark_error(db, "olx", base_cooldown_minutes=5, error="boom")
    db.commit()

    minutes = mark_bug(db, "olx", error="NameError: x is not defined")
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.consecutive_failures == 0
    assert st.consecutive_blocks == 0
    assert minutes <= 5
    assert st.last_payload["bug"] is True
