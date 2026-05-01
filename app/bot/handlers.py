import re
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.listing_sender import send_listing_message
from app.notifications.telegram_formatter import format_ad_message
from app.scoring.score_v2 import score_ad
from app.services.market_stats_service import batch_get_market_stats, cohort_key_for_listing
from app.bot.utils import normalize_args, parse_int, reply_text
from app.db.session import SessionLocal
from app.services.search_service import manual_search
from app.services.users_service import get_or_create_user_by_chat
from app.sources import list_sources
from app.services.wishlists_service import (
    add_wishlist, remove_wishlist,
    add_filter, list_filters, remove_filter,
)
from app.services.limits_service import get_daily_limit_for_user, count_sent_today
from app.models.user import User
from app.models.plan import Plan
from app.models.subscription import Subscription

from app.bot.admin import is_admin
from app.bot.open_ad import normalize_listing_url

from types import SimpleNamespace

class _AdView:
    """Adapter: expose listing fields + computed score fields to the vNext formatter."""

    def __init__(self, listing, *, score_v2=None, score_breakdown=None):
        self._listing = listing
        self.score_v2 = score_v2
        self.score_breakdown = score_breakdown

    def __getattr__(self, item):
        return getattr(self._listing, item)


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


def _resolve_target_chat_id(args: list[str], default_chat_id: int) -> tuple[int | None, str | None]:
    if len(args) >= 2:
        chat_id = parse_int(args[1])
        if chat_id is None:
            return None, "telegram_chat_id inválido (deve ser número)."
        return chat_id, None
    return default_chat_id, None


async def _ensure_admin(update: Update) -> bool:
    chat_id = update.effective_chat.id
    if is_admin(chat_id):
        return True
    await reply_text(update, "Sem permissão.")
    return False

async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, sources = _parse_query_and_sources(context.args)
    if not query:
        await reply_text(
            update,
            "Use: /buscar <termos>\nEx: /buscar civic 2019\nDica: /buscar audi a5 @mobiauto",
        )
        return

    with SessionLocal() as db:
        _user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        results = manual_search(db, query=query, limit=5, sources=sources, force_scrape=bool(sources))

        if not results:
            await reply_text(update, "Nada encontrado agora.")
            return

        # vNext scoring+formatting (treat manual query as a temporary wishlist)
        pseudo_wishlist = SimpleNamespace(query=query, filters=[])
        stats_map = {}
        try:
            stats_map = batch_get_market_stats(db, results)
        except Exception:
            stats_map = {}

        for item in results:
            ms = None
            try:
                k = cohort_key_for_listing(item)
                if k:
                    ms = stats_map.get(k)
            except Exception:
                ms = None

            sres = score_ad(item, pseudo_wishlist, ms)
            payload = format_ad_message(_AdView(item, score_v2=sres.total, score_breakdown=sres.to_dict()))

            keyboard_rows = [list(row) for row in (payload.inline_keyboard or [])]
            keyboard = None
            if keyboard_rows:
                built_rows = []
                for row in keyboard_rows:
                    built = []
                    for btn in row:
                        if btn.get("callback_data"):
                            built.append(InlineKeyboardButton(btn.get("text", "Botão"), callback_data=btn.get("callback_data")))
                        else:
                            built.append(InlineKeyboardButton(btn.get("text", "Abrir anúncio"), url=btn.get("url")))
                    built_rows.append(built)
                keyboard = InlineKeyboardMarkup(built_rows)

            await send_listing_message(
                update,
                text=payload.text,
                thumbnail_url=getattr(item, "thumbnail_url", None),
                referer_url=getattr(item, "url", None),
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )


