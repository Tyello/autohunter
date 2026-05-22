from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters
import hashlib
import json
import logging

from app.bot.utils import reply_text
from app.db.session import SessionLocal
from app.bot.renderers import render_all_tracked_listings, render_help_text, render_start_text, render_user_wishlists, render_wishlist_filters, render_upgrade_text, build_upgrade_choice_keyboard
from app.core.settings import settings
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists, get_user_plan_snapshot, add_wishlist, add_filter, list_filters, remove_filter, get_wishlist_summaries, normalize_wishlist_filter_input, create_wishlist_with_filters, parse_wishlist_query_with_implicit_filters, parse_wishlist_filter_expression, remove_wishlist, set_wishlist_active_state, add_wishlist_with_initial_summary, create_wishlist_with_filters_and_initial_summary
from app.services.wishlist_tracking_service import list_tracked_listings

MENU_CREATE_WISHLIST_QUERY = 1
MENU_FILTER_SELECT_VALUE = 2

MENU_FILTER_USER_DATA_KEYS = ("menu_filter_wishlist_index", "menu_filter_wishlist_id", "menu_filter_type")
MENU_CREATE_WISHLIST_DRAFT_KEYS = ("menu_create_wishlist_query", "menu_create_wishlist_draft_filters", "menu_create_wishlist_draft_filter_type")
logger = logging.getLogger(__name__)

FILTER_TYPE_TO_SPEC = {
    "price": ("price", "eq", "Qual faixa de preço?\nExemplos:\n- até 120000\n- acima de 50000\n- a partir de 80000\n- entre 50000 e 90000"),
    "year": ("year", "eq", "Qual ano?\nExemplos:\n- a partir de 2017\n- até 2021\n- entre 2017 e 2021"),
    "mileage": ("mileage_km", "eq", "Qual quilometragem?\nExemplos:\n- até 80000\n- acima de 30000\n- entre 30000 e 90000"),
    "city": ("city", "eq", "Em qual cidade você quer buscar?\nExemplo: São Paulo"),
    "state": ("state", "eq", "Em qual estado?\nExemplos:\n- SP\n- São Paulo"),
    # Compatibilidade temporária com callbacks antigos já enviados no Telegram.
    "price_max": ("price", "eq", "Qual faixa de preço?\nExemplos:\n- até 120000\n- acima de 50000\n- a partir de 80000\n- entre 50000 e 90000"),
    "year_min": ("year", "eq", "Qual ano?\nExemplos:\n- a partir de 2017\n- até 2021\n- entre 2017 e 2021"),
    "km_max": ("mileage_km", "eq", "Qual quilometragem?\nExemplos:\n- até 80000\n- acima de 30000\n- entre 30000 e 90000"),
}
DRAFT_FILTER_TYPE_TO_FIELD = {"price": "price", "year": "year", "mileage": "mileage_km", "city": "city", "state": "state"}
DRAFT_FILTER_PROMPTS = {
    "price": "Qual faixa de preço?\nExemplos:\n- até 120000\n- entre 90000 e 130000\n- a partir de 80000\n\nPode escrever com ou sem R$.",
    "year": "Qual ano você procura?\nExemplos:\n- 2018\n- a partir de 2017\n- até 2021\n- entre 2017 e 2021",
    "mileage": "Qual quilometragem máxima?\nExemplos:\n- até 80000\n- entre 30000 e 90000\n\nDica: para carro usado, KM ajuda muito a evitar anúncio ruim.",
    "city": "Em qual cidade você quer buscar?\nExemplo: São Paulo\n\nVocê também pode deixar sem cidade e filtrar só por estado.",
    "state": "Em qual estado?\nExemplos:\n- SP\n- São Paulo\n- RJ\n- Paraná",
}

def _format_brl(value: str) -> str:
    return f"R$ {int(value):,}".replace(",", ".")


def _build_draft_group_label(group: str, filters_payload: list[dict]) -> str:
    op_map = {f["operator"]: f["value"] for f in filters_payload}
    if group == "year":
        if "gte" in op_map and "lte" in op_map:
            return f"Ano {op_map['gte']}" if op_map["gte"] == op_map["lte"] else f"Ano entre {op_map['gte']} e {op_map['lte']}"
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


