from __future__ import annotations

from typing import Final

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.plan import PLAN_CODE_FREE, PLAN_CODE_PRO, PLAN_CODE_ULTRA, Plan

BASE_PLANS: Final[dict[str, dict[str, int | str | bool]]] = {
    PLAN_CODE_FREE: {
        "name": "Free",
        "daily_alert_limit": 10,
        "max_wishlists": 3,
        "is_active": True,
    },
    PLAN_CODE_PRO: {
        "name": "Pro",
        "daily_alert_limit": 50,
        "max_wishlists": 10,
        "is_active": True,
    },
    PLAN_CODE_ULTRA: {
        "name": "Ultra",
        "daily_alert_limit": 200,
        "max_wishlists": 30,
        "is_active": True,
    },
}


class PlansBootstrapError(RuntimeError):
    """Raised when required plans cannot be loaded/bootstrapped."""


def ensure_base_plans(db: Session) -> dict[str, Plan]:
    """Guarantee required plans exist in an idempotent way.

    Uses `code` as stable identifier and never duplicates rows because `plans.code`
    is unique. Existing rows are preserved; only missing base plans are inserted.
    """

    try:
        plans_by_code = {
            p.code: p
            for p in db.query(Plan).filter(Plan.code.in_(tuple(BASE_PLANS.keys()))).all()
        }

        for code, attrs in BASE_PLANS.items():
            if code in plans_by_code:
                continue

            plan = Plan(
                code=code,
                name=str(attrs["name"]),
                daily_alert_limit=int(attrs["daily_alert_limit"]),
                max_wishlists=int(attrs["max_wishlists"]),
                is_active=bool(attrs["is_active"]),
            )
            db.add(plan)
            plans_by_code[code] = plan

        db.flush()
        return plans_by_code
    except SQLAlchemyError as exc:
        raise PlansBootstrapError(
            "Unable to bootstrap required plans (free/pro/ultra). "
            "Check DATABASE_URL and run migrations."
        ) from exc


def get_required_plan(db: Session, code: str) -> Plan:
    plans = ensure_base_plans(db)
    plan = plans.get(code)
    if not plan:
        raise PlansBootstrapError(
            f"Required plan '{code}' not found after bootstrap. "
            "Check migrations/seed integrity."
        )
    return plan
