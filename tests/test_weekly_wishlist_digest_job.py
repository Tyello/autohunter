from __future__ import annotations

from datetime import datetime, timezone
import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.scheduler.weekly_wishlist_digest_job import job_weekly_wishlist_digest


def _mk_user_with_wishlist(db, *, chat_id: int = 7001) -> User:
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username="digest", is_active=True)
    db.add(user)
    db.commit()

    wishlist = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wishlist)
    db.commit()
    return user


def test_weekly_digest_job_avoids_duplicate_same_day(db, monkeypatch):
    _mk_user_with_wishlist(db)

    monkeypatch.setattr(
        "app.scheduler.weekly_wishlist_digest_job._now_utc",
        lambda: datetime(2026, 1, 3, 13, 0, tzinfo=timezone.utc),  # sábado
    )

    sent_messages: list[tuple[int, str]] = []

    def _fake_send(chat_id: int, text: str) -> None:
        sent_messages.append((chat_id, text))

    monkeypatch.setattr("app.scheduler.weekly_wishlist_digest_job._send_text", _fake_send)

    job_weekly_wishlist_digest()
    first_count = len(sent_messages)
    assert first_count >= 1

    job_weekly_wishlist_digest()
    assert len(sent_messages) == first_count


def test_weekly_digest_job_only_runs_on_saturday(db, monkeypatch):
    _mk_user_with_wishlist(db, chat_id=7002)
    monkeypatch.setattr(
        "app.scheduler.weekly_wishlist_digest_job._now_utc",
        lambda: datetime(2026, 1, 2, 13, 0, tzinfo=timezone.utc),  # sexta
    )

    called = {"count": 0}

    def _fake_send(chat_id: int, text: str) -> None:
        called["count"] += 1

    monkeypatch.setattr("app.scheduler.weekly_wishlist_digest_job._send_text", _fake_send)

    job_weekly_wishlist_digest()
    assert called["count"] == 0