def _build_wishlist_create_key(chat_id: int, query: str, filters: list[dict]) -> str:
    normalized_filters = sorted(
        [
            {
                "field": str(f.get("field", "")).strip().lower(),
                "operator": str(f.get("operator", "")).strip().lower(),
                "value": str(f.get("value", "")).strip().lower(),
            }
            for f in (filters or [])
        ],
        key=lambda item: (item["field"], item["operator"], item["value"]),
    )
    payload = {
        "chat_id": chat_id,
        "query": (query or "").strip().lower(),
        "filters": normalized_filters,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_create_feedback(msg: object) -> str:
    if not isinstance(msg, str):
        return ""
    lines = [line.strip() for line in msg.strip().splitlines() if line.strip()]
    if not lines:
        return ""
    if lines[0].startswith("✅ Busca criada com sucesso.") or lines[0].startswith("✅ Wishlist criada:"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _render_initial_run_feedback(summary: dict | None) -> str:
    if not summary:
        return "Primeira varredura:\n📡 Busca inicial agendada para processamento em segundo plano."
    triggered = int(summary.get("triggered") or 0)
    failed = int(summary.get("failed") or 0)
    skipped = int(summary.get("skipped") or 0)
    if triggered > 0:
        return (
            "Primeira varredura:\n"
            f"📡 Busca inicial agendada em {triggered} fonte(s).\n"
            "Você receberá os alertas assim que os resultados forem processados."
        )
    if failed > 0:
        return (
            "Primeira varredura:\n"
            "⚠️ Não consegui agendar a primeira busca agora.\n"
            "Mesmo assim, o monitoramento contínuo segue ativo."
        )
    if skipped > 0:
        return (
            "Primeira varredura:\n"
            "⏳ Monitoramento salvo. A próxima execução automática fará a varredura."
        )
    return "Primeira varredura:\n📡 Monitoramento salvo para processamento em segundo plano."


def _post_creation_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Ver minhas buscas", callback_data="MENU:WISHLISTS")],
        [InlineKeyboardButton("➕ Criar outra busca", callback_data="MENU:CREATE_WISHLIST")],
    ])


def _render_draft_filters(filters_draft: list[dict]) -> str:
    if not filters_draft:
        return "Nenhum filtro adicionado ainda."
    lines = [f"{i}. {f.get('label')}" for i, f in enumerate(filters_draft, start=1)]
    return "\n".join(lines)


def _build_create_wishlist_summary_screen(query: str, filters_draft: list[dict], include_auctions: bool) -> tuple[str, InlineKeyboardMarkup]:
    has_filters = bool(filters_draft)
    create_label = "✅ Criar busca" if has_filters else "✅ Criar mesmo assim"
    auctions_status = _render_auctions_status(include_auctions)
    filters_text = _render_draft_filters(filters_draft)
    if has_filters:
        text = (
            f"Entendi sua busca:\n\nCarro: {query}\n"
            f"Filtros detectados:\n{filters_text}\n\n"
            f"Leilões: {auctions_status}\n\n"
            "Quer adicionar mais filtros antes de ativar?\n\n"
            "Quer incluir oportunidades de leilão nessa busca?"
        )
    else:
        text = (
            f"Entendi: {query}\n\n"
            "Essa busca ainda está bem aberta.\n"
            "Para receber alertas melhores, recomendo adicionar pelo menos preço, ano ou região.\n\n"
            f"Leilões: {auctions_status}\n\n"
            "Quer incluir oportunidades de leilão nessa busca?"
        )
    if include_auctions:
        text += "\n\nAtenção: em leilões, lance não é preço final. Confira edital, taxas, documentação e vistoria antes de participar."
    toggle_label = "❌ Não, apenas anúncios tradicionais" if include_auctions else "✅ Sim, incluir leilões"
    toggle_cb = "CWL:AUCTIONS:NO" if include_auctions else "CWL:AUCTIONS:YES"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Adicionar filtros", callback_data="CWL:CREATE_FILTERS")],
        [InlineKeyboardButton(create_label, callback_data="CWL:CREATE")],
        [InlineKeyboardButton(toggle_label, callback_data=toggle_cb)],
        [InlineKeyboardButton("❌ Cancelar", callback_data="CWL:CANCEL")],
    ])
    return text, kb


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


async def _show_create_wishlist_summary_screen(update: Update, context: ContextTypes.DEFAULT_TYPE, feedback: str | None = None):
    query = context.user_data.get("menu_create_wishlist_query") or "(sem busca)"
    filters_draft = context.user_data.get("menu_create_wishlist_draft_filters") or []
    include_auctions = bool(context.user_data.get("menu_create_wishlist_include_auctions", False))
    text, markup = _build_create_wishlist_summary_screen(query, filters_draft, include_auctions)
    if feedback:
        text = f"{feedback}\n\n{text}"
    if update.callback_query:
        await _safe_edit_or_send(update, text, reply_markup=markup)
    else:
        await reply_text(update, text, reply_markup=markup)
    return MENU_CREATE_WISHLIST_QUERY

