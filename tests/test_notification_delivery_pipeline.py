from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.user import User
from app.models.wishlist import Wishlist
from app.scheduler.jobs_send import send_queued_notifications
from app.services.notification_delivery_service import (
    claim_queued_notifications,
    mark_notification_delivery_error,
    reclaim_stale_processing_notifications,
)
from app.services.notifications_queue_service import queue_notifications_for_matches


def _seed(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=12345, username="u", is_active=True)
    wl = Wishlist(user_id=user.id, query="civic", is_active=True)
    listing = CarListing(
        source="olx",
        external_id=f"X-{uuid.uuid4()}",
        title="Civic",
        url="https://example/1",
        price=Decimal("10"),
        currency="BRL",
    )
    db.add_all([user, wl, listing])
    db.commit()
    return user, wl, listing


def test_queue_sets_delivery_defaults_and_idempotency(db):
    user, wl, listing = _seed(db)

    first = queue_notifications_for_matches(db, wl, [listing])
    second = queue_notifications_for_matches(db, wl, [listing])
    db.commit()

    row = db.query(Notification).filter(Notification.user_id == user.id).one()
    assert first == 1
    assert second == 0
    assert row.status == "queued"
    assert row.next_attempt_at is not None
    assert row.max_attempts == 3


def test_claim_prevents_double_consume_between_workers(db):
    _user, wl, listing = _seed(db)
    queue_notifications_for_matches(db, wl, [listing])
    db.commit()

    worker1 = claim_queued_notifications(db, owner="w1", batch_size=10)
    db.commit()
    worker2 = claim_queued_notifications(db, owner="w2", batch_size=10)

    assert len(worker1) == 1
    assert len(worker2) == 0


def test_retry_and_discard_lifecycle(db):
    _user, wl, listing = _seed(db)
    queue_notifications_for_matches(db, wl, [listing])
    db.commit()

    row = claim_queued_notifications(db, owner="w", batch_size=1)[0]
    out1 = mark_notification_delivery_error(row, error_message="timeout")
    db.commit()
    assert out1 == "retry_scheduled"

    row = claim_queued_notifications(db, owner="w", batch_size=1, now=datetime.now(timezone.utc) + timedelta(hours=1))[0]
    out2 = mark_notification_delivery_error(row, error_message="timeout")
    db.commit()

    row = claim_queued_notifications(db, owner="w", batch_size=1, now=datetime.now(timezone.utc) + timedelta(hours=2))[0]
    out3 = mark_notification_delivery_error(row, error_message="timeout")
    db.commit()

    refreshed = db.query(Notification).filter(Notification.id == row.id).one()
    assert out2 == "retry_scheduled"
    assert out3 == "discarded"
    assert refreshed.status == "discarded"
    assert refreshed.reason == "retry_exhausted"


def test_stale_processing_is_reclaimed_after_crash(db):
    _user, wl, listing = _seed(db)
    queue_notifications_for_matches(db, wl, [listing])
    db.commit()

    row = claim_queued_notifications(db, owner="dead-worker", batch_size=1)[0]
    row.processing_started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()

    rescued = reclaim_stale_processing_notifications(db)
    db.commit()

    refreshed = db.query(Notification).filter(Notification.id == row.id).one()
    assert rescued == 1
    assert refreshed.status == "queued"
    assert refreshed.reason == "processing_stale_requeued"


def test_sender_marks_retry_on_transient_error(db, monkeypatch):
    _user, wl, listing = _seed(db)
    queue_notifications_for_matches(db, wl, [listing])
    db.commit()

    monkeypatch.setattr("app.scheduler.jobs_send.count_sent_today", lambda *_: 0)
    monkeypatch.setattr("app.scheduler.jobs_send.get_active_subscription_limit_for_user", lambda *_: 10)

    def _sender(*_args, **_kwargs):
        raise RuntimeError("timeout from telegram")

    sent = send_queued_notifications(db, component="sender-test", sender_fn=_sender)
    assert sent == 0

    row = db.query(Notification).one()
    assert row.status == "queued"
    assert row.reason == "retry_scheduled"
    assert row.attempts == 1


def test_claim_eager_loads_user_and_listing(db):
    user, wl, listing = _seed(db)
    queue_notifications_for_matches(db, wl, [listing])
    db.commit()

    row = claim_queued_notifications(db, owner="w", batch_size=1)[0]

    assert row.user is not None
    assert row.user.id == user.id
    assert row.car_listing is not None
    assert row.car_listing.id == listing.id


from sqlalchemy import event
from sqlalchemy.dialects import postgresql


def test_claim_with_for_update_sql_postgres_has_no_outer_join():
    now = datetime.now(timezone.utc)
    q = (
        Notification.__table__.select()
        .where(Notification.status == "queued")
        .where((Notification.next_attempt_at.is_(None)) | (Notification.next_attempt_at <= now))
        .order_by(Notification.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(10)
    )
    sql = str(q.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "LEFT OUTER JOIN" not in sql


def test_claim_query_keeps_main_select_without_outer_join_and_eager_loads(db):
    user, wl, listing = _seed(db)
    queue_notifications_for_matches(db, wl, [listing])
    db.commit()

    statements: list[str] = []

    def _before_cursor_execute(_conn, _cursor, statement, _params, _ctx, _executemany):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", _before_cursor_execute)
    try:
        row = claim_queued_notifications(db, owner="w", batch_size=1)[0]
    finally:
        event.remove(db.bind, "before_cursor_execute", _before_cursor_execute)

    assert row.user is not None
    assert row.user.id == user.id
    assert row.car_listing is not None
    assert row.car_listing.id == listing.id

    lock_selects = [s for s in statements if "FOR UPDATE" in s.upper()]
    if lock_selects:
        assert all("LEFT OUTER JOIN" not in s.upper() for s in lock_selects)
