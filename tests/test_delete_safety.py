from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.db.base import Base
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.models.wishlist_listing_activity import WishlistListingActivity
from app.models.wishlist_token import WishlistToken
from app.models.notification import Notification
from app.models.telemetry_event import TelemetryEvent
from app.models.car_listing import CarListing
from app.models.system_log import SystemLog
from app.services.wishlists_service import remove_all_wishlists, remove_wishlist


def _enable_fk(db) -> None:
    db.execute(text("PRAGMA foreign_keys=ON"))


def test_no_model_fk_uses_cascade_delete() -> None:
    cascades: list[tuple[str, str]] = []
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if (fk.ondelete or "").upper() == "CASCADE":
                cascades.append((table.name, str(fk.target_fullname)))

    assert cascades == []


def test_no_orm_relationship_uses_delete_cascade() -> None:
    dangerous: list[str] = []

    for mapper in Base.registry.mappers:
        for rel in mapper.relationships:
            cascade_options = {opt.lower() for opt in rel.cascade}
            if "delete" in cascade_options or "delete-orphan" in cascade_options:
                dangerous.append(f"{mapper.class_.__name__}.{rel.key}={sorted(cascade_options)}")

    assert dangerous == []


def test_no_migration_reintroduces_on_delete_cascade() -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    offenders: list[str] = []

    for migration_file in sorted(migrations_dir.glob("*.py")):
        content = migration_file.read_text(encoding="utf-8").upper()
        if "ONDELETE=\"CASCADE\"" in content or "ONDELETE='CASCADE'" in content:
            offenders.append(str(migration_file.relative_to(Path(__file__).resolve().parents[1])))

    assert offenders == []


def test_delete_user_with_wishlist_is_restricted(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=123456)
    db.add(user)
    db.flush()
    db.add(Wishlist(user_id=user.id, query="civic", is_active=True))
    db.commit()

    db.delete(user)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_delete_wishlist_with_filters_requires_explicit_cleanup(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999001)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="gol", is_active=True)
    db.add(wishlist)
    db.flush()

    db.add(WishlistFilter(wishlist_id=wishlist.id, field="year", operator="gte", value="2015"))
    db.commit()

    db.delete(wishlist)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_remove_wishlist_service_soft_deletes_wishlist(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999002)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="corolla", is_active=True)
    db.add(wishlist)
    db.flush()

    db.add(WishlistFilter(wishlist_id=wishlist.id, field="source", operator="eq", value="olx"))
    db.commit()

    ok, _msg = remove_wishlist(db, user.id, 1)
    assert ok is True
    assert db.query(Wishlist).filter(Wishlist.id == wishlist.id).one().deleted_at is not None


def test_remove_all_wishlists_service_soft_deletes_wishlists(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999003)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="jetta", is_active=True)
    db.add(wishlist)
    db.flush()

    db.add(WishlistFilter(wishlist_id=wishlist.id, field="year", operator="gte", value="2018"))
    db.commit()

    ok, _msg = remove_all_wishlists(db, user.id)
    assert ok is True
    assert db.query(Wishlist).filter(Wishlist.user_id == user.id).one().deleted_at is not None


def test_remove_wishlist_service_writes_explicit_audit_log(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999004)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="tiguan", is_active=True)
    db.add(wishlist)
    db.commit()

    ok, _msg = remove_wishlist(db, user.id, 1)
    assert ok is True

    evt = (
        db.query(SystemLog)
        .filter(SystemLog.event_type == "wishlist_delete_explicit")
        .order_by(SystemLog.created_at.desc())
        .first()
    )
    assert evt is not None
    assert evt.payload["wishlist_id"] == str(wishlist.id)
    assert evt.payload["user_id"] == str(user.id)
    assert evt.payload["caller"] == "wishlists_service.remove_wishlist"
    assert evt.payload["flow_context"] == "wishlist_remove"