def _wishlist_help_text() -> str:
    return (
        "🧰 Ajuda avançada de buscas\n\n"
        "Comandos /wishlist_* são legados/avançados e continuam funcionando por compatibilidade.\n\n"
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






def _start_markup(wishlist_count: int) -> InlineKeyboardMarkup:
    if wishlist_count > 0:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🎯 Ver minhas buscas", callback_data="MENU:WISHLISTS")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("➕ Criar minha primeira busca", callback_data="MENU:CREATE_WISHLIST")]])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        w = list_wishlists(db, user.id)

    await reply_text(update, render_start_text(len(w)), reply_markup=_start_markup(len(w)))

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
        "🎯 Garagem Alvo\n\n"
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
        await _safe_edit_or_send(update, "🔎 Buscar agora\n\nEssa é uma busca pontual. Eu procuro uma vez e não salvo monitoramento.\n\nExemplo:\n`/buscar civic si até 120000 sp`\n\nPara receber alertas todos os dias, use ➕ Criar busca.")
        return
    if data == "MENU:UPGRADE":
        await _safe_edit_or_send(
            update,
            render_upgrade_text(bool(settings.mercado_pago_monthly_payment_link or settings.mercado_pago_annual_payment_link)),
            reply_markup=build_upgrade_choice_keyboard(settings.mercado_pago_monthly_payment_link, settings.mercado_pago_annual_payment_link),
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
        buttons = []
        if summaries:
            buttons.append([InlineKeyboardButton("⚙️ Ajustar filtros", callback_data="WL:FILTERS_MENU")])
        if any(item.get("is_active", True) for item in summaries):
            buttons.append([InlineKeyboardButton("⏸️ Pausar busca", callback_data="WL:PAUSE_MENU")])
        if any(not item.get("is_active", True) for item in summaries):
            buttons.append([InlineKeyboardButton("▶️ Reativar busca", callback_data="WL:RESUME_MENU")])
        if summaries:
            buttons.append([InlineKeyboardButton("🗑️ Remover busca", callback_data="WL:REMOVE_MENU")])
        buttons.extend([
            [InlineKeyboardButton("⭐ Anúncios rastreados", callback_data="WL:TRACKED")],
            [InlineKeyboardButton("↩️ Voltar", callback_data="WL:BACK")],
        ])
        await _safe_edit_or_send(update, render_user_wishlists(summaries), reply_markup=InlineKeyboardMarkup(buttons))
        return
    if data in {"WL:PAUSE_MENU", "WL:RESUME_MENU", "WL:FILTERS_MENU"}:
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if not wishlists:
            await _safe_edit_or_send(update, "Você ainda não tem buscas.")
            return
        action = "PAUSE" if "PAUSE" in data else ("RESUME" if "RESUME" in data else "FILTERS")
        label = {"PAUSE": "⏸️ Pausar", "RESUME": "▶️ Reativar", "FILTERS": "⚙️ Ajustar filtros"}[action]
        if action == "PAUSE":
            indexed = [(i, wl) for i, wl in enumerate(wishlists, start=1) if getattr(wl, "is_active", True)]
        elif action == "RESUME":
            indexed = [(i, wl) for i, wl in enumerate(wishlists, start=1) if not getattr(wl, "is_active", True)]
        else:
            indexed = list(enumerate(wishlists, start=1))
        if not indexed:
            empty_msg = "Não há buscas ativas para pausar." if action == "PAUSE" else "Não há buscas pausadas para reativar."
            await _safe_edit_or_send(update, empty_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Voltar", callback_data="MENU:WISHLISTS")]]))
            return
        if action == "FILTERS":
            kb = [[InlineKeyboardButton(f"{label} {i} — {wl.query}", callback_data=f"WL:FILTERS_ID:{wl.id}")] for i, wl in indexed]
        else:
            kb = [[InlineKeyboardButton(f"{label} {i} — {wl.query}", callback_data=f"WL:{action}:{i}")] for i, wl in indexed]
        kb.append([InlineKeyboardButton("↩️ Voltar", callback_data="MENU:WISHLISTS")])
        await _safe_edit_or_send(update, "Escolha a busca:", reply_markup=InlineKeyboardMarkup(kb))
        return
    if data.startswith("WL:PAUSE:") or data.startswith("WL:RESUME:"):
        idx = int(data.split(":")[-1])
        is_pause = data.startswith("WL:PAUSE:")
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if idx < 1 or idx > len(wishlists):
            await _safe_edit_or_send(update, "Busca não encontrada para sua conta.")
            return
        wl = wishlists[idx - 1]
        if is_pause:
            text = f"⏸️ Pausar busca\n\nA busca continuará salva, mas não vai gerar novos alertas enquanto estiver pausada.\n\nImportante:\nbuscas pausadas continuam ocupando vaga do seu plano.\n\nBusca: {wl.query}"
            cb = f"WL:PAUSE_CONFIRM:{idx}"
        else:
            text = f"▶️ Reativar busca\n\nEssa busca voltará a gerar alertas quando aparecerem anúncios compatíveis.\n\nBusca: {wl.query}"
            cb = f"WL:RESUME_CONFIRM:{idx}"
        confirm_label = "⏸️ Pausar" if is_pause else "▶️ Reativar"
        await _safe_edit_or_send(update, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(confirm_label, callback_data=cb)], [InlineKeyboardButton("↩️ Voltar", callback_data="MENU:WISHLISTS")]]))
        return
    if data.startswith("WL:PAUSE_CONFIRM:") or data.startswith("WL:RESUME_CONFIRM:"):
        idx = int(data.split(":")[-1])
        resume = data.startswith("WL:RESUME_CONFIRM:")
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            ok, _query = set_wishlist_active_state(db, user.id, idx, is_active=resume)
        if not ok:
            await _safe_edit_or_send(update, "Busca não encontrada para sua conta.")
            return
        await _safe_edit_or_send(update, "✅ Busca reativada.\n\nVou voltar a monitorar anúncios compatíveis com essa busca." if resume else "✅ Busca pausada.\n\nEla continua salva e pode ser reativada quando quiser em Minhas buscas.")
        return
    if data.startswith("WL:FILTERS:"):
        idx = int(data.split(":")[-1])
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
            if idx < 1 or idx > len(wishlists):
                await _safe_edit_or_send(update, "Busca inválida.")
                return
            wl = wishlists[idx - 1]
            fs = list_filters(db, wl.id)
        context.user_data["menu_filter_wishlist_index"] = idx
        context.user_data["menu_filter_wishlist_id"] = wl.id
        await _safe_edit_or_send(update, _build_filters_adjust_text(wl, fs), reply_markup=_build_filters_adjust_keyboard(wl))
        return MENU_FILTER_SELECT_VALUE
    if data.startswith("WL:FILTERS_ID:"):
        wishlist_id = data.split(":")[-1]
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
            wishlist_index, wl = _find_user_wishlist_by_id(wishlists, wishlist_id)
            if not wl:
                await _safe_edit_or_send(update, "Busca não encontrada. Abra Minhas buscas novamente.")
                return
            fs = list_filters(db, wl.id)
        context.user_data["menu_filter_wishlist_index"] = wishlist_index
        context.user_data["menu_filter_wishlist_id"] = wl.id
        await _safe_edit_or_send(update, _build_filters_adjust_text(wl, fs), reply_markup=_build_filters_adjust_keyboard(wl))
        return MENU_FILTER_SELECT_VALUE
    if data == "WL:FILTER:AUCTIONS:TOGGLE":
        wishlist_id = context.user_data.get("menu_filter_wishlist_id")
        if not wishlist_id:
            await _safe_edit_or_send(update, "Sessão expirada. Abra novamente /menu → Minhas buscas.")
            return ConversationHandler.END
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
            _idx, wl = _find_user_wishlist_by_id(wishlists, wishlist_id)
            if not wl:
                await _safe_edit_or_send(update, "Busca não encontrada para sua conta.")
                return ConversationHandler.END
        status_enabled = bool(getattr(wl, "include_auctions", False))
        if status_enabled:
            status_label = "✅ Leilões ativados"
            buttons = [[InlineKeyboardButton("Desativar leilões", callback_data="WL:AUCTIONS:DISABLE")]]
        else:
            status_label = "Leilões: desativado"
            buttons = [[InlineKeyboardButton("⚠️ Ativar leilões", callback_data="WL:AUCTIONS:ENABLE")]]
        buttons.append([InlineKeyboardButton("↩️ Voltar aos filtros", callback_data=f"WL:FILTERS_ID:{wishlist_id}")])
        await _safe_edit_or_send(update, status_label, reply_markup=InlineKeyboardMarkup(buttons))
        return MENU_FILTER_SELECT_VALUE
    if data in {"WL:AUCTIONS:ENABLE", "WL:AUCTIONS:DISABLE"}:
        wishlist_id = context.user_data.get("menu_filter_wishlist_id")
        if not wishlist_id:
            await _safe_edit_or_send(update, "Sessão expirada. Abra novamente /menu → Minhas buscas.")
            return ConversationHandler.END
        enable = data.endswith("ENABLE")
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
            _idx, wl = _find_user_wishlist_by_id(wishlists, wishlist_id)
            if not wl:
                await _safe_edit_or_send(update, "Busca não encontrada para sua conta.")
                return ConversationHandler.END
            wl.include_auctions = enable
            db.add(wl)
            db.commit()
            db.refresh(wl)
            fs = list_filters(db, wl.id)
            feedback = (
                "✅ Leilões ativados para esta busca.\n\nA partir de agora, também vamos considerar oportunidades em leilão compatíveis com seus filtros.\n\nAtenção: lance não é preço final. Verifique edital, taxas/comissão, documentação e vistoria antes de participar."
                if enable
                else "✅ Leilões desativados para esta busca.\nVocê continuará recebendo alertas de anúncios normais compatíveis."
            )
            text = f"{feedback}\n\n{_build_filters_adjust_text(wl, fs)}"
        await _safe_edit_or_send(update, text, reply_markup=_build_filters_adjust_keyboard(wl))
        return MENU_FILTER_SELECT_VALUE
    if data == "WL:BACK":
        await _safe_edit_or_send(update, "🎯 Garagem Alvo\n\nO que você quer fazer?", reply_markup=_main_menu_markup_for_user(update))
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
        await _safe_edit_or_send(update, "Os filtros guiados agora ficam no fluxo de criação da busca. Use /menu → ➕ Criar busca.")
        return
    if data == "MENU:HELP":
        await _safe_edit_or_send(update, render_help_text())
        return

    await _safe_edit_or_send(update, "Essa opção não está mais válida.\n\nAbra o menu novamente para continuar.\n\nUse /menu.")


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(update, "🤖 Garagem Alvo — appv4\nRuntime interno: AutoHunter")


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
        f"Buscas: {len(w)}/{max_w}\n"
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
        await _safe_edit_or_send(update, "Os filtros guiados agora ficam no fluxo de criação da busca. Use /menu → ➕ Criar busca.")
        return ConversationHandler.END

    if data.startswith("FILTER:WL:"):
        try:
            wishlist_index = int(data.split(":")[-1])
        except ValueError:
            await _safe_edit_or_send(update, "Busca inválida. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
        if wishlist_index < 1 or wishlist_index > len(wishlists):
            await _safe_edit_or_send(update, "Busca inválida. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        wl = wishlists[wishlist_index - 1]
        context.user_data["menu_filter_wishlist_index"] = wishlist_index
        context.user_data["menu_filter_wishlist_id"] = wl.id

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar filtro", callback_data="FILTER:ACTION:add")],
            [InlineKeyboardButton("📋 Ver filtros", callback_data="FILTER:ACTION:list")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="FILTER:CANCEL")],
        ])
        await _safe_edit_or_send(update, "Escolha uma ação para a busca:", reply_markup=kb)
        return MENU_FILTER_SELECT_VALUE

    if data == "FILTER:ACTION:add":
        if not context.user_data.get("menu_filter_wishlist_id"):
            await _safe_edit_or_send(update, "Sessão expirada. Use /menu → ⚙️ Filtros novamente.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Preço / faixa", callback_data="FILTER:TYPE:price")],
            [InlineKeyboardButton("📅 Ano", callback_data="FILTER:TYPE:year")],
            [InlineKeyboardButton("🛣️ KM", callback_data="FILTER:TYPE:mileage")],
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
        await _safe_edit_or_send(update, "Escolha uma ação para a busca:", reply_markup=kb)
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
    spec = FILTER_TYPE_TO_SPEC.get(context.user_data.get("menu_filter_type"))
    if not wishlist_id or not spec:
        _clear_menu_filter_context(context)
        await reply_text(update, "Sessão expirada. Use /menu → ⚙️ Filtros novamente.")
        return ConversationHandler.END

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        _wishlist_index, wl = _find_user_wishlist_by_id(wishlists, wishlist_id)
        if not wl:
            _clear_menu_filter_context(context)
            await reply_text(update, "Busca não encontrada. Abra Minhas buscas novamente.")
            return ConversationHandler.END

        try:
            parsed = parse_wishlist_filter_expression(spec[0], value)
        except ValueError as exc:
            await reply_text(update, f"{exc}\n\nEnvie outro valor ou /cancelar.")
            return MENU_FILTER_SELECT_VALUE

        fields_to_replace = {"price", "year", "mileage_km"}
        if spec[0] in fields_to_replace:
            existing = list_filters(db, wishlist_id)
            for idx in range(len(existing), 0, -1):
                if existing[idx - 1].field == spec[0]:
                    remove_filter(db, wishlist_id, idx)

        ok, msg = True, ""
        for item in parsed:
            ok, msg = add_filter(db, wishlist_id, item.field, item.operator, item.value)
            if not ok:
                break

    if not ok:
        await reply_text(update, f"{msg}\n\nEnvie outro valor ou /cancelar.")
        return MENU_FILTER_SELECT_VALUE

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        _wishlist_index, wl = _find_user_wishlist_by_id(wishlists, wishlist_id)
        if not wl:
            _clear_menu_filter_context(context)
            await reply_text(update, "Busca não encontrada. Abra Minhas buscas novamente.")
            return ConversationHandler.END
        fs = list_filters(db, wl.id)

    text = (
        f"✅ Filtro atualizado.\n"
        f"Busca: {wl.query if wl else '(indisponível)'}\n\n"
        f"Filtros atuais:\n{('- Nenhum filtro ainda' if not fs else render_wishlist_filters(fs, wishlist_query=None))}\n\n"
        "O que deseja fazer agora?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Ajustar outro filtro", callback_data="FILTER:ACTION:add")],
        [InlineKeyboardButton("📋 Ver filtros", callback_data="FILTER:ACTION:list")],
        [InlineKeyboardButton("🎯 Escolher outra busca", callback_data="WL:FILTERS_MENU")],
        [InlineKeyboardButton("↩️ Voltar para Minhas buscas", callback_data="MENU:WISHLISTS")],
    ])
    await reply_text(update, text, reply_markup=kb)
    return MENU_FILTER_SELECT_VALUE


