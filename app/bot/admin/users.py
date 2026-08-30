from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import func, or_, cast, Text, case
from telegram import Update

from app.bot.text_sanitize import sanitize_for_telegram
from app.db.session import SessionLocal
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.auction_source_config_service import list_user_eligible_auction_sources
from app.services.plan_capabilities import normalize_plan_code
from app.sources.auctions.registry import get_auction_source_definition


def _render_user_eligible_auction_sources_hint(db) -> str:
    keys = list_user_eligible_auction_sources(db)
    aliases = []
    for key in sorted(keys):
        definition = get_auction_source_definition(key)
        if definition:
            aliases.append(definition.aliases[0])
    return f"Sources elegíveis: {'|'.join(aliases)}" if aliases else "Sources elegíveis: -"


def _admin_user_by_chat(db, chat_id: int | None) -> User | None:
    if chat_id is None:
        return None
    return db.query(User).filter(User.telegram_chat_id == int(chat_id)).first()


async def _admin_users(update: Update, raw_args: List[str]):
    # Lista usuários (paginado) para operação remota via Telegram.
    #
    # Use:
    #   /admin users
    #   /admin users 2
    #   /admin users civic
    #   /admin users 2 civic

    page = 1
    term: Optional[str] = None

    if raw_args:
        if raw_args[0].isdigit():
            page = max(1, int(raw_args[0]))
            term = " ".join(raw_args[1:]).strip() or None
        else:
            term = " ".join(raw_args).strip() or None

    if term:
        term = term.strip()
        if term.startswith("@"):  # permite /admin users @marcelo
            term = term[1:]
        if not term:
            term = None

    per_page = 10
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        q = db.query(User)
        if term:
            like = f"%{term}%"
            q = q.filter(
                or_(
                    User.username.ilike(like),
                    cast(User.telegram_chat_id, Text).ilike(like),
                    cast(User.id, Text).ilike(like),
                )
            )

        total = q.count()
        pages = max(1, (total + per_page - 1) // per_page)
        if page > pages:
            page = pages

        users = (
            q.order_by(User.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # wishlist counts (total/active)
        uids = [u.id for u in users]
        wl_counts: Dict[Any, tuple[int, int]] = {}
        if uids:
            wl_rows = (
                db.query(
                    Wishlist.user_id,
                    func.count(Wishlist.id),
                    func.sum(case((Wishlist.is_active == True, 1), else_=0)),
                )
                .filter(Wishlist.user_id.in_(uids))
                .group_by(Wishlist.user_id)
                .all()
            )
            for uid, wl_total, wl_active in wl_rows:
                wl_counts[uid] = (int(wl_total or 0), int(wl_active or 0))

        # subscription snapshot per account (latest by starts_at)
        acc_ids = [u.account_id for u in users if u.account_id]
        sub_map: Dict[Any, Dict[str, Any]] = {}
        if acc_ids:
            sub_rows = (
                db.query(
                    Subscription.account_id,
                    Subscription.status,
                    Subscription.daily_alert_limit_override,
                    Subscription.starts_at,
                    Subscription.ends_at,
                    Plan.code,
                )
                .join(Plan, Subscription.plan_id == Plan.id)
                .filter(Subscription.account_id.in_(acc_ids))
                .order_by(Subscription.account_id.asc(), Subscription.starts_at.desc())
                .all()
            )
            for aid, status, override, starts_at, ends_at, plan_code in sub_rows:
                if aid not in sub_map:
                    sub_map[aid] = {
                        "status": status,
                        "override": override,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "plan_code": plan_code,
                    }

    out: List[str] = []
    out.append("👥 Admin — Users")

    header = f"total={total} | page={page}/{pages} | per_page={per_page}"
    if term:
        header += f" | filter={term}"
    out.append(header)
    out.append("")

    if not users:
        out.append("Nenhum usuário encontrado.")
    else:
        start_index = (page - 1) * per_page + 1
        for i, u in enumerate(users, start=start_index):
            uname = f"@{u.username}" if u.username else "-"
            active = "✅" if u.is_active else "🚫"

            wl_total, wl_active = wl_counts.get(u.id, (0, 0))

            sub = sub_map.get(u.account_id) if u.account_id else None
            raw_plan = (sub.get("plan_code") if sub else None) or (u.plan or "free")
            plan = normalize_plan_code(raw_plan)

            override = None
            if sub and sub.get("override") is not None:
                override = sub.get("override")
            elif u.daily_limit_override is not None:
                override = u.daily_limit_override

            limit_txt = str(override) if override is not None else "-"
            acc_txt = "acc✅" if u.account_id else "acc—"
            sub_status = (sub.get("status") if sub else None) or "-"

            out.append(
                f"{i}. {active} {uname} | chat={u.telegram_chat_id} | {acc_txt} | wl={wl_active}/{wl_total} | plan={plan} ({sub_status}) | limit={limit_txt}"
            )

    out.append("")
    out.append("Dica: /setplan <free|premium> <chat_id>  |  /setlimit <n|none> <chat_id>")

    msg = sanitize_for_telegram("\n".join(out))
    if len(msg) > 3800:
        msg = msg[:3797] + "..."
    await update.effective_message.reply_text(msg)
