from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from app.bot.utils import reply_text
from app.db.session import SessionLocal
from app.bot.renderers import render_all_tracked_listings, render_help_text, render_start_text, render_user_wishlists, render_wishlist_filters
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists, get_user_plan_snapshot, add_wishlist, add_filter, list_filters, remove_filter, get_wishlist_summaries
from app.services.wishlist_tracking_service import list_tracked_listings

MENU_CREATE_WISHLIST_QUERY = 1
MENU_CREATE_WISHLIST_CONFIRM = 2
MENU_FILTER_SELECT_VALUE = 3

MENU_FILTER_USER_DATA_KEYS = ("menu_filter_wishlist_index", "menu_filter_wishlist_id", "menu_filter_type")
MENU_CREATE_WISHLIST_QUERY_KEY = "menu_create_wishlist_query"
MENU_CREATE_WISHLIST_CREATED_KEY = "menu_create_wishlist_created"

FILTER_TYPE_TO_SPEC = {
    "price_max": ("price", "lte", "Qual preço máximo?\nExemplo: 90000 ou 90.000"),
    "year_min": ("year", "gte", "Qual ano mínimo?\nExemplo: 2015"),
    "km_max": ("mileage_km", "lte", "Qual KM máximo?\nExemplo: 80000 ou 80.000"),
    "city": ("city", "eq", "Qual cidade?\nExemplo: São Paulo"),
    "state": ("state", "eq", "Qual estado/UF?\nExemplo: SP"),
}


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

    await reply_text(update, render_start_text(len(w)))

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
            summaries = get_wishlist_summaries(db, user.id)
        await _safe_edit_or_send(update, render_user_wishlists(summaries))
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
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if not wishlists:
            await _safe_edit_or_send(update, "Você ainda não tem wishlists.\nCrie uma pelo /menu → ➕ Criar wishlist.")
            return
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{i} — {wl.query}", callback_data=f"FILTER:WL:{i}")] for i, wl in enumerate(wishlists, start=1)]
            + [[InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")]]
        )
        await _safe_edit_or_send(update, "Escolha a wishlist para adicionar filtro:", reply_markup=kb)
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


async def _safe_edit_or_send(update: Update, text: str, reply_markup=None) -> None:
    q = update.callback_query
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        await q.message.reply_text(text, reply_markup=reply_markup)


def _clear_menu_filter_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in MENU_FILTER_USER_DATA_KEYS:
        context.user_data.pop(key, None)


def _clear_menu_create_wishlist_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(MENU_CREATE_WISHLIST_QUERY_KEY, None)
    context.user_data.pop(MENU_CREATE_WISHLIST_CREATED_KEY, None)


async def _show_menu_filter_actions(update: Update, wishlist_index: int, wishlist_query: str, prefix_text: str | None = None):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Adicionar filtro", callback_data="FILTER:ACTION:add")],
        [InlineKeyboardButton("📋 Ver filtros", callback_data="FILTER:ACTION:list")],
        [InlineKeyboardButton("✅ Concluir", callback_data="FILTER:DONE")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")],
    ])
    text = f"Filtros da wishlist {wishlist_index} — {wishlist_query}"
    if prefix_text:
        text = f"{prefix_text}\n\n{text}"
    await _safe_edit_or_send(update, text, reply_markup=kb)