async def _show_menu_filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE, feedback: str | None = None):
    wishlist_id = context.user_data.get("menu_filter_wishlist_id")
    if not wishlist_id:
        _clear_menu_filter_context(context)
        await _safe_edit_or_send(update, "Sessão expirada. Use /menu → ⚙️ Filtros novamente.")
        return ConversationHandler.END

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        wishlist_index, wl = _find_user_wishlist_by_id(wishlists, wishlist_id)
        if not wl:
            _clear_menu_filter_context(context)
            await _safe_edit_or_send(update, "Busca não encontrada. Abra Minhas buscas novamente.")
            return ConversationHandler.END
        fs = list_filters(db, wl.id)

    if not fs:
        text = "Essa busca ainda não tem filtros."
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
    buttons = [[InlineKeyboardButton(f"🗑️ Remover {i}", callback_data=f"FILTER:RM:{wishlist_id}:{i}")] for i in range(1, len(fs) + 1)]
    buttons.extend([
        [InlineKeyboardButton("➕ Ajustar outro filtro", callback_data="FILTER:ACTION:add")],
        [InlineKeyboardButton("🎯 Escolher outra busca", callback_data="WL:FILTERS_MENU")],
        [InlineKeyboardButton("↩️ Voltar para Minhas buscas", callback_data="MENU:WISHLISTS")],
    ])
    await _safe_edit_or_send(update, text, reply_markup=InlineKeyboardMarkup(buttons))
    return MENU_FILTER_SELECT_VALUE


