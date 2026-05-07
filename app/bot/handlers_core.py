from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from app.bot.utils import reply_text
from app.db.session import SessionLocal
from app.bot.renderers import render_all_tracked_listings, render_help_text, render_start_text, render_user_wishlists, render_wishlist_filters, render_upgrade_text, build_upgrade_keyboard
from app.core.settings import settings
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists, get_user_plan_snapshot, add_wishlist, add_filter, list_filters, remove_filter, get_wishlist_summaries, normalize_wishlist_filter_input, create_wishlist_with_filters, parse_wishlist_query_with_implicit_filters, parse_wishlist_filter_expression, remove_wishlist
from app.services.wishlist_tracking_service import list_tracked_listings

MENU_CREATE_WISHLIST_QUERY = 1
MENU_FILTER_SELECT_VALUE = 2

MENU_FILTER_USER_DATA_KEYS = ("menu_filter_wishlist_index", "menu_filter_wishlist_id", "menu_filter_type")
MENU_CREATE_WISHLIST_DRAFT_KEYS = ("menu_create_wishlist_query", "menu_create_wishlist_draft_filters", "menu_create_wishlist_draft_filter_type")

FILTER_TYPE_TO_SPEC = {
    "price_max": ("price", "lte", "Qual preço máximo?\nExemplo: 90000 ou 90.000"),
    "year_min": ("year", "gte", "Qual ano mínimo?\nExemplo: 2015"),
    "km_max": ("mileage_km", "lte", "Qual KM máximo?\nExemplo: 80000 ou 80.000"),
    "city": ("city", "eq", "Qual cidade?\nExemplo: São Paulo"),
    "state": ("state", "eq", "Qual estado/UF?\nExemplo: SP"),
}
DRAFT_FILTER_TYPE_TO_FIELD = {"price": "price", "year": "year", "mileage": "mileage_km", "city": "city", "state": "state"}
DRAFT_FILTER_PROMPTS = {
    "price": "Qual preço?\nExemplos:\n- até 150000\n- entre 70000 e 90000\n- a partir de 50000",
    "year": "Qual ano?\nExemplos:\n- 2018\n- até 2021\n- a partir de 2017\n- entre 2017 e 2021",
    "mileage": "Qual quilometragem?\nExemplos:\n- até 90000\n- menor que 80000\n- entre 30000 e 100000",
    "city": "Qual cidade?\nExemplo: São Paulo",
    "state": "Qual estado?\nExemplo: SP ou São Paulo",
}

def _format_brl(value: str) -> str:
    return f"R$ {int(value):,}".replace(",", ".")


def _build_draft_group_label(group: str, filters_payload: list[dict]) -> str:
    op_map = {f["operator"]: f["value"] for f in filters_payload}
    if group == "year":
        if "gte" in op_map and "lte" in op_map:
            return f"Ano entre {op_map['gte']} e {op_map['lte']}"
        if "gte" in op_map:
            return f"Ano a partir de {op_map['gte']}"
        if "lte" in op_map:
            return f"Ano até {op_map['lte']}"
    if group == "price":
        if "gte" in op_map and "lte" in op_map:
            return f"Preço entre {_format_brl(op_map['gte'])} e {_format_brl(op_map['lte'])}"
        if "gte" in op_map:
            return f"Preço a partir de {_format_brl(op_map['gte'])}"
        if "lte" in op_map:
            return f"Preço até {_format_brl(op_map['lte'])}"
    if group == "mileage_km":
        if "lte" in op_map:
            return f"KM até {int(op_map['lte']):,}".replace(",", ".")
    if group == "state" and "eq" in op_map:
        return f"Estado: {op_map['eq']}"
    if group == "city" and "eq" in op_map:
        return f"Cidade: {op_map['eq']}"
    return f"{group}: " + ", ".join(f"{f['operator']} {f['value']}" for f in filters_payload)


def build_draft_filter_groups(filters: list) -> list[dict]:
    by_group: dict[str, list[dict]] = {}
    for f in filters or []:
        payload = {"field": f.field, "operator": f.operator, "value": f.value}
        by_group.setdefault(f.field, []).append(payload)
    groups: list[dict] = []
    for group, payloads in by_group.items():
        groups.append({"group": group, "label": _build_draft_group_label(group, payloads), "filters": payloads})
    return groups




def _clear_menu_create_wishlist_draft_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in MENU_CREATE_WISHLIST_DRAFT_KEYS:
        context.user_data.pop(key, None)


