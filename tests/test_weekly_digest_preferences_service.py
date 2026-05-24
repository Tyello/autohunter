import uuid

import pytest

from app.models.user import User
from app.services.weekly_digest_preferences_service import (
    get_or_create_digest_preference,
    set_weekly_digest_enabled,
    update_weekly_digest_preferences,
)


def _mk_user(db, chat_id=7777):
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="u", is_active=True)
    db.add(u)
    db.commit()
    return u


def test_defaults(db):
    u = _mk_user(db)
    pref = get_or_create_digest_preference(db, u.id)
    assert pref.weekly_digest_enabled is False
    assert pref.digest_days == 7
    assert pref.digest_limit == 10


def test_enable_disable(db):
    u = _mk_user(db, 7778)
    pref = set_weekly_digest_enabled(db, u.id, True)
    assert pref.weekly_digest_enabled is True
    pref = set_weekly_digest_enabled(db, u.id, False)
    assert pref.weekly_digest_enabled is False


def test_config_ranges(db):
    u = _mk_user(db, 7779)
    pref = update_weekly_digest_preferences(db, u.id, days=14, limit=5)
    assert pref.digest_days == 14
    assert pref.digest_limit == 5
    with pytest.raises(ValueError):
        update_weekly_digest_preferences(db, u.id, days=0)
    with pytest.raises(ValueError):
        update_weekly_digest_preferences(db, u.id, limit=99)