async def cb_menu_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)
    data = (q.data or "").strip()

    if data == "FILTER:CANCEL":
        _clear_menu_filter_context(context)
        await _safe_edit_or_send(update, "Configuração de filtro cancelada.")
        return ConversationHandler.END
    if data == "FILTER:DONE":
        _clear_menu_filter_context(context)
        await _safe_edit_or_send(update, "Tudo certo. Use /menu para acompanhar suas buscas.")
        return ConversationHandler.END

    if data.startswith("FILTER:WL:"):
        try:
            wishlist_index = int(data.split(":")[-1])
        except ValueError:
            await _safe_edit_or_send(update, "Wishlist inválida. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if wishlist_index < 1 or wishlist_index > len(wishlists):
            await _safe_edit_or_send(update, "Wishlist inválida. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        wl = wishlists[wishlist_index - 1]
        context.user_data["menu_filter_wishlist_index"] = wishlist_index
        context.user_data["menu_filter_wishlist_id"] = wl.id
        await _show_menu_filter_actions(update, wishlist_index, wl.query)
        return MENU_FILTER_SELECT_VALUE

    if data == "FILTER:ACTION:add":
        if not context.user_data.get("menu_filter_wishlist_id"):
            await _safe_edit_or_send(update, "Sessão expirada. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Preço máximo", callback_data="FILTER:TYPE:price_max")],
            [InlineKeyboardButton("📅 Ano mínimo", callback_data="FILTER:TYPE:year_min")],
            [InlineKeyboardButton("🛣️ KM máximo", callback_data="FILTER:TYPE:km_max")],
            [InlineKeyboardButton("📍 Cidade", callback_data="FILTER:TYPE:city")],
            [InlineKeyboardButton("🗺️ Estado", callback_data="FILTER:TYPE:state")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")],
        ])
        await _safe_edit_or_send(update, "Escolha o tipo de filtro:", reply_markup=kb)
        return MENU_FILTER_SELECT_VALUE

    if data == "FILTER:ACTION:list":
        return await _show_menu_filter_list(update, context)

    if data.startswith("FILTER:RM:"):
        return await _menu_filter_remove_from_callback(update, context, data)

    if data == "FILTER:BACK":
        if not context.user_data.get("menu_filter_wishlist_id"):
            await _safe_edit_or_send(update, "Sessão expirada. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        wishlist_index = context.user_data.get("menu_filter_wishlist_index")
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if wishlist_index < 1 or wishlist_index > len(wishlists):
            await _safe_edit_or_send(update, "Wishlist não encontrada para sua conta.")
            return ConversationHandler.END
        wl = wishlists[wishlist_index - 1]
        await _show_menu_filter_actions(update, wishlist_index, wl.query)
        return MENU_FILTER_SELECT_VALUE

    if data.startswith("FILTER:TYPE:"):
        filter_type = data.split(":")[-1]
        spec = FILTER_TYPE_TO_SPEC.get(filter_type)
        if not spec:
            await _safe_edit_or_send(update, "Tipo de filtro inválido. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        context.user_data["menu_filter_type"] = filter_type
        await _safe_edit_or_send(update, spec[2])
        return MENU_FILTER_SELECT_VALUE

    await _safe_edit_or_send(update, "Ação inválida. Use /menu → ⚙️ Filtros novamente.")
    return ConversationHandler.END


async def menu_filter_on_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = (update.message.text or "").strip()
    if not value:
        await reply_text(update, "Valor inválido. Envie novamente ou /cancelar.")
        return MENU_FILTER_SELECT_VALUE

    wishlist_id = context.user_data.get("menu_filter_wishlist_id")
    wishlist_index = context.user_data.get("menu_filter_wishlist_index")
    spec = FILTER_TYPE_TO_SPEC.get(context.user_data.get("menu_filter_type"))
    if not wishlist_id or not wishlist_index or not spec:
        _clear_menu_filter_context(context)
        await reply_text(update, "Sessão expirada. Use /menu → ⚙️ Filtros novamente.")
        return ConversationHandler.END

    with SessionLocal() as db:
        ok, msg = add_filter(db, wishlist_id, spec[0], spec[1], value)

    if not ok:
        await reply_text(update, f"{msg}\n\nEnvie outro valor ou /cancelar.")
        return MENU_FILTER_SELECT_VALUE

    _clear_menu_filter_context(context)
    await reply_text(
        update,
        f"{msg}\n\nVer filtros: /wishlist_filter_list {wishlist_index}\nAdicionar outro filtro: /menu → ⚙️ Filtros",
    )
    return ConversationHandler.END


async def _show_menu_filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE, feedback: str | None = None):
    wishlist_index = context.user_data.get("menu_filter_wishlist_index")
    if not wishlist_index:
        _clear_menu_filter_context(context)
        await _safe_edit_or_send(update, "Sessão expirada. Use /menu → ⚙️ Filtros novamente.")
        return ConversationHandler.END

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if wishlist_index < 1 or wishlist_index > len(wishlists):
            _clear_menu_filter_context(context)
            await _safe_edit_or_send(update, "Wishlist inválida. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        wl = wishlists[wishlist_index - 1]
        fs = list_filters(db, wl.id)

    if not fs:
        text = "Essa wishlist ainda não tem filtros."
        if feedback:
            text = f"{feedback}\n\n{text}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar filtro", callback_data="FILTER:ACTION:add")],
            [InlineKeyboardButton("↩️ Voltar", callback_data="FILTER:BACK")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")],
        ])
        await _safe_edit_or_send(update, text, reply_markup=kb)
        return MENU_FILTER_SELECT_VALUE

    text = render_wishlist_filters(fs, wishlist_query=wl.query)
    if feedback:
        text = f"{feedback}\n\n{text}"
    buttons = [[InlineKeyboardButton(f"🗑️ Remover {i}", callback_data=f"FILTER:RM:{wishlist_index}:{i}")] for i in range(1, len(fs) + 1)]
    buttons.extend([
        [InlineKeyboardButton("➕ Adicionar filtro", callback_data="FILTER:ACTION:add")],
        [InlineKeyboardButton("↩️ Voltar", callback_data="FILTER:BACK")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")],
    ])
    await _safe_edit_or_send(update, text, reply_markup=InlineKeyboardMarkup(buttons))
    return MENU_FILTER_SELECT_VALUE


async def _menu_filter_remove_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split(":")
    if len(parts) != 4:
        await _safe_edit_or_send(update, "Ação inválida. Use /menu → ⚙️ Filtros novamente.")
        return ConversationHandler.END

    try:
        wishlist_index = int(parts[2])
        filter_index = int(parts[3])
    except ValueError:
        await _safe_edit_or_send(update, "Filtro não encontrado. Atualize a lista de filtros.")
        return MENU_FILTER_SELECT_VALUE

    if not context.user_data.get("menu_filter_wishlist_index"):
        await _safe_edit_or_send(update, "Sessão expirada. Abra novamente /menu → ⚙️ Filtros.")
        return ConversationHandler.END

    if wishlist_index != context.user_data.get("menu_filter_wishlist_index"):
        await _safe_edit_or_send(update, "Wishlist não encontrada para sua conta.")
        return ConversationHandler.END

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if wishlist_index < 1 or wishlist_index > len(wishlists):
            await _safe_edit_or_send(update, "Wishlist não encontrada para sua conta.")
            return ConversationHandler.END
        wl = wishlists[wishlist_index - 1]
        fs = list_filters(db, wl.id)
        if filter_index < 1 or filter_index > len(fs):
            await _safe_edit_or_send(update, "Filtro não encontrado. Atualize a lista de filtros.")
            return MENU_FILTER_SELECT_VALUE
        ok, msg = remove_filter(db, wl.id, filter_index)

    feedback = f"✅ {msg}" if ok else "Não consegui remover o filtro agora. Tente novamente."
    return await _show_menu_filter_list(update, context, feedback=feedback)


async def menu_create_wishlist_on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if not query:
        await reply_text(update, "Texto inválido. Envie o carro/busca ou use /cancelar.")
        return MENU_CREATE_WISHLIST_QUERY

    context.user_data[MENU_CREATE_WISHLIST_QUERY_KEY] = query
    context.user_data.pop(MENU_CREATE_WISHLIST_CREATED_KEY, None)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Criar agora", callback_data="CWL:CREATE")],
        [InlineKeyboardButton("⚙️ Criar e adicionar filtros", callback_data="CWL:CREATE_FILTERS")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="CWL:CANCEL")],
    ])
    await reply_text(update, f"Busca:\n{query}\n\nComo deseja continuar?", reply_markup=kb)
    return MENU_CREATE_WISHLIST_CONFIRM