async def _menu_filter_remove_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split(":")
    if len(parts) != 4:
        await _safe_edit_or_send(update, "Ação inválida. Use /menu → ⚙️ Filtros novamente.")
        return ConversationHandler.END

    try:
        wishlist_id = parts[2]
        filter_index = int(parts[3])
    except ValueError:
        await _safe_edit_or_send(update, "Filtro não encontrado. Atualize a lista de filtros.")
        return MENU_FILTER_SELECT_VALUE

    if not context.user_data.get("menu_filter_wishlist_id"):
        await _safe_edit_or_send(update, "Sessão expirada. Abra novamente /menu → ⚙️ Filtros.")
        return ConversationHandler.END

    if str(wishlist_id) != str(context.user_data.get("menu_filter_wishlist_id")):
        await _safe_edit_or_send(update, "Busca não encontrada para sua conta.")
        return ConversationHandler.END

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        _wishlist_index, wl = _find_user_wishlist_by_id(wishlists, wishlist_id)
        if not wl:
            await _safe_edit_or_send(update, "Busca não encontrada para sua conta.")
            return ConversationHandler.END
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
    context.user_data.pop("menu_create_wishlist_creating", None)
    context.user_data.pop("menu_create_wishlist_completed", None)
    context.user_data.pop("menu_create_wishlist_last_create_key", None)
    context.user_data["menu_create_wishlist_query"] = parsed.cleaned_query
    context.user_data["menu_create_wishlist_draft_filters"] = build_draft_filter_groups(parsed.filters)
    context.user_data["menu_create_wishlist_include_auctions"] = False
    return await _show_create_wishlist_summary_screen(update, context)




