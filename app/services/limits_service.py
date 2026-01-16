from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.settings import settings
from app.models.notification import Notification
from app.models.subscription import Subscription
from app.models.plan import Plan
from app.models.user import User


def should_send_daily_limit_notice(user) -> bool:
    """
    Helper para o sender_job decidir se manda aviso 1x/dia.
    NÃO é usado dentro do cálculo de limite.
    """
    now = datetime.now(timezone.utc)
    last = getattr(user, "last_daily_limit_notice_at", None)
    if last is None:
        return True
    return last.date() != now.date()


def count_sent_today(db: Session, user_id) -> int:
    """
    Conta notificações 'sent' desde 00:00 UTC.
    """
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id)
        .filter(Notification.status == "sent")
        .filter(Notification.sent_at >= day_start)
        .scalar()
    )
    return int(count or 0)


def get_active_subscription_limit_for_user(db: Session, user_id) -> int:
    """
    Limite diário vindo do plano ativo da ACCOUNT do usuário.
    Override (na subscription) tem prioridade.
    Fallback: settings.default_alert_limit
    """
    u: User | None = db.query(User).filter(User.id == user_id).first()
    if not u or not getattr(u, "account_id", None):
        return int(getattr(settings, "default_alert_limit", 10))

    row = (
        db.query(Subscription, Plan)
        .join(Plan, Plan.id == Subscription.plan_id)
        .filter(Subscription.account_id == u.account_id)
        .filter(Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
        .first()
    )

    if not row:
        return int(getattr(settings, "default_alert_limit", 10))

    subscription, plan = row

    if subscription.daily_alert_limit_override is not None:
        return int(subscription.daily_alert_limit_override)

    return int(plan.daily_alert_limit)


def get_daily_limit_for_user(db: Session, user_id) -> int:
    """
    Compat: handlers chamam isso.
    """
    return get_active_subscription_limit_for_user(db, user_id)


def can_send_more_today(db: Session, user_id) -> bool:
    """
    True se ainda pode enviar hoje.
    """
    sent = count_sent_today(db, user_id)
    limit = get_active_subscription_limit_for_user(db, user_id)
    return sent < limit