def _render_draft_filters(filters_draft: list[dict]) -> str:
    if not filters_draft:
        return "Nenhum filtro adicionado ainda."
    lines = [f"{i}. {f.get('label')}" for i, f in enumerate(filters_draft, start=1)]
    return "\n".join(lines)


def _draft_filters_menu_markup(filters_draft: list[dict]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("➕ Adicionar filtro", callback_data="CWLF:ACTION:add")],
        [InlineKeyboardButton("📋 Ver filtros", callback_data="CWLF:ACTION:list")],
    ]
    if filters_draft:
        buttons.extend([[InlineKeyboardButton(f"🗑️ Remover {i}", callback_data=f"CWLF:RM:{i}")] for i in range(1, len(filters_draft) + 1)])
    buttons.extend([
        [InlineKeyboardButton("✅ Concluir e criar", callback_data="CWLF:DONE")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="CWLF:CANCEL")],
    ])
    return InlineKeyboardMarkup(buttons)


async def _show_draft_filters_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, feedback: str | None = None):
    query = context.user_data.get("menu_create_wishlist_query") or "(sem busca)"
    filters_draft = context.user_data.get("menu_create_wishlist_draft_filters") or []
    text = f"Filtros para: {query}\n\n{_render_draft_filters(filters_draft)}"
    if feedback:
        text = f"{feedback}\n\n{text}"
    if update.callback_query:
        await _safe_edit_or_send(update, text, reply_markup=_draft_filters_menu_markup(filters_draft))
    else:
        await reply_text(update, text, reply_markup=_draft_filters_menu_markup(filters_draft))
    return MENU_CREATE_WISHLIST_QUERY

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
    await _show_main_menu(update)


async def _show_main_menu(update: Update) -> None:
    markup = _main_menu_markup_for_user(update)
    await reply_text(
        update,
        "🚗 AutoHunter\n\n"
        "O que você quer fazer?",
        reply_markup=markup,
    )


