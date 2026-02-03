from datetime import datetime, timezone

import re
from io import BytesIO
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.formatting import format_price
from app.bot.media import download_image_bytes
from app.db.session import SessionLocal
from app.services.search_service import manual_search
from app.services.users_service import get_or_create_user_by_chat
from app.sources import list_sources
from app.services.wishlists_service import (
    list_wishlists, add_wishlist, remove_wishlist,
    add_filter, list_filters, remove_filter,
)
from app.services.limits_service import get_daily_limit_for_user, count_sent_today
from app.models.user import User
from app.models.plan import Plan
from app.models.subscription import Subscription

from app.bot.admin import is_admin
from app.bot.open_ad import normalize_listing_url


def _get_active_subscription_and_plan(db, user: User):
    if not user.account_id:
        return None, None

    row = (
        db.query(Subscription, Plan)
        .join(Plan, Plan.id == Subscription.plan_id)
        .filter(Subscription.account_id == user.account_id)
        .filter(Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if not row:
        return None, None
    sub, plan = row
    return sub, plan


def _get_known_sources() -> set[str]:
    try:
        return {p.name.lower() for p in list_sources()}
    except Exception:
        return set()


def _parse_query_and_sources(args: list[str] | None) -> tuple[str, list[str] | None]:
    """Parse /buscar args and extract optional source selector.

    Supported:
      - @mobiauto
      - source:mobiauto  / source=mobiauto
      - src:mobiauto     / src=mobiauto
      - legacy: last token == source name (e.g. "a5 mobiauto")
    """
    args = args or []
    known = _get_known_sources()

    sources: list[str] = []
    cleaned: list[str] = []

    for tok in args:
        t = (tok or "").strip()
        if not t:
            continue

        low = t.lower()
        name: str | None = None

        if low.startswith("@"):
            name = low[1:]
        elif low.startswith("source:") or low.startswith("src:"):
            name = low.split(":", 1)[1]
        elif low.startswith("source=") or low.startswith("src="):
            name = low.split("=", 1)[1]

        if name:
            # allow comma-separated sources in one token
            parts = [p.strip() for p in re.split(r"[,\s]+", name) if p.strip()]
            ok = [p for p in parts if p in known]
            if ok:
                sources.extend(ok)
                continue

        cleaned.append(t)

    # legacy: if last token is a known source, treat as selector
    if not sources and cleaned:
        last = cleaned[-1].lower()
        if last in known:
            sources = [last]
            cleaned = cleaned[:-1]

    # dedupe while preserving order
    if sources:
        seen = set()
        uniq: list[str] = []
        for s in sources:
            if s not in seen:
                uniq.append(s)
                seen.add(s)
        sources = uniq

    query = " ".join(cleaned).strip()
    return query, (sources or None)



async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, sources = _parse_query_and_sources(context.args)
    if not query:
        await update.message.reply_text("Use: /buscar <termos>\nEx: /buscar civic 2019\nDica: /buscar audi a5 @mobiauto")
        return

    with SessionLocal() as db:
        _user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        results = manual_search(db, query=query, limit=5, sources=sources)

    if not results:
        await update.message.reply_text("Nada encontrado agora.")
        return

    for item in results:
        open_url = normalize_listing_url(
            getattr(item, "url", None) or "",
            source=getattr(item, "source", None) or None,
            external_id=getattr(item, "external_id", None) or None,
        )

        keyboard = None
        if open_url:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Abrir anúncio", url=open_url)]])

        # Texto curto: o link vai no botão.
        text = (
            f"{item.title or 'Anúncio'}\n"
            f"Fonte: {item.source}\n"
            f"Preço: {format_price(item.price)}"
        )

        if item.thumbnail_url:
            img = download_image_bytes(item.thumbnail_url, referer=item.url)
            if img:
                img_bytes, _ctype = img
                bio = BytesIO(img_bytes)
                bio.name = "thumb.jpg"
                await update.message.reply_photo(photo=bio, caption=text, reply_markup=keyboard)
            else:
                await update.message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)
        else:
            await update.message.reply_text(text, reply_markup=keyboard, disable_web_page_preview=True)

async def cmd_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = [a.strip() for a in (context.args or []) if a.strip()]
    sub = (args[0].lower() if args else "listar")

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)

        # /wishlist listar
        if sub in ("listar",):
            w = list_wishlists(db, user.id)
            if not w:
                await update.message.reply_text(
                    "Você não tem wishlists.\n"
                    "Opções:\n"
                    "• /wishlist_add (assistente)\n"
                    "• /wishlist add <termos> (modo antigo)"
                )
                return
            lines = [f"{i+1}. {x.query}" for i, x in enumerate(w)]
            await update.message.reply_text("Wishlists:\n" + "\n".join(lines))
            return

        # /wishlist add <termos>
        if sub == "add":
            query = " ".join(args[1:]).strip()
            if not query:
                await update.message.reply_text("Use: /wishlist add <termos>")
                return
            ok, msg = add_wishlist(db, user.id, query)
            await update.message.reply_text(msg)
            return

        # /wishlist rm <numero>
        if sub == "rm":
            if len(args) < 2 or not args[1].isdigit():
                await update.message.reply_text("Use: /wishlist rm <numero>")
                return
            ok, msg = remove_wishlist(db, user.id, int(args[1]))
            await update.message.reply_text(msg)
            return

        # /wishlist filter ...
        if sub == "filter":
            if len(args) < 2:
                await update.message.reply_text(
                    "Use:\n"
                    "/wishlist filter add <n> price lte 90000\n"
                    "/wishlist filter add <n> source eq mercadolivre\n"
                    "/wishlist filter list <n>\n"
                    "/wishlist filter rm <n> <filter_num>"
                )
                return

            action = args[1].lower()
            w = list_wishlists(db, user.id)

            def get_wishlist_by_index(n: int):
                if n < 1 or n > len(w):
                    return None
                return w[n-1]

            if action == "list":
                if len(args) < 3 or not args[2].isdigit():
                    await update.message.reply_text("Use: /wishlist filter list <n>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
                    return
                fs = list_filters(db, wl.id)
                if not fs:
                    await update.message.reply_text("Sem filtros. Use /wishlist filter add ...")
                    return
                lines = [f"{i+1}. {f.field} {f.operator} {f.value}" for i, f in enumerate(fs)]
                await update.message.reply_text("Filtros:\n" + "\n".join(lines))
                return

            if action == "add":
                if len(args) < 6 or not args[2].isdigit():
                    await update.message.reply_text("Use: /wishlist filter add <n> <field> <op> <value>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
                    return
                field, op, value = args[3], args[4], args[5]
                ok, msg = add_filter(db, wl.id, field, op, value)
                await update.message.reply_text(msg)
                return

            if action == "rm":
                if len(args) < 4 or (not args[2].isdigit()) or (not args[3].isdigit()):
                    await update.message.reply_text("Use: /wishlist filter rm <n> <filter_num>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
                    return
                ok, msg = remove_filter(db, wl.id, int(args[3]))
                await update.message.reply_text(msg)
                return

            await update.message.reply_text("Ação inválida. Use: add|list|rm")
            return

        await update.message.reply_text("Use: /wishlist listar | /wishlist add <termos> | /wishlist rm <numero>")


async def cmd_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        limit = get_daily_limit_for_user(db, user.id)

    await update.message.reply_text(
        "Alertas do AutoHunter:\n"
        "- Monitoramento: a cada 30 min (Mercado Livre e OLX)\n"
        f"- Limite: {limit} alertas/dia\n"
        "Use /plan para ver consumo e /wishlist para gerenciar."
    )


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)

        limit = get_daily_limit_for_user(db, user.id)
        sent_today = count_sent_today(db, user.id)
        remaining = max(0, limit - sent_today)

        sub, plan = _get_active_subscription_and_plan(db, user)

    plan_label = "free"
    if plan:
        plan_label = f"{plan.code} ({plan.name})"

    override = None
    if sub and sub.daily_alert_limit_override is not None:
        override = sub.daily_alert_limit_override

    text = (
        "📦 Seu plano no AutoHunter\n"
        f"- Plano: {plan_label}\n"
        f"- Limite diário: {limit}/dia\n"
        f"- Enviados hoje: {sent_today}\n"
        f"- Restantes hoje: {remaining}\n"
    )
    if override is not None:
        text += f"- Override: {override}\n"

    text += "\nUse /upgrade para ver opções de aumento."
    await update.message.reply_text(text)


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        plans = (
            db.query(Plan)
            .filter(Plan.is_active == True)  # noqa
            .order_by(Plan.daily_alert_limit.asc())
            .all()
        )

    if not plans:
        await update.message.reply_text("Sem planos disponíveis no momento.")
        return

    lines = ["🚀 Upgrade AutoHunter", ""]
    for p in plans:
        lines.append(f"- {p.code}: {p.daily_alert_limit} alertas/dia | até {p.max_wishlists} wishlists")
    lines += ["", "Para upgrade, fale com o admin do bot.", "Dica: use /plan para ver seu consumo hoje."]
    await update.message.reply_text("\n".join(lines))


async def cmd_setplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    args = [a.strip() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /setplan <free|pro|ultra> [telegram_chat_id]")
        return

    plan_code = args[0].lower()

    if len(args) >= 2:
        if not args[1].isdigit():
            await update.message.reply_text("telegram_chat_id inválido (deve ser número).")
            return
        chat_id = int(args[1])
    else:
        chat_id = int(update.effective_chat.id)

    with SessionLocal() as db:
        u = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not u:
            await update.message.reply_text("Usuário não encontrado nesse chat_id.")
            return
        if not u.account_id:
            await update.message.reply_text("Usuário sem account_id (verifique users_service).")
            return

        plan = db.query(Plan).filter(Plan.code == plan_code).first()
        if not plan:
            await update.message.reply_text("Plano inválido. Use: free|pro|ultra")
            return

        # cancela subscription ativa (se existir)
        active = (
            db.query(Subscription)
            .filter(Subscription.account_id == u.account_id)
            .filter(Subscription.status == "active")
            .order_by(Subscription.created_at.desc())
            .first()
        )
        if active:
            active.status = "canceled"
            active.ends_at = datetime.now(timezone.utc)

        # cria nova subscription ativa
        db.add(
            Subscription(
                account_id=u.account_id,
                plan_id=plan.id,
                status="active",
                source="manual",
                starts_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

    await update.message.reply_text(f"✅ Plano atualizado para {plan_code} (chat_id={chat_id}).")


async def cmd_setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    args = [a.strip() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /setlimit <numero|none> [telegram_chat_id]")
        return

    raw = args[0].lower()

    if len(args) >= 2:
        if not args[1].isdigit():
            await update.message.reply_text("telegram_chat_id inválido (deve ser número).")
            return
        chat_id = int(args[1])
    else:
        chat_id = int(update.effective_chat.id)

    with SessionLocal() as db:
        u = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not u:
            await update.message.reply_text("Usuário não encontrado nesse chat_id.")
            return
        if not u.account_id:
            await update.message.reply_text("Usuário sem account_id (verifique users_service).")
            return

        active = (
            db.query(Subscription)
            .filter(Subscription.account_id == u.account_id)
            .filter(Subscription.status == "active")
            .order_by(Subscription.created_at.desc())
            .first()
        )
        if not active:
            await update.message.reply_text("Usuário sem subscription ativa.")
            return

        if raw == "none":
            active.daily_alert_limit_override = None
            db.commit()
            await update.message.reply_text(f"✅ Override removido (chat_id={chat_id}).")
            return

        if not raw.isdigit():
            await update.message.reply_text("Use um número (ex: 50) ou 'none'.")
            return

        active.daily_alert_limit_override = int(raw)
        db.commit()

    await update.message.reply_text(f"✅ Override diário setado para {raw} (chat_id={chat_id}).")
