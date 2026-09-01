from __future__ import annotations

from app.models.source_url_cursor import SourceUrlCursor
from app.services.source_url_cursors_service import get_cursor, touch_cursor


def test_get_cursor_returns_none_when_missing(db):
    assert get_cursor(db, source="olx", url="https://olx.com/x") is None


def test_get_cursor_returns_none_for_blank_source_or_url(db):
    assert get_cursor(db, source="", url="https://olx.com/x") is None
    assert get_cursor(db, source="olx", url="") is None


def test_touch_cursor_creates_row_on_first_call(db):
    row = touch_cursor(db, source="OLX", url="https://olx.com/x", last_external_id="ext-1")
    db.commit()

    assert row.source == "olx"
    assert row.last_external_id == "ext-1"
    assert row.runs == 1
    assert row.last_seen_at is not None


def test_touch_cursor_increments_runs_on_repeated_calls(db):
    touch_cursor(db, source="olx", url="https://olx.com/x")
    db.commit()
    touch_cursor(db, source="olx", url="https://olx.com/x")
    db.commit()
    row = touch_cursor(db, source="olx", url="https://olx.com/x")
    db.commit()

    assert row.runs == 3


def test_touch_cursor_without_external_id_does_not_update_last_seen(db):
    touch_cursor(db, source="olx", url="https://olx.com/x", last_external_id="ext-1")
    db.commit()
    row = db.query(SourceUrlCursor).filter(SourceUrlCursor.source == "olx").one()
    first_seen = row.last_seen_at

    touch_cursor(db, source="olx", url="https://olx.com/x")
    db.commit()

    row = db.query(SourceUrlCursor).filter(SourceUrlCursor.source == "olx").one()
    assert row.last_seen_at == first_seen
    assert row.last_external_id == "ext-1"


def test_touch_cursor_raises_on_missing_source_or_url(db):
    import pytest

    with pytest.raises(ValueError):
        touch_cursor(db, source="", url="https://olx.com/x")
    with pytest.raises(ValueError):
        touch_cursor(db, source="olx", url="")