async def cb_menu_create_wishlist_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)
    data = (q.data or "").strip()

    if data == "CWL:CANCEL":
        _clear_menu_create_wishlist_context(context)
        _clear_menu_filter_context(context)
        await _safe_edit_or_send(update, "Criação de wishlist cancelada.")
        return ConversationHandler.END

    query = (context.user_data.get(MENU_CREATE_WISHLIST_QUERY_KEY) or "").strip()
    if not query:
        await _safe_edit_or_send(update, "Sessão expirada. Abra novamente /menu → ➕ Criar wishlist.")
        return ConversationHandler.END

    if context.user_data.get(MENU_CREATE_WISHLIST_CREATED_KEY):
        await _safe_edit_or_send(update, "Wishlist já criada nesta sessão. Use /menu para continuar.")
        return ConversationHandler.END

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        ok, msg = add_wishlist(db, user.id, query)
        wishlists = list_wishlists(db, user.id) if ok else []

    if not ok:
        await _safe_edit_or_send(update, f"Não consegui criar a wishlist:\n{msg}\n\nEnvie outro texto ou use /cancelar.")
        return MENU_CREATE_WISHLIST_QUERY

    context.user_data[MENU_CREATE_WISHLIST_CREATED_KEY] = True
    if data == "CWL:CREATE":
        _clear_menu_create_wishlist_context(context)
        _clear_menu_filter_context(context)
        await _safe_edit_or_send(update, f"{msg}\n\nUse /menu para ver suas buscas ou adicionar filtros.")
        return ConversationHandler.END

    created = wishlists[-1] if wishlists else None
    if not created:
        _clear_menu_create_wishlist_context(context)
        await _safe_edit_or_send(update, "Wishlist criada, mas não consegui abrir os filtros agora. Use /menu → ⚙️ Filtros.")
        return ConversationHandler.END

    context.user_data["menu_filter_wishlist_index"] = len(wishlists)
    context.user_data["menu_filter_wishlist_id"] = created.id
    context.user_data.pop("menu_filter_type", None)
    _clear_menu_create_wishlist_context(context)
    await _show_menu_filter_actions(
        update,
        len(wishlists),
        created.query,
        prefix_text=f"Wishlist criada: {created.query}\n\nAgora vamos melhorar essa busca com filtros.",
    )
    return MENU_FILTER_SELECT_VALUE