def test_scheduler_and_runall_paths_do_not_call_wishlist_remove_services() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    targets = [
        root / "app" / "scheduler" / "run.py",
        root / "app" / "scheduler" / "jobs.py",
        root / "app" / "services" / "source_execution_service.py",
        root / "app" / "bot" / "handlers_admin.py",
    ]

    for path in targets:
        content = path.read_text(encoding="utf-8")
        if "remove_wishlist(" in content or "remove_all_wishlists(" in content:
            offenders.append(str(path.relative_to(root)))

    assert offenders == []


def test_remove_wishlist_service_soft_deletes_filters_only_and_preserves_history(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999005)
    db.add(user)
    db.flush()

    listing = CarListing(source="olx", external_id="ad-1", url="https://example.com/ad-1", title="Car")
    db.add(listing)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="civic", is_active=True)
    db.add(wishlist)
    db.flush()

    db.add(WishlistFilter(wishlist_id=wishlist.id, field="source", operator="eq", value="olx"))
    db.add(WishlistToken(wishlist_id=wishlist.id, token="honda"))
    db.add(
        WishlistListingActivity(
            wishlist_id=wishlist.id,
            listing_identity_key="olx:ad-1",
            source_name="olx",
            source_listing_id="ad-1",
            listing_url="https://example.com/ad-1",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
    )

    notification = Notification(user_id=user.id, wishlist_id=wishlist.id, car_listing_id=listing.id, status="queued")
    telemetry = TelemetryEvent(event_type="test_evt", fingerprint="fp-1", wishlist_id=wishlist.id, user_id=user.id)
    db.add(notification)
    db.add(telemetry)
    db.commit()

    ok, _msg = remove_wishlist(db, user.id, 1)
    assert ok is True

    removed = db.query(Wishlist).filter(Wishlist.id == wishlist.id).one()
    assert removed.deleted_at is not None
    assert removed.is_active is False
    assert db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id, WishlistFilter.is_active.is_(True)).count() == 0
    assert db.query(WishlistListingActivity).filter(WishlistListingActivity.wishlist_id == wishlist.id).count() == 1
    assert db.query(WishlistToken).filter(WishlistToken.wishlist_id == wishlist.id).count() == 1

    notification_db = db.query(Notification).filter(Notification.id == notification.id).first()
    telemetry_db = db.query(TelemetryEvent).filter(TelemetryEvent.id == telemetry.id).first()
    assert notification_db is not None
    assert telemetry_db is not None
    assert notification_db.wishlist_id == wishlist.id
    assert telemetry_db.wishlist_id == wishlist.id


def test_remove_wishlist_service_is_transactional_on_delete_failure(db, monkeypatch):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999006)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="focus", is_active=True)
    db.add(wishlist)
    db.flush()

    db.add(WishlistFilter(wishlist_id=wishlist.id, field="year", operator="gte", value="2019"))
    db.add(WishlistToken(wishlist_id=wishlist.id, token="ford"))
    db.add(
        WishlistListingActivity(
            wishlist_id=wishlist.id,
            listing_identity_key="olx:ad-2",
            source_name="olx",
            source_listing_id="ad-2",
            listing_url="https://example.com/ad-2",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    original_commit = db.commit

    def _boom():
        raise SQLAlchemyError("forced-soft-delete-failure")

    monkeypatch.setattr(db, "commit", _boom)

    ok, msg = remove_wishlist(db, user.id, 1)
    assert ok is False
    assert "falha no banco" in msg

    monkeypatch.setattr(db, "commit", original_commit)
    db.rollback()
    assert db.query(Wishlist).filter(Wishlist.id == wishlist.id).one().deleted_at is None
    assert db.query(WishlistFilter).filter(WishlistFilter.wishlist_id == wishlist.id, WishlistFilter.is_active.is_(True)).count() == 1
    assert db.query(WishlistListingActivity).filter(WishlistListingActivity.wishlist_id == wishlist.id).count() == 1
    assert db.query(WishlistToken).filter(WishlistToken.wishlist_id == wishlist.id).count() == 1


def test_remove_wishlist_service_without_dependencies_still_removes(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999007)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="polo", is_active=True)
    db.add(wishlist)
    db.commit()

    ok, _msg = remove_wishlist(db, user.id, 1)
    assert ok is True
    assert db.query(Wishlist).filter(Wishlist.id == wishlist.id).one().deleted_at is not None
