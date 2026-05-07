import re
import asyncio
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.listing_sender import send_listing_message
from app.notifications.telegram_formatter import format_ad_message
from app.scoring.score_v2 import score_ad
from app.services.market_stats_service import batch_get_market_stats, cohort_key_for_listing
from app.bot.utils import normalize_args, parse_int, reply_text
from app.bot.renderers import render_user_wishlists
from app.db.session import SessionLocal
from app.services.search_service import manual_search
from app.services.users_service import get_or_create_user_by_chat
from app.sources import list_sources
from app.services.wishlists_service import (
    add_wishlist, remove_wishlist,
    add_filter, list_filters, remove_filter, get_wishlist_summaries, list_wishlists,
)
from app.services.limits_service import get_daily_limit_for_user, count_sent_today
from app.models.user import User
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.services.plan_capabilities import resolve_plan_capabilities
from app.core.settings import settings
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.models.wishlist import Wishlist

from app.bot.admin import is_admin
from app.bot.open_ad import normalize_listing_url

from types import SimpleNamespace
import logging

logger = logging.getLogger(__name__)


def _run_manual_search_sync(*, chat_id: int, username: str | None, query: str, sources: list[str] | None) -> list[dict]:
    with SessionLocal() as db:
        _user = get_or_create_user_by_chat(db, chat_id, username)
        results = manual_search(db, query=query, limit=5, sources=sources, force_scrape=bool(sources))
        if not results:
            return []
        pseudo_wishlist = SimpleNamespace(query=query, filters=[])
        stats_map = {}
        try:
            stats_map = batch_get_market_stats(db, results)
        except Exception:
            stats_map = {}
        payloads: list[dict] = []
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
            payloads.append(
                {
                    "text": payload.text,
                    "inline_keyboard": payload.inline_keyboard or [],
                }
            )
        return payloads

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

    chat_id = update.effective_chat.id
    user_name = update.effective_user.username
    await reply_text(update, "Busca recebida. Vou processar em segundo plano e te aviso quando encontrar resultados.")

    async def _run_background_search() -> None:
        try:
            payloads = await asyncio.to_thread(
                _run_manual_search_sync,
                chat_id=chat_id,
                username=user_name,
                query=query,
                sources=sources,
            )
            if not payloads:
                await context.bot.send_message(chat_id=chat_id, text="Nada encontrado agora.")
                return
            for payload in payloads:
                built_rows = []
                for row in payload.get("inline_keyboard") or []:
                    built = []
                    for btn in row:
                        if btn.get("callback_data"):
                            built.append(InlineKeyboardButton(btn.get("text", "Botão"), callback_data=btn.get("callback_data")))
                        else:
                            built.append(InlineKeyboardButton(btn.get("text", "Abrir anúncio"), url=btn.get("url")))
                    if built:
                        built_rows.append(built)
                reply_markup = InlineKeyboardMarkup(built_rows) if built_rows else None
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=payload["text"],
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
        except Exception:
            logger.exception("manual_search_background_failed", extra={"chat_id": chat_id, "query": query})
            await context.bot.send_message(
                chat_id=chat_id,
                text="Não consegui concluir essa busca agora. Tente novamente em alguns minutos.",
            )

    asyncio.create_task(_run_background_search())
    return


async def cmd_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = normalize_args(context.args)
    sub = (args[0].lower() if args else "listar")

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)

        # /wishlist listar
        if sub in ("listar",):
            summaries = get_wishlist_summaries(db, user.id)
            await reply_text(update, render_user_wishlists(summaries))
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

        sub, plan = _get_active_subscription_and_plan(db, user)
        total_tracked = (
            db.query(WishlistTrackedListing)
            .join(Wishlist, Wishlist.id == WishlistTrackedListing.wishlist_id)
            .filter(Wishlist.user_id == user.id)
            .count()
        )
        plan_code = plan.code if plan else "free"
        caps = resolve_plan_capabilities(db, plan_code)

    if caps.premium:
        valid_until = getattr(sub, "current_period_end", None) or getattr(sub, "ends_at", None)
        valid_txt = valid_until.astimezone(timezone.utc).strftime("%d/%m/%Y") if valid_until else "-"
        text = (
            "Plano atual: Premium\n- Plano: premium\n\n"
            f"Válido até: {valid_txt}\n\n"
            "Uso:\n"
            f"Wishlists: até {caps.max_active_wishlists}\n"
            f"Rastreados: {total_tracked}/{caps.max_tracked_total}\n"
            f"Notificações: até {caps.daily_notifications_per_wishlist} por dia por wishlist\n\n"
            "Renovação: manual"
        )
    else:
        text = (
            "Plano atual: Free\n- Plano: free\n\n"
            "Uso:\n"
            f"Wishlists: {0}/{caps.max_active_wishlists}\n"
            f"Rastreados: {total_tracked}/{caps.max_tracked_total}\n"
            f"Notificações: até {caps.daily_notifications_per_wishlist} por dia por wishlist\n\n"
            "Para liberar mais buscas, mais rastreados e alertas automáticos:\n"
            "Use /upgrade"
        )
    await reply_text(update, text)


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚀 AutoHunter Premium\n\n"
        "Escolha seu plano:\n\n"
        "Mensal\n"
        "De R$ 9,99 por R$ 5,99/mês no lançamento.\n\n"
        "Anual\n"
        "De R$ 89,99 por R$ 59,99/ano.\n"
        "Equivale a R$ 4,99/mês.\n\n"
        "Benefícios:\n"
        "- até 10 wishlists\n"
        "- até 5 anúncios rastreados no total\n"
        "- alertas automáticos de preço/status\n"
        "- até 15 notificações por dia por wishlist\n"
        "- prioridade em novas funcionalidades\n\n"
        "Após pagar, envie o comprovante aqui no Telegram.\n"
        "A ativação é feita manualmente."
    )
    kb=[]
    if settings.mercado_pago_monthly_payment_link:
        kb.append([InlineKeyboardButton("💳 Assinar Mensal", url=settings.mercado_pago_monthly_payment_link)])
    if settings.mercado_pago_annual_payment_link:
        kb.append([InlineKeyboardButton("💳 Assinar Anual", url=settings.mercado_pago_annual_payment_link)])
    if not kb:
        text += "\n\nOs links de pagamento ainda não estão configurados. Fale com o admin para ativação manual."
    await reply_text(update, text, reply_markup=InlineKeyboardMarkup(kb) if kb else None)


async def cmd_setplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_admin(update):
        return

    args = normalize_args(context.args)
    if not args:
        await reply_text(update, "Use: /setplan <free|premium> [telegram_chat_id]")
        return

    requested_plan_code = args[0].lower()
    if requested_plan_code not in {"free", "premium"}:
        await reply_text(update, "Plano inválido. Use: free|premium")
        return

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

        resolved_code = requested_plan_code
        plan = db.query(Plan).filter(Plan.code == resolved_code).first()
        if not plan:
            await reply_text(update, f"Plano {resolved_code} não encontrado no banco. Rode migrations/seed de planos.")
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

    await reply_text(update, f"✅ Plano atualizado para {resolved_code} (chat_id={chat_id}).")


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