async def menu_create_wishlist_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_menu_create_wishlist_context(context)
    _clear_menu_filter_context(context)
    await reply_text(update, "Criação de wishlist cancelada.")
    return ConversationHandler.END


async def menu_filter_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_menu_filter_context(context)
    await reply_text(update, "Configuração de filtro cancelada.")
    return ConversationHandler.END


def menu_create_wishlist_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_menu, pattern=r"^MENU:CREATE_WISHLIST$")],
        states={
            MENU_CREATE_WISHLIST_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_create_wishlist_on_text),
                MessageHandler(filters.COMMAND, menu_create_wishlist_cancel),
            ],
            MENU_CREATE_WISHLIST_CONFIRM: [
                CallbackQueryHandler(cb_menu_create_wishlist_confirm, pattern=r"^CWL:(CREATE|CREATE_FILTERS|CANCEL)$"),
            ],
            MENU_FILTER_SELECT_VALUE: [
                CallbackQueryHandler(cb_menu_filter, pattern=r"^FILTER:(WL:\d+|TYPE:[a-z_]+|ACTION:(?:add|list)|RM:\d+:\d+|BACK|DONE|CANCEL)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_filter_on_value),
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


def menu_filter_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_menu, pattern=r"^MENU:FILTERS$")],
        allow_reentry=True,
        states={
            MENU_FILTER_SELECT_VALUE: [
                CallbackQueryHandler(cb_menu_filter, pattern=r"^FILTER:(WL:\d+|TYPE:[a-z_]+|ACTION:(?:add|list)|RM:\d+:\d+|BACK|DONE|CANCEL)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_filter_on_value),
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", menu_filter_cancel),
            CommandHandler("cancel", menu_filter_cancel),
            CallbackQueryHandler(cb_menu_filter, pattern=r"^FILTER:CANCEL$"),
        ],
        name="menu_filter_add",
        persistent=False,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
