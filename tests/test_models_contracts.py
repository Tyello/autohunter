from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.account import Account
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.plan import Plan
from app.models.source_state import SourceState
from app.models.subscription import Subscription
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.models.auction_event import AuctionEvent
from app.models.auction_lot import AuctionLot


def _mk_user() -> User:
    return User(id=uuid.uuid4(), telegram_chat_id=123456789, username="tester")


def test_user_defaults_plan_and_active(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=999999)
    db.add(user)
    db.commit()

    db.refresh(user)
    assert user.is_active is True
    assert user.plan == "free"


def test_plan_code_unique(db):
    p1 = Plan(code="free", name="Free", daily_alert_limit=5)
    p2 = Plan(code="free", name="Free 2", daily_alert_limit=10)

    db.add(p1)
    db.commit()

    db.add(p2)
    with pytest.raises(IntegrityError):
        db.commit()


def test_subscription_starts_at_default_not_null(db):
    acc = Account(type="personal", name="Test")
    plan = Plan(code="free", name="Free", daily_alert_limit=30)
    db.add_all([acc, plan])
    db.commit()

    sub = Subscription(account_id=acc.id, plan_id=plan.id)
    db.add(sub)
    db.commit()

    db.refresh(sub)
    assert sub.starts_at is not None


def test_wishlist_filter_unique_constraint(db):
    user = _mk_user()
    db.add(user)
    db.commit()

    w = Wishlist(user_id=user.id, query="civic si")
    db.add(w)
    db.commit()

    f1 = WishlistFilter(wishlist_id=w.id, field="source", operator="eq", value="olx")
    f2 = WishlistFilter(wishlist_id=w.id, field="source", operator="eq", value="olx")

    db.add(f1)
    db.commit()

    db.add(f2)
    with pytest.raises(IntegrityError):
        db.commit()


def test_source_state_unique_source_and_defaults(db):
    s1 = SourceState(source="olx")
    s2 = SourceState(source="olx")

    db.add(s1)
    db.commit()
    db.refresh(s1)

    assert s1.consecutive_blocks == 0
    assert s1.consecutive_failures == 0

    db.add(s2)
    with pytest.raises(IntegrityError):
        db.commit()


def test_notification_default_status(db):
    user = _mk_user()
    db.add(user)

    listing = CarListing(
        source="olx",
        external_id="1",
        title="Honda Civic SI 1994",
        url="https://example.com/1",
        price=Decimal("32000"),
        currency="BRL",
    )
    db.add(listing)
    db.commit()

    n = Notification(user_id=user.id, wishlist_id=None, car_listing_id=listing.id)
    db.add(n)
    db.commit()

    db.refresh(n)
    assert n.status == "queued"


def test_auction_indexes_and_unique_constraints_declared():
    events_indexes = {idx.name: idx for idx in AuctionEvent.__table__.indexes}
    assert "uq_auction_events_source_external_id" in events_indexes
    assert events_indexes["uq_auction_events_source_external_id"].unique is True

    lots_indexes = {idx.name: idx for idx in AuctionLot.__table__.indexes}
    assert "uq_auction_lots_source_external_id" in lots_indexes
    assert lots_indexes["uq_auction_lots_source_external_id"].unique is True
    assert "ix_auction_lots_source_status" in lots_indexes
    assert "ix_auction_lots_auction_end_at" in lots_indexes
    assert "ix_auction_lots_make_model_year" in lots_indexes
    assert "ix_auction_lots_item_type_status" in lots_indexes
    assert "ix_auction_lots_city_state" in lots_indexes