def _main_menu_markup_for_user(update: Update) -> InlineKeyboardMarkup:
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        snap = get_user_plan_snapshot(db, user.id)
    return _menu_keyboard(is_premium=(snap.get("plan_code") == "premium"))


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)

    data = (q.data or "").strip()
    if data == "MENU:SEARCH":
        await _safe_edit_or_send(update, "🔎 Buscar agora\n\nEssa é uma busca pontual. Eu procuro uma vez e não salvo monitoramento.\n\nExemplo:\n`/buscar civic 2019 até 90000 sp`\n\nPara receber alertas todos os dias, use ➕ Criar busca.")
        return
    if data == "MENU:UPGRADE":
        await _safe_edit_or_send(
            update,
            render_upgrade_text(bool(settings.mercado_pago_monthly_payment_link or settings.mercado_pago_annual_payment_link)),
            reply_markup=build_upgrade_keyboard(settings.mercado_pago_monthly_payment_link, settings.mercado_pago_annual_payment_link),
        )
        return
    if data == "MENU:CREATE_WISHLIST":
        await _safe_edit_or_send(
            update,
            "Qual carro você quer encontrar?\n\nExemplos:\n- civic si\n- corolla até 120000\n- audi a5 entre 2017 e 2021\n- compass diesel até 180000 em SP\n\nDica: quanto mais específico, melhores serão os alertas.",
        )
        return MENU_CREATE_WISHLIST_QUERY
    if data == "MENU:WISHLISTS":
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            summaries = get_wishlist_summaries(db, user.id)
        await _safe_edit_or_send(update, render_user_wishlists(summaries), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Remover busca", callback_data="WL:REMOVE_MENU")],
            [InlineKeyboardButton("⭐ Anúncios rastreados", callback_data="WL:TRACKED")],
            [InlineKeyboardButton("↩️ Voltar", callback_data="WL:BACK")],
        ]))
        return
    if data == "WL:BACK":
        await _safe_edit_or_send(update, "🚗 AutoHunter\n\nO que você quer fazer?", reply_markup=_main_menu_markup_for_user(update))
        return
    if data == "WL:TRACKED":
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
            tracked_messages = []
            for i, _wl in enumerate(wishlists, start=1):
                _ok, msg = list_tracked_listings(db, user_id=user.id, wishlist_index=i)
                tracked_messages.append(msg)
        await _safe_edit_or_send(update, render_all_tracked_listings(wishlists, tracked_messages)[:3900], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="MENU:WISHLISTS")]]))
        return
    if data == "WL:REMOVE_MENU":
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if not wishlists:
            await _safe_edit_or_send(update, "Você ainda não tem buscas para remover.")
            return
        kb = [[InlineKeyboardButton(f"🗑️ Remover {i} — {wl.query}", callback_data=f"WL:REMOVE:{i}")] for i, wl in enumerate(wishlists, start=1)]
        kb.append([InlineKeyboardButton("↩️ Voltar", callback_data="MENU:WISHLISTS")])
        await _safe_edit_or_send(update, "Escolha a busca para remover:", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data.startswith("WL:REMOVE:"):
        idx = int(data.split(":")[-1])
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if idx < 1 or idx > len(wishlists):
            await _safe_edit_or_send(update, "Busca não encontrada para sua conta.")
            return
        wl = wishlists[idx - 1]
        await _safe_edit_or_send(update, f"Remover esta busca?\n\nBusca: {wl.query}\n\nIsso também remove os filtros e anúncios rastreados vinculados a ela.\n\nEssa ação não pode ser desfeita.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Sim, remover", callback_data=f"WL:REMOVE_CONFIRM:{idx}")],
            [InlineKeyboardButton("↩️ Voltar", callback_data="WL:REMOVE_MENU")],
        ]))
        return
    if data.startswith("WL:REMOVE_CONFIRM:"):
        idx = int(data.split(":")[-1])
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            ok, _msg = remove_wishlist(db, user.id, idx)
        await _safe_edit_or_send(update, "✅ Busca removida.\n\nSe quiser, você pode criar uma nova busca em /menu." if ok else "Busca não encontrada para sua conta.")
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
        await _safe_edit_or_send(update, "Os filtros guiados agora ficam no fluxo de criação da wishlist. Use /menu → ➕ Criar busca.")
        return
    if data == "MENU:HELP":
        await _safe_edit_or_send(update, render_help_text())
        return

    await _safe_edit_or_send(update, "Essa opção não está mais válida.\n\nAbra o menu novamente para continuar.\n\nUse /menu.")


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
def _menu_keyboard(is_premium: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("➕ Criar busca", callback_data="MENU:CREATE_WISHLIST")],
        [InlineKeyboardButton("🎯 Minhas buscas", callback_data="MENU:WISHLISTS")],
        [InlineKeyboardButton("⭐ Anúncios rastreados", callback_data="MENU:TRACKED")],
        [InlineKeyboardButton("🔎 Buscar agora", callback_data="MENU:SEARCH")],
    ]
    if not is_premium:
        rows.append([InlineKeyboardButton("🚀 Premium", callback_data="MENU:UPGRADE")])
    rows.append([InlineKeyboardButton("❓ Ajuda", callback_data="MENU:HELP")])
    return InlineKeyboardMarkup(rows)


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


