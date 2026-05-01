from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from app.bot.utils import reply_text
from app.db.session import SessionLocal
from app.bot.renderers import render_all_tracked_listings, render_help_text, render_user_wishlists
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists, get_user_plan_snapshot
from app.services.wishlists_service import add_wishlist
from app.services.wishlist_tracking_service import list_tracked_listings

MENU_CREATE_WISHLIST_QUERY = 1


def _wishlist_help_text() -> str:
    return (
        "🧰 Wishlist — ajuda rápida\n\n"
        "Criar (assistente):\n"
        "• /wishlist_add\n"
        "  Depois digite, por exemplo:\n"
        "  - audi a6 entre 2014 e 2020\n"
        "  - audi a6 a partir de 2014\n"
        "  - audi a6 até 2020\n"
        "  - audi a6 entre 200k e 300k\n"
        "  - audi a6 até R$ 120.000\n\n"
        "Fluxo oficial recomendado:\n"
        "• /wishlist_add (assistente)\n\n"
        "Compatibilidade (modo antigo):\n"
        "• /wishlist add audi a6\n\n"
        "Diretivas embutidas no texto (criam filtros automáticos):\n"
        "• Ano: entre 2014 e 2020 | 2014-2020 | a partir de 2014 | até 2020 | ano>=2014 | ano<=2020\n"
        "• Preço (BRL): entre 200k e 300k | 200k-300k | a partir de 80k | até 120k | preço>=80k | valor<=120k\n"
        "  (k=mil, m=milhão; também aceita R$ 80.000)\n\n"
        "Equivalente em filtros manuais:\n"
        "• /wishlist_filter_add <n> year gte 2014\n"
        "• /wishlist_filter_add <n> year lte 2020\n"
        "• /wishlist_filter_add <n> price gte 200000\n"
        "• /wishlist_filter_add <n> price lte 300000\n\n"
        "Outros filtros úteis:\n"
        "• /wishlist_filter_add <n> price lte 90000\n"
        "• /wishlist_filter_add <n> km <= 80000\n"
        "• /wishlist_filter_add <n> km entre 30000 90000\n"
        "• /wishlist_filter_add <n> source eq icarros\n"
        "• /wishlist_filter_add <n> color eq prata\n"
        "• /wishlist_filter_add <n> city eq sao paulo\n"
        "• /wishlist_filter_add <n> state eq SP\n"
        "• /wishlist_filter_add <n> vendedor = particular\n"
        "• /wishlist_filter_add <n> vendedor apenas loja\n"
        "• /wishlist_filter_add <n> vendedor excluir revenda\n\n"
        "• /wishlist_filter_add <n> carroceria = suv\n"
        "• /wishlist_filter_add <n> carroceria excluir pickup\n\n"
        "• /wishlist_filter_add <n> portas = 4\n"
        "• /wishlist_filter_add <n> portas >= 4\n"
        "• /wishlist_filter_add <n> portas entre 2 4\n\n"
        "Ver/remover filtros:\n"
        "• /wishlist_filter_list <n>\n"
        "• /wishlist_filter_remove <n> <k>\n\n"
        "Rastrear até 3 anúncios por wishlist:\n"
        "• /wishlist_track_add <n> <url|external_id>\n"
        "• /wishlist_track_list <n>\n"
        "• /wishlist_track_remove <n> <slot>\n\n"
        "Quando receber um anúncio de uma wishlist, clique em ⭐ Rastrear para acompanhar preço e status.\n"
        "Veja seus rastreados com:\n"
        "/wishlist_track_list\n\n"
        "Dica: /wishlist mostra o número <n>.\n"
        "Obs: filtros de preço só dão match quando a fonte extrai preço (se vier None, não entra em range)."
    )




async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        w = list_wishlists(db, user.id)

    await reply_text(
        update,
        "👋 Bem-vindo ao AutoHunter!\n\n"
        f"Você tem {len(w)} wishlist(s) ativa(s).\n"
        "Use /wishlist para listar, /wishlist_add para criar e /wishlist_help para ajuda."
    )

