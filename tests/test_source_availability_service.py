from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.system_log import SystemLog
from app.services.source_availability_service import is_in_cooldown


def _mk_log(db, component, level, message, created_at):
    row = SystemLog(id=uuid.uuid4(), level=level, component=component, message=message, created_at=created_at)
    db.add(row)
    db.commit()
    return row


def test_is_in_cooldown_false_when_no_logs(db):
    assert is_in_cooldown(db, "olx", 30) is False


def test_is_in_cooldown_true_for_recent_block(db):
    now = datetime.now(timezone.utc)
    _mk_log(db, "scraper_olx", "warning", "source_blocked", now - timedelta(minutes=5))
    assert is_in_cooldown(db, "olx", 30) is True


def test_is_in_cooldown_false_for_stale_block(db):
    now = datetime.now(timezone.utc)
    _mk_log(db, "scraper_olx", "warning", "source_blocked", now - timedelta(minutes=60))
    assert is_in_cooldown(db, "olx", 30) is False


def test_is_in_cooldown_ignores_other_components(db):
    now = datetime.now(timezone.utc)
    _mk_log(db, "scraper_webmotors", "warning", "source_blocked", now - timedelta(minutes=5))
    assert is_in_cooldown(db, "olx", 30) is False


def test_is_in_cooldown_ignores_non_warning_level(db):
    now = datetime.now(timezone.utc)
    _mk_log(db, "scraper_olx", "info", "source_blocked", now - timedelta(minutes=5))
    assert is_in_cooldown(db, "olx", 30) is False


def test_is_in_cooldown_ignores_other_messages(db):
    now = datetime.now(timezone.utc)
    _mk_log(db, "scraper_olx", "warning", "some_other_event", now - timedelta(minutes=5))
    assert is_in_cooldown(db, "olx", 30) is False
