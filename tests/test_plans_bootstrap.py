from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.account import Account
from app.models.plan import PLAN_CODE_FREE, PLAN_CODE_PREMIUM, Plan
from app.models.subscription import Subscription
from app.services.plans_bootstrap_service import BASE_PLANS, PlansBootstrapError, ensure_base_plans
from app.services.users_service import get_or_create_user_by_chat


def test_ensure_base_plans_creates_free_plan(db):
    plans = ensure_base_plans(db)
    assert PLAN_CODE_FREE in plans

    free = db.query(Plan).filter(Plan.code == PLAN_CODE_FREE).first()
    assert free is not None
    assert free.name == BASE_PLANS[PLAN_CODE_FREE]["name"]
    assert free.daily_alert_limit == 5
    assert free.max_wishlists == 2

    premium = db.query(Plan).filter(Plan.code == PLAN_CODE_PREMIUM).first()
    assert premium is not None
    assert premium.daily_alert_limit == 15
    assert premium.max_wishlists == 10


def test_ensure_base_plans_is_idempotent(db):
    ensure_base_plans(db)
    ensure_base_plans(db)

    count = db.query(Plan).filter(Plan.code.in_(tuple(BASE_PLANS.keys()))).count()
    assert count == len(BASE_PLANS)


def test_user_bootstrap_lookup_finds_free_plan(db):
    user = get_or_create_user_by_chat(db, chat_id=55119999, username="bot_user")
    assert user is not None

    account = db.query(Account).filter(Account.id == user.account_id).first()
    assert account is not None

    sub = db.query(Subscription).filter(Subscription.account_id == account.id).first()
    assert sub is not None

    free = db.query(Plan).filter(Plan.code == PLAN_CODE_FREE).first()
    assert free is not None
    assert sub.plan_id == free.id


def test_bootstrap_error_is_clear_when_plans_table_is_missing(db):
    db.execute(text("DROP TABLE plans"))
    db.commit()

    with pytest.raises(PlansBootstrapError, match="Unable to bootstrap required plans"):
        get_or_create_user_by_chat(db, chat_id=55118888, username="broken_db")


def test_compat_existing_free_plan_keeps_same_row_and_updates_limits(db):
    custom_free = Plan(code=PLAN_CODE_FREE, name="Plano Grátis", daily_alert_limit=42, max_wishlists=7)
    db.add(custom_free)
    db.commit()

    plans = ensure_base_plans(db)
    db.refresh(custom_free)

    assert plans[PLAN_CODE_FREE].id == custom_free.id
    assert custom_free.daily_alert_limit == 5
    assert custom_free.max_wishlists == 2


def test_compat_existing_premium_plan_is_updated_to_official_limits(db):
    custom = Plan(code=PLAN_CODE_PREMIUM, name="Legacy Premium", daily_alert_limit=999, max_wishlists=999)
    db.add(custom)
    db.commit()

    ensure_base_plans(db)
    db.refresh(custom)

    assert custom.name == "Premium"
    assert custom.daily_alert_limit == 15
    assert custom.max_wishlists == 10