async def cb_menu_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)
    data = (q.data or "").strip()

    if data == "FILTER:CANCEL":
        _clear_menu_filter_context(context)
        await _safe_edit_or_send(update, "Os filtros guiados agora ficam no fluxo de criação da wishlist. Use /menu → ➕ Criar busca.")
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

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar filtro", callback_data="FILTER:ACTION:add")],
            [InlineKeyboardButton("📋 Ver filtros", callback_data="FILTER:ACTION:list")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")],
        ])
        await _safe_edit_or_send(update, "Escolha uma ação para a wishlist:", reply_markup=kb)
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
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar filtro", callback_data="FILTER:ACTION:add")],
            [InlineKeyboardButton("📋 Ver filtros", callback_data="FILTER:ACTION:list")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")],
        ])
        await _safe_edit_or_send(update, "Escolha uma ação para a wishlist:", reply_markup=kb)
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
    value_input_mode = context.user_data.get("menu_create_wishlist_draft_filter_type")
    if value_input_mode:
        field = DRAFT_FILTER_TYPE_TO_FIELD[value_input_mode]
        raw_value = (update.message.text or "").strip()
        try:
            parsed = parse_wishlist_filter_expression(field, raw_value)
        except ValueError as exc:
            await reply_text(update, f"Valor inválido: {exc}\nEnvie outro valor ou use /cancelar.")
            return MENU_CREATE_WISHLIST_QUERY

        draft_filters = context.user_data.setdefault("menu_create_wishlist_draft_filters", [])
        filters_payload = [{"field": n.field, "operator": n.operator, "value": n.value} for n in parsed]
        label = _build_draft_group_label(field, filters_payload)
        draft_filters = [g for g in draft_filters if g.get("group") != field]
        draft_filters.append({"group": field, "label": label, "filters": filters_payload})
        context.user_data["menu_create_wishlist_draft_filters"] = draft_filters
        context.user_data.pop("menu_create_wishlist_draft_filter_type", None)
        return await _show_draft_filters_screen(update, context, feedback="✅ Filtro adicionado/atualizado.")

    if "menu_create_wishlist_draft_filters" in context.user_data:
        await reply_text(
            update,
            "Use os botões para adicionar filtros, concluir ou cancelar. "
            "Para informar um valor, primeiro escolha o tipo de filtro.",
        )
        return MENU_CREATE_WISHLIST_QUERY

    query = (update.message.text or "").strip()
    if not query:
        await reply_text(update, "Texto inválido. Envie o carro/busca ou use /cancelar.")
        return MENU_CREATE_WISHLIST_QUERY

    parsed = parse_wishlist_query_with_implicit_filters(query)
    context.user_data["menu_create_wishlist_query"] = parsed.cleaned_query
    context.user_data["menu_create_wishlist_draft_filters"] = build_draft_filter_groups(parsed.filters)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Criar busca", callback_data="CWL:CREATE")],
        [InlineKeyboardButton("➕ Adicionar filtros", callback_data="CWL:CREATE_FILTERS")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="CWL:CANCEL")],
    ])
    await reply_text(update, f"Entendi sua busca:\n\nCarro: {parsed.cleaned_query}\nFiltros detectados:\n{_render_draft_filters(context.user_data['menu_create_wishlist_draft_filters'])}\n\nQuer adicionar mais filtros antes de ativar?", reply_markup=kb)
    return MENU_CREATE_WISHLIST_QUERY