async def cmd_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = normalize_args(context.args)
    sub = (args[0].lower() if args else "listar")

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)

        # /wishlist listar
        if sub in ("listar",):
            w = list_wishlists(db, user.id)
            if not w:
                await reply_text(
                    update,
                    "Você não tem wishlists.\n"
                    "Opções:\n"
                    "• /wishlist_add (fluxo oficial)\n"
                    "• /wishlist add <termos> (compatibilidade legado)"
                )
                return
            lines = [f"{i+1}. {x.query}" for i, x in enumerate(w)]
            await reply_text(update, "Wishlists:\n" + "\n".join(lines))
            return

        # /wishlist add <termos>
        if sub == "add":
            query = " ".join(args[1:]).strip()
            if not query:
                await reply_text(update, "Use: /wishlist add <termos>")
                return
            ok, msg = add_wishlist(db, user.id, query)
            await reply_text(update, msg)
            return

        # /wishlist rm <numero>
        if sub == "rm":
            if len(args) < 2 or parse_int(args[1]) is None:
                await reply_text(update, "Use: /wishlist rm <numero>")
                return
            ok, msg = remove_wishlist(db, user.id, int(args[1]))
            await reply_text(update, msg)
            return

        # /wishlist filter ...
        if sub == "filter":
            if len(args) < 2:
                await reply_text(
                    update,
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
                if len(args) < 3 or parse_int(args[2]) is None:
                    await reply_text(update, "Use: /wishlist filter list <n>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await reply_text(update, "Wishlist inválida. Use /wishlist listar.")
                    return
                fs = list_filters(db, wl.id)
                if not fs:
                    await reply_text(update, "Sem filtros. Use /wishlist filter add ...")
                    return
                lines = [f"{i+1}. {f.field} {f.operator} {f.value}" for i, f in enumerate(fs)]
                await reply_text(update, "Filtros:\n" + "\n".join(lines))
                return

            if action == "add":
                if len(args) < 6 or parse_int(args[2]) is None:
                    await reply_text(update, "Use: /wishlist filter add <n> <field> <op> <value>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await reply_text(update, "Wishlist inválida. Use /wishlist listar.")
                    return
                field, op, value = args[3], args[4], args[5]
                ok, msg = add_filter(db, wl.id, field, op, value)
                await reply_text(update, msg)
                return

            if action == "rm":
                if len(args) < 4 or parse_int(args[2]) is None or parse_int(args[3]) is None:
                    await reply_text(update, "Use: /wishlist filter rm <n> <filter_num>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await reply_text(update, "Wishlist inválida. Use /wishlist listar.")
                    return
                ok, msg = remove_filter(db, wl.id, int(args[3]))
                await reply_text(update, msg)
                return

            await reply_text(update, "Ação inválida. Use: add|list|rm")
            return

        await reply_text(update, "Use: /wishlist listar | /wishlist_add (oficial) | /wishlist add <termos> (legado) | /wishlist rm <numero>")


async def cmd_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        limit = get_daily_limit_for_user(db, user.id)

    await reply_text(
        update,
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
    await reply_text(update, text)


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        plans = (
            db.query(Plan)
            .filter(Plan.is_active == True)  # noqa
            .order_by(Plan.daily_alert_limit.asc())
            .all()
        )

    if not plans:
        await reply_text(update, "Sem planos disponíveis no momento.")
        return

    lines = ["🚀 Upgrade AutoHunter", ""]
    for p in plans:
        lines.append(f"- {p.code}: {p.daily_alert_limit} alertas/dia | até {p.max_wishlists} wishlists")
    lines += ["", "Para upgrade, fale com o admin do bot.", "Dica: use /plan para ver seu consumo hoje."]
    await reply_text(update, "\n".join(lines))


async def cmd_setplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_admin(update):
        return

    args = normalize_args(context.args)
    if not args:
        await reply_text(update, "Use: /setplan <free|pro|ultra> [telegram_chat_id]")
        return

    plan_code = args[0].lower()

    chat_id, error = _resolve_target_chat_id(args, int(update.effective_chat.id))
    if error:
        await reply_text(update, error)
        return

    with SessionLocal() as db:
        u = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not u:
            await reply_text(update, "Usuário não encontrado nesse chat_id.")
            return
        if not u.account_id:
            await reply_text(update, "Usuário sem account_id (verifique users_service).")
            return

        plan = db.query(Plan).filter(Plan.code == plan_code).first()
        if not plan:
            await reply_text(update, "Plano inválido. Use: free|pro|ultra")
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

    await reply_text(update, f"✅ Plano atualizado para {plan_code} (chat_id={chat_id}).")


async def cmd_setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_admin(update):
        return

    args = normalize_args(context.args)
    if not args:
        await reply_text(update, "Use: /setlimit <numero|none> [telegram_chat_id]")
        return

    raw = args[0].lower()

    chat_id, error = _resolve_target_chat_id(args, int(update.effective_chat.id))
    if error:
        await reply_text(update, error)
        return

    with SessionLocal() as db:
        u = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not u:
            await reply_text(update, "Usuário não encontrado nesse chat_id.")
            return
        if not u.account_id:
            await reply_text(update, "Usuário sem account_id (verifique users_service).")
            return

        active = (
            db.query(Subscription)
            .filter(Subscription.account_id == u.account_id)
            .filter(Subscription.status == "active")
            .order_by(Subscription.created_at.desc())
            .first()
        )
        if not active:
            await reply_text(update, "Usuário sem subscription ativa.")
            return

        if raw == "none":
            active.daily_alert_limit_override = None
            db.commit()
            await reply_text(update, f"✅ Override removido (chat_id={chat_id}).")
            return

        if parse_int(raw) is None:
            await reply_text(update, "Use um número (ex: 50) ou 'none'.")
            return

        active.daily_alert_limit_override = int(raw)
        db.commit()

    await reply_text(update, f"✅ Override diário setado para {raw} (chat_id={chat_id}).")
