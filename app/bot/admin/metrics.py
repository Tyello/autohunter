from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.plan import PLAN_CODE_PREMIUM, Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.wishlist import Wishlist


def _pct(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round((part / total) * 100))


def _format_sources(source_rows: Iterable[tuple[str | None, int]]) -> list[str]:
    rows = [(name or "-", int(count or 0)) for name, count in source_rows]
    if not rows:
        return ["-"]
    return [f"{name}: {count} alertas" for name, count in rows]


def _render_metrics(data: dict) -> str:
    users_total = int(data.get("users_total") or 0)
    users_7d = int(data.get("users_7d") or 0)
    with_active = int(data.get("users_with_active") or 0)
    with_alert_7d = int(data.get("users_with_alert_7d") or 0)
    wish_7d = int(data.get("wishlists_7d") or 0)
    wish_active_total = int(data.get("wishlists_active_total") or 0)
    sent_today = int(data.get("alerts_sent_today") or 0)
    sent_7d = int(data.get("alerts_sent_7d") or 0)
    backlog = int(data.get("alerts_backlog") or 0)
    free_users = int(data.get("free_users") or 0)
    premium_users = int(data.get("premium_users") or 0)
    premium_pct = _pct(premium_users, users_total)

    lines = [
        "📊 Métricas — Garagem Alvo",
        "",
        "Usuários",
        f"Total: {users_total} · Novos 7d: {users_7d}",
        f"Com busca ativa: {with_active} ({_pct(with_active, users_total)}%)",
        f"Receberam alerta 7d: {with_alert_7d} ({_pct(with_alert_7d, users_total)}%)",
        "",
        "Buscas",
        f"Criadas 7d: {wish_7d} · Total ativas: {wish_active_total}",
        "",
        "Alertas",
        f"Enviados hoje (UTC): {sent_today} · Enviados 7d: {sent_7d}",
        f"Backlog atual: {backlog}",
        "",
        "Conversão",
        f"Free: {free_users} · Premium: {premium_users} ({premium_pct}%)",
        "",
        "Sources (7d)",
        *_format_sources(data.get("sources_7d") or []),
    ]
    return "\n".join(lines)


async def admin_metrics(update, raw_args: list[str]):
    _ = raw_args
    now = datetime.now(timezone.utc)
    start_7d = now - timedelta(days=7)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with SessionLocal() as db:
        users_total = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
        users_7d = db.query(func.count(User.id)).filter(User.is_active.is_(True)).filter(User.created_at >= start_7d).scalar() or 0

        users_with_active = (
            db.query(func.count(func.distinct(Wishlist.user_id)))
            .join(User, User.id == Wishlist.user_id)
            .filter(User.is_active.is_(True))
            .filter(Wishlist.is_active.is_(True))
            .scalar()
            or 0
        )

        users_with_alert_7d = (
            db.query(func.count(func.distinct(Notification.user_id)))
            .join(User, User.id == Notification.user_id)
            .filter(User.is_active.is_(True))
            .filter(Notification.status == "sent")
            .filter(Notification.sent_at.is_not(None))
            .filter(Notification.sent_at >= start_7d)
            .scalar()
            or 0
        )

        wishlists_7d = (
            db.query(func.count(Wishlist.id))
            .join(User, User.id == Wishlist.user_id)
            .filter(User.is_active.is_(True))
            .filter(Wishlist.created_at >= start_7d)
            .scalar()
            or 0
        )
        wishlists_active_total = (
            db.query(func.count(Wishlist.id))
            .join(User, User.id == Wishlist.user_id)
            .filter(User.is_active.is_(True))
            .filter(Wishlist.is_active.is_(True))
            .scalar()
            or 0
        )

        alerts_sent_today = (
            db.query(func.count(Notification.id))
            .join(User, User.id == Notification.user_id)
            .filter(User.is_active.is_(True))
            .filter(Notification.status == "sent")
            .filter(Notification.sent_at.is_not(None))
            .filter(Notification.sent_at >= start_today)
            .scalar()
            or 0
        )
        alerts_sent_7d = (
            db.query(func.count(Notification.id))
            .join(User, User.id == Notification.user_id)
            .filter(User.is_active.is_(True))
            .filter(Notification.status == "sent")
            .filter(Notification.sent_at.is_not(None))
            .filter(Notification.sent_at >= start_7d)
            .scalar()
            or 0
        )
        alerts_backlog = (
            db.query(func.count(Notification.id))
            .join(User, User.id == Notification.user_id)
            .filter(User.is_active.is_(True))
            .filter(Notification.status == "queued")
            .scalar()
            or 0
        )

        premium_users = (
            db.query(func.count(func.distinct(User.id)))
            .join(Subscription, Subscription.account_id == User.account_id)
            .join(Plan, Plan.id == Subscription.plan_id)
            .filter(User.is_active.is_(True))
            .filter(Subscription.status == "active")
            .filter(Plan.code == PLAN_CODE_PREMIUM)
            .filter((Subscription.current_period_end.is_(None)) | (Subscription.current_period_end > now))
            .scalar()
            or 0
        ) if users_total else 0
        free_users = max(0, int(users_total) - int(premium_users))

        sources_7d = (
            db.query(CarListing.source, func.count(Notification.id))
            .join(CarListing, CarListing.id == Notification.car_listing_id)
            .join(User, User.id == Notification.user_id)
            .filter(User.is_active.is_(True))
            .filter(Notification.status == "sent")
            .filter(Notification.sent_at.is_not(None))
            .filter(Notification.sent_at >= start_7d)
            .group_by(CarListing.source)
            .order_by(func.count(Notification.id).desc(), CarListing.source.asc())
            .limit(8)
            .all()
        )

    text = _render_metrics(
        {
            "users_total": users_total,
            "users_7d": users_7d,
            "users_with_active": users_with_active,
            "users_with_alert_7d": users_with_alert_7d,
            "wishlists_7d": wishlists_7d,
            "wishlists_active_total": wishlists_active_total,
            "alerts_sent_today": alerts_sent_today,
            "alerts_sent_7d": alerts_sent_7d,
            "alerts_backlog": alerts_backlog,
            "free_users": free_users,
            "premium_users": premium_users,
            "sources_7d": sources_7d,
        }
    )
    await update.message.reply_text(text)