async def cb_menu_create_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)
    data = (q.data or "").strip()

    if data == "CWL:CANCEL" or data == "CWLF:CANCEL":
        _clear_menu_create_wishlist_draft_context(context)
        await _safe_edit_or_send(update, "Criação de busca cancelada.")
        return ConversationHandler.END

    if data in {"CWL:AUCTIONS:YES", "CWL:AUCTIONS:NO"}:
        include_auctions = data.endswith(":YES")
        context.user_data["menu_create_wishlist_include_auctions"] = include_auctions
        return await _show_create_wishlist_summary_screen(update, context)

    if data == "CWL:CREATE":
        if context.user_data.get("menu_create_wishlist_creating") or context.user_data.get("menu_create_wishlist_completed"):
            await _safe_edit_or_send(update, "Essa busca já foi criada. Abra /menu para continuar.")
            return ConversationHandler.END
        query = context.user_data.get("menu_create_wishlist_query")
        if not query:
            await _safe_edit_or_send(update, "Essa etapa expirou.\n\nPara continuar com segurança, abra o menu novamente e refaça a ação.\n\nUse /menu.")
            return ConversationHandler.END
        draft_groups = context.user_data.get("menu_create_wishlist_draft_filters") or []
        include_auctions = bool(context.user_data.get("menu_create_wishlist_include_auctions", False))
        flat = [flt for g in draft_groups for flt in g.get("filters", [])]
        create_key = _build_wishlist_create_key(update.effective_chat.id, query, flat)
        if (
            context.user_data.get("menu_create_wishlist_creating")
            or context.user_data.get("menu_create_wishlist_completed")
            or context.user_data.get("menu_create_wishlist_last_create_key") == create_key
        ):
            await _safe_edit_or_send(update, "Essa busca já foi criada. Abra /menu para continuar.")
            return ConversationHandler.END
        context.user_data["menu_create_wishlist_creating"] = True
        context.user_data["menu_create_wishlist_last_create_key"] = create_key
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            try:
                if draft_groups:
                    create_result = create_wishlist_with_filters_and_initial_summary(
                        db, user.id, query, flat, include_auctions=include_auctions
                    )
                else:
                    create_result = add_wishlist_with_initial_summary(
                        db, user.id, query, include_auctions=include_auctions
                    )
            except Exception as exc:
                logger.exception(
                    "Unexpected error creating wishlist via CWL:CREATE",
                    extra={
                        "chat_id": update.effective_chat.id,
                        "query": query,
                        "draft_filters": draft_groups,
                        "create_key": create_key,
                        "exception_type": type(exc).__name__,
                        "callback_data": data,
                    },
                )
                context.user_data["menu_create_wishlist_creating"] = False
                context.user_data.pop("menu_create_wishlist_last_create_key", None)
                await _safe_edit_or_send(update, "Não consegui concluir essa ação agora. Tente novamente em instantes.")
                return MENU_CREATE_WISHLIST_QUERY
        if not create_result.ok:
            context.user_data["menu_create_wishlist_creating"] = False
            context.user_data.pop("menu_create_wishlist_last_create_key", None)
            await _safe_edit_or_send(update, create_result.message)
            return MENU_CREATE_WISHLIST_QUERY
        context.user_data["menu_create_wishlist_completed"] = True
        context.user_data["menu_create_wishlist_creating"] = False
        labels = [g.get("label") for g in draft_groups if g.get("label")]
        filters_text = "\n".join(f"- {label}" for label in labels) if labels else "- Sem filtros adicionais"
        service_feedback = _normalize_create_feedback(create_result.message)
        feedback_block = f"{service_feedback}\n\n" if service_feedback else ""
        initial_run_feedback = _render_initial_run_feedback(create_result.initial_run_summary)
        _clear_menu_create_wishlist_draft_context(context)
        await _safe_edit_or_send(
            update,
            (
                f"✅ Busca criada com sucesso.\n\n"
                f"Busca: {query}\n"
                f"Leilões: {_render_auctions_status(include_auctions)}\n"
                f"Filtros:\n{filters_text}\n\n"
                f"{feedback_block}"
                f"{initial_run_feedback}" + ("\n\nAtenção: em leilões, lance não é preço final. Confira edital, taxas, documentação e vistoria antes de participar." if include_auctions else "")
            ),
            reply_markup=_post_creation_markup(),
        )
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
        return await _show_create_wishlist_summary_screen(update, context)

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
        if context.user_data.get("menu_create_wishlist_creating") or context.user_data.get("menu_create_wishlist_completed"):
            await _safe_edit_or_send(update, "Essa busca já foi criada. Abra /menu para continuar.")
            return ConversationHandler.END
        query = context.user_data.get("menu_create_wishlist_query")
        draft_groups = context.user_data.get("menu_create_wishlist_draft_filters") or []
        include_auctions = bool(context.user_data.get("menu_create_wishlist_include_auctions", False))
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
        create_key = _build_wishlist_create_key(update.effective_chat.id, query, filters_draft)
        if (
            context.user_data.get("menu_create_wishlist_creating")
            or context.user_data.get("menu_create_wishlist_completed")
            or context.user_data.get("menu_create_wishlist_last_create_key") == create_key
        ):
            await _safe_edit_or_send(update, "Essa busca já foi criada. Abra /menu para continuar.")
            return ConversationHandler.END
        context.user_data["menu_create_wishlist_creating"] = True
        context.user_data["menu_create_wishlist_last_create_key"] = create_key
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            try:
                create_result = create_wishlist_with_filters_and_initial_summary(
                    db, user.id, query, filters_draft, include_auctions=include_auctions
                )
            except Exception:
                logger.exception(
                    "Unexpected error creating wishlist via CWLF:DONE",
                    extra={"chat_id": update.effective_chat.id, "query": query, "filters_draft": filters_draft, "callback_data": data},
                )
                context.user_data["menu_create_wishlist_creating"] = False
                context.user_data.pop("menu_create_wishlist_last_create_key", None)
                await _safe_edit_or_send(update, "Não consegui concluir essa ação agora. Tente novamente em instantes.")
                return MENU_CREATE_WISHLIST_QUERY
        if not create_result.ok:
            context.user_data["menu_create_wishlist_creating"] = False
            context.user_data.pop("menu_create_wishlist_last_create_key", None)
            await _safe_edit_or_send(update, create_result.message)
            return MENU_CREATE_WISHLIST_QUERY
        context.user_data["menu_create_wishlist_completed"] = True
        context.user_data["menu_create_wishlist_creating"] = False
        labels = "\n".join(f"- {g.get('label')}" for g in draft_groups if g.get("label")) or "- Sem filtros adicionais"
        initial_run_feedback = _render_initial_run_feedback(create_result.initial_run_summary)
        _clear_menu_create_wishlist_draft_context(context)
        await _safe_edit_or_send(
            update,
            f"✅ Busca criada com sucesso.\n\nBusca: {query}\nLeilões: {_render_auctions_status(include_auctions)}\nFiltros:\n{labels}\n\n{initial_run_feedback}",
            reply_markup=_post_creation_markup(),
        )
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