async def cmd_wishlist_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(update, _wishlist_help_text())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(update, render_help_text())


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(
        update,
        "🚗 AutoHunter\n\n"
        "O que você quer fazer?",
        reply_markup=_menu_keyboard(),
    )


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)

    data = (q.data or "").strip()
    if data == "MENU:SEARCH":
        await _safe_edit_or_send(update, "Para buscar agora, use:\n/buscar civic si")
        return
    if data == "MENU:CREATE_WISHLIST":
        await _safe_edit_or_send(
            update,
            "Qual carro você quer monitorar?\n"
            "Exemplos:\n"
            "- civic si\n"
            "- miata\n"
            "- corolla 2018\n\n"
            "Envie o texto ou use /cancelar.",
        )
        return MENU_CREATE_WISHLIST_QUERY
    if data == "MENU:WISHLISTS":
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            w = list_wishlists(db, user.id)
        await _safe_edit_or_send(update, render_user_wishlists(w))
        return
    if data == "MENU:TRACKED":
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
            tracked_messages = []
            for i, _wl in enumerate(wishlists, start=1):
                _ok, msg = list_tracked_listings(db, user_id=user.id, wishlist_index=i)
                tracked_messages.append(msg)
        await _safe_edit_or_send(update, render_all_tracked_listings(wishlists, tracked_messages)[:3900])
        return
    if data == "MENU:FILTERS":
        await _safe_edit_or_send(
            update,
            "Para ver filtros de uma wishlist:\n"
            "/wishlist_filter_list <n>\n\n"
            "Para adicionar filtro:\n"
            "/wishlist_filter_add <n> <campo> <operador> <valor>\n\n"
            "Dica: use /wishlist para ver o número <n> da wishlist.",
        )
        return
    if data == "MENU:HELP":
        await _safe_edit_or_send(update, render_help_text())
        return

    await _safe_edit_or_send(update, "Opção inválida. Use /menu novamente.")


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(update, "🤖 AutoHunter (bot) — appv4")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        w = list_wishlists(db, user.id)
        snap = get_user_plan_snapshot(db, user.id)

    max_w = snap.get("max_wishlists")
    dal = snap.get("daily_alert_limit")
    plan_code = snap.get("plan_code") or "free"

    dal_txt = str(dal) if dal is not None else "—"

    await reply_text(
        update,
        "📊 Status\n\n"
        f"Plano: {plan_code}\n"
        f"Wishlists: {len(w)}/{max_w}\n"
        f"Alertas/dia: {dal_txt}\n"
        "Monitoramento: fontes via scheduler\n\n"
        "Use /wishlist para ver suas buscas monitoradas."
    )
def _menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Criar wishlist", callback_data="MENU:CREATE_WISHLIST")],
        [InlineKeyboardButton("🎯 Minhas wishlists", callback_data="MENU:WISHLISTS")],
        [InlineKeyboardButton("📌 Rastreados", callback_data="MENU:TRACKED")],
        [InlineKeyboardButton("🔎 Buscar anúncio", callback_data="MENU:SEARCH")],
        [InlineKeyboardButton("⚙️ Filtros", callback_data="MENU:FILTERS")],
        [InlineKeyboardButton("❓ Ajuda", callback_data="MENU:HELP")],
    ])


async def _safe_answer_callback(q) -> None:
    try:
        await q.answer()
    except BadRequest as exc:
        msg = str(exc).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            return
        raise


async def _safe_edit_or_send(update: Update, text: str) -> None:
    q = update.callback_query
    try:
        await q.edit_message_text(text)
    except Exception:
        await q.message.reply_text(text)


async def menu_create_wishlist_on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if not query:
        await reply_text(update, "Texto inválido. Envie o carro/busca ou use /cancelar.")
        return MENU_CREATE_WISHLIST_QUERY

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        _ok, _msg = add_wishlist(db, user.id, query)

    await reply_text(
        update,
        f"✅ Wishlist criada: {query}\n\n"
        "Vou monitorar anúncios compatíveis.\n"
        "Você pode adicionar filtros depois em:\n"
        "⚙️ Filtros no /menu\n"
        "ou\n"
        "/wishlist_filter_add <n> <campo> <operador> <valor>\n\n"
        "Veja suas wishlists: /wishlist",
    )
    return ConversationHandler.END


async def menu_create_wishlist_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(update, "Criação de wishlist cancelada.")
    return ConversationHandler.END


def menu_create_wishlist_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_menu, pattern=r"^MENU:CREATE_WISHLIST$")],
        states={
            MENU_CREATE_WISHLIST_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_create_wishlist_on_text),
                MessageHandler(filters.COMMAND, menu_create_wishlist_cancel),
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", menu_create_wishlist_cancel),
            CommandHandler("cancel", menu_create_wishlist_cancel),
        ],
        name="menu_create_wishlist",
        persistent=False,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