async def cb_menu_create_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)
    data = (q.data or "").strip()

    if data == "CWL:CANCEL" or data == "CWLF:CANCEL":
        _clear_menu_create_wishlist_draft_context(context)
        await _safe_edit_or_send(update, "Criação de busca cancelada.")
        return ConversationHandler.END

    if data == "CWL:CREATE":
        query = context.user_data.get("menu_create_wishlist_query")
        if not query:
            await _safe_edit_or_send(update, "Essa etapa expirou.\n\nPara continuar com segurança, abra o menu novamente e refaça a ação.\n\nUse /menu.")
            return ConversationHandler.END
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            draft_groups = context.user_data.get("menu_create_wishlist_draft_filters") or []
            if draft_groups:
                flat = [flt for g in draft_groups for flt in g.get("filters", [])]
                ok, msg, _ = create_wishlist_with_filters(db, user.id, query, flat)
            else:
                ok, msg = add_wishlist(db, user.id, query)
        if not ok:
            await _safe_edit_or_send(update, f"Não consegui concluir essa ação agora.\n\nTente novamente em alguns minutos.\nSe continuar acontecendo, envie esta mensagem para o suporte.\n\nDetalhe: {msg}")
            return MENU_CREATE_WISHLIST_QUERY
        _clear_menu_create_wishlist_draft_context(context)
        await _safe_edit_or_send(update, f"✅ Busca criada: {query}\n\nUse /menu para acompanhar.")
        return ConversationHandler.END

    if data == "CWL:CREATE_FILTERS":
        context.user_data["menu_create_wishlist_draft_filters"] = context.user_data.get("menu_create_wishlist_draft_filters") or []
        context.user_data.pop("menu_create_wishlist_draft_filter_type", None)
        return await _show_draft_filters_screen(update, context)

    if data == "CWLF:ACTION:add":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Preço", callback_data="CWLF:TYPE:price")],
            [InlineKeyboardButton("📅 Ano", callback_data="CWLF:TYPE:year")],
            [InlineKeyboardButton("🛣️ KM", callback_data="CWLF:TYPE:mileage")],
            [InlineKeyboardButton("📍 Cidade", callback_data="CWLF:TYPE:city")],
            [InlineKeyboardButton("🗺️ Estado", callback_data="CWLF:TYPE:state")],
            [InlineKeyboardButton("↩️ Voltar aos filtros", callback_data="CWLF:BACK")],
        ])
        await _safe_edit_or_send(update, "Escolha o tipo de filtro:", reply_markup=kb)
        return MENU_CREATE_WISHLIST_QUERY

    if data.startswith("CWLF:TYPE:"):
        ftype = data.split(":", 2)[2]
        if ftype not in DRAFT_FILTER_TYPE_TO_FIELD:
            await _safe_edit_or_send(update, "Tipo de filtro inválido.")
            return MENU_CREATE_WISHLIST_QUERY
        context.user_data["menu_create_wishlist_draft_filter_type"] = ftype
        await _safe_edit_or_send(update, DRAFT_FILTER_PROMPTS[ftype])
        return MENU_CREATE_WISHLIST_QUERY
    if data == "CWLF:BACK":
        context.user_data.pop("menu_create_wishlist_draft_filter_type", None)
        return await _show_draft_filters_screen(update, context)

    if data == "CWLF:ACTION:list":
        return await _show_draft_filters_screen(update, context)

    if data.startswith("CWLF:RM:"):
        try:
            idx = int(data.split(":", 2)[2])
        except ValueError:
            return await _show_draft_filters_screen(update, context, feedback="Índice inválido.")
        draft_groups = context.user_data.get("menu_create_wishlist_draft_filters") or []
        if idx < 1 or idx > len(draft_groups):
            return await _show_draft_filters_screen(update, context, feedback="Índice inválido.")
        draft_groups.pop(idx - 1)
        context.user_data["menu_create_wishlist_draft_filters"] = draft_groups
        return await _show_draft_filters_screen(update, context, feedback="✅ Filtro removido.")

    if data == "CWLF:DONE":
        query = context.user_data.get("menu_create_wishlist_query")
        draft_groups = context.user_data.get("menu_create_wishlist_draft_filters") or []
        filters_draft = []
        for g in draft_groups:
            if isinstance(g, dict) and "filters" in g:
                filters_draft.extend(g.get("filters", []))
            elif isinstance(g, dict) and {"field", "operator", "value"}.issubset(g.keys()):
                filters_draft.append({"field": g["field"], "operator": g["operator"], "value": g["value"]})
        if not query:
            _clear_menu_create_wishlist_draft_context(context)
            await _safe_edit_or_send(update, "Essa etapa expirou.\n\nPara continuar com segurança, abra o menu novamente e refaça a ação.\n\nUse /menu.")
            return ConversationHandler.END
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            ok, msg, _wid = create_wishlist_with_filters(db, user.id, query, filters_draft)
        if not ok:
            await _safe_edit_or_send(update, f"Não consegui concluir essa ação agora.\n\nTente novamente em alguns minutos.\nSe continuar acontecendo, envie esta mensagem para o suporte.\n\nDetalhe: {msg}")
            return MENU_CREATE_WISHLIST_QUERY
        _clear_menu_create_wishlist_draft_context(context)
        if draft_groups:
            labels = "\n".join(f"- {g.get('label')}" for g in draft_groups)
            await _safe_edit_or_send(update, f"✅ Busca criada com filtros.\n\nBusca: {query}\nFiltros:\n{labels}\n\nA primeira busca foi agendada com os filtros aplicados.\nUse /menu para acompanhar.")
        else:
            await _safe_edit_or_send(update, f"✅ Busca criada sem filtros. Você pode adicionar filtros depois pelo /menu.\n\nBusca: {query}\nUse /menu para acompanhar.")
        return ConversationHandler.END

    await _safe_edit_or_send(update, "Essa opção não está mais válida.\n\nAbra o menu novamente para continuar.\n\nUse /menu.")
    return MENU_CREATE_WISHLIST_QUERY


async def menu_create_wishlist_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_menu_create_wishlist_draft_context(context)
    await reply_text(update, "Criação de busca cancelada.")
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
                CallbackQueryHandler(cb_menu_create_wishlist, pattern=r"^(CWL:(?:CREATE|CREATE_FILTERS|CANCEL)|CWLF:(?:ACTION:(?:add|list)|TYPE:[a-z_]+|RM:\d+|DONE|CANCEL|BACK))$"),
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


def menu_filter_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_menu, pattern=r"^MENU:FILTERS$")],
        states={
            MENU_FILTER_SELECT_VALUE: [
                CallbackQueryHandler(cb_menu_filter, pattern=r"^FILTER:(WL:\d+|TYPE:[a-z_]+|ACTION:(?:add|list)|RM:\d+:\d+|BACK|CANCEL)$"),
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