async def menu_upgrade_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_menu_create_wishlist_draft_context(context)
    _clear_menu_filter_context(context)
    from app.bot.handlers import cmd_upgrade
    await cmd_upgrade(update, context)
    return ConversationHandler.END


def menu_create_wishlist_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_menu, pattern=r"^MENU:CREATE_WISHLIST$")],
        states={
            MENU_CREATE_WISHLIST_QUERY: [
                CallbackQueryHandler(cb_menu_create_wishlist, pattern=r"^(CWL:(?:CREATE|CREATE_FILTERS|CANCEL|AUCTIONS:(?:YES|NO))|CWLF:(?:ACTION:(?:add|list)|TYPE:[a-z_]+|RM:\d+|DONE|CANCEL|BACK))$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_create_wishlist_on_text),
                MessageHandler(filters.COMMAND, menu_create_wishlist_cancel),
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", menu_create_wishlist_cancel),
            CommandHandler("cancel", menu_create_wishlist_cancel),
            CommandHandler("upgrade", menu_upgrade_fallback),
        ],
        name="menu_create_wishlist",
        persistent=False,
        per_chat=True,
        per_user=True,
        per_message=False,
    )


def menu_filter_conversation() -> ConversationHandler:
    return ConversationHandler(
        # Contrato: seleção da wishlist em "Ajustar filtros" entra nesta conversa
        # via WL:FILTERS:<idx>. MENU:FILTERS permanece por compatibilidade legada.
        entry_points=[
            CallbackQueryHandler(cb_menu, pattern=r"^WL:FILTERS:\d+$"),
            CallbackQueryHandler(cb_menu, pattern=r"^WL:FILTERS_ID:[^:]+$"),
            CallbackQueryHandler(cb_menu, pattern=r"^MENU:FILTERS$"),
        ],
        states={
            MENU_FILTER_SELECT_VALUE: [
                CallbackQueryHandler(
                    cb_menu,
                    pattern=r"^(WL:FILTER:AUCTIONS:TOGGLE|WL:AUCTIONS:(?:ENABLE|DISABLE)|WL:FILTERS_ID:[^:]+|WL:FILTERS_MENU|MENU:WISHLISTS)$",
                ),
                CallbackQueryHandler(cb_menu_filter, pattern=r"^FILTER:(WL:\d+|TYPE:[a-z_]+|ACTION:(?:add|list)|RM:[^:]+:\d+|BACK|CANCEL)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_filter_on_value),
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", menu_filter_cancel),
            CommandHandler("cancel", menu_filter_cancel),
            CommandHandler("upgrade", menu_upgrade_fallback),
            CallbackQueryHandler(cb_menu_filter, pattern=r"^FILTER:CANCEL$"),
        ],
        name="menu_filter_add",
        persistent=False,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
def _find_user_wishlist_by_id(wishlists: list, wishlist_id):
    for idx, wishlist in enumerate(wishlists, start=1):
        if str(getattr(wishlist, "id", "")) == str(wishlist_id):
            return idx, wishlist
    return None, None
def _render_auctions_status(include_auctions: bool) -> str:
    return "ativado" if bool(include_auctions) else "desativado"


def _build_filters_adjust_text(wl, filters) -> str:
    filters_block = "Filtros atuais:\n- Nenhum filtro ainda" if not filters else render_wishlist_filters(filters, wishlist_query=None)
    auctions_status = _render_auctions_status(getattr(wl, "include_auctions", False))
    return (
        "⚙️ Ajustar filtros\n\nVocê pode adicionar ou alterar filtros desta busca.\n\n"
        "Se já existir um filtro do mesmo tipo, ele será atualizado.\n\n"
        f"Busca: {wl.query}\n\n{filters_block}\n\nLeilões: {auctions_status}\n\nEscolha o que deseja ajustar:"
    )


def _build_filters_adjust_keyboard(wl) -> InlineKeyboardMarkup:
    auctions_label = f"⚠️ Leilões: {_render_auctions_status(getattr(wl, 'include_auctions', False))}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Preço / faixa", callback_data="FILTER:TYPE:price")],
        [InlineKeyboardButton("📅 Ano", callback_data="FILTER:TYPE:year")],
        [InlineKeyboardButton("🛣️ KM", callback_data="FILTER:TYPE:mileage")],
        [InlineKeyboardButton("📍 Cidade", callback_data="FILTER:TYPE:city")],
        [InlineKeyboardButton("🗺️ Estado", callback_data="FILTER:TYPE:state")],
        [InlineKeyboardButton(auctions_label, callback_data="WL:FILTER:AUCTIONS:TOGGLE")],
        [InlineKeyboardButton("↩️ Voltar", callback_data="MENU:WISHLISTS")],
    ])
