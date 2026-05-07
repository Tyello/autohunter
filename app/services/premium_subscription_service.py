from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.plan import PLAN_CODE_PREMIUM, Plan
from app.models.subscription import Subscription
from app.models.user import User


@dataclass
class PremiumActivationResult:
    ok: bool
    error: str | None = None
    period_days: int | None = None
    period_label: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    subscription_id: str | None = None


@dataclass
class ExpirationResult:
    expired_count: int
    expired_chat_ids: list[int]


def _resolve_period(period: str) -> tuple[int, str] | None:
    norm = (period or "").strip().lower()
    if norm in {"monthly", "30d"}:
        return 30, "mensal"
    if norm in {"annual", "365d"}:
        return 365, "anual"
    return None


def activate_manual_premium(
    db: Session,
    user_id,
    period: str,
    activated_by: str | None = None,
    source: str = "manual_mercado_pago",
) -> PremiumActivationResult:
    resolved = _resolve_period(period)
    if not resolved:
        return PremiumActivationResult(ok=False, error="Período inválido.")
    period_days, period_label = resolved

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not getattr(user, "account_id", None):
        return PremiumActivationResult(ok=False, error="Usuário inválido para assinatura.")

    plan = db.query(Plan).filter(Plan.code == PLAN_CODE_PREMIUM).first()
    if not plan:
        return PremiumActivationResult(ok=False, error="Plano premium não encontrado no banco.")

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=period_days)

    active = (
        db.query(Subscription)
        .filter(Subscription.account_id == user.account_id)
        .filter(Subscription.status == "active")
        .all()
    )
    for sub in active:
        sub.status = "canceled"
        sub.ends_at = now

    meta: dict[str, Any] = {
        "period": period.lower(),
        "activated_by": activated_by,
        "activated_at": now.isoformat(),
    }

    sub = Subscription(
        account_id=user.account_id,
        plan_id=plan.id,
        status="active",
        source=source,
        starts_at=now,
        ends_at=end,
        current_period_start=now,
        current_period_end=end,
        metadata_json=meta,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return PremiumActivationResult(
        ok=True,
        period_days=period_days,
        period_label=period_label,
        current_period_start=now,
        current_period_end=end,
        subscription_id=str(sub.id),
    )


def expire_due_premium_subscriptions(db: Session, now: datetime | None = None) -> ExpirationResult:
    now = now or datetime.now(timezone.utc)
    expired_chat_ids: set[int] = set()
    due_subs = (
        db.query(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .filter(Plan.code == PLAN_CODE_PREMIUM)
        .filter(Subscription.status == "active")
        .all()
    )
    changed = 0
    touched_accounts: set[Any] = set()
    for sub in due_subs:
        effective_end = _as_utc(getattr(sub, "current_period_end", None) or getattr(sub, "ends_at", None))
        if effective_end and effective_end <= now:
            sub.status = "expired"
            sub.ends_at = effective_end
            changed += 1
            touched_accounts.add(sub.account_id)
    if touched_accounts:
        users = db.query(User).filter(User.account_id.in_(list(touched_accounts))).all()
        for user in users:
            if getattr(user, "telegram_chat_id", None):
                expired_chat_ids.add(int(user.telegram_chat_id))
    if changed:
        db.commit()
    return ExpirationResult(expired_count=changed, expired_chat_ids=sorted(expired_chat_ids))
def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
