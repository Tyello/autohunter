from __future__ import annotations

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.db.session import SessionLocal
from app.bot.utils import normalize_args, parse_int, reply_text
from app.bot.renderers import render_all_tracked_listings
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import (
    list_wishlists,
    add_wishlist,
    remove_wishlist,
    remove_all_wishlists,
    add_filter,
    list_filters,
    remove_filter,
    get_max_wishlists_for_user,
)
from app.services.wishlist_tracking_service import (
    add_tracked_listing,
    add_tracked_listing_result,
    TrackedListingResult,
    list_tracked_listings,
    remove_tracked_listing,
    set_price_drop_alert_enabled,
    user_has_tracking_automation,
)
from app.models.notification import Notification
from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing

logger = logging.getLogger(__name__)


# ---------- Wishlist Remove / Clear (UX simples e previsível) ----------

async def cmd_wishlist_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando: /wishlist_remove [n]

    - sem n: lista e sugere comandos removíveis
    - com n: remove o item n
    """
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)

        if not wishlists:
            await reply_text(update, "Você não tem wishlists. Use /wishlist_add.")
            return

        args = normalize_args(context.args)
        n = parse_int(args[0]) if args else None
        if n is not None:
            _ok, msg = remove_wishlist(db, user.id, n)
            await reply_text(update, msg)
            return

    lines = [f"{i+1}. {w.query}" for i, w in enumerate(wishlists)]
    sug = "\n".join([f"/wishlist_remove {i+1}" for i in range(min(len(wishlists), 9))])

    await reply_text(
        update,
        "🗑️ Remover wishlist\n\n"
        "Escolha o número e envie um dos comandos abaixo:\n\n"
        + sug
        + "\n\nWishlists atuais:\n"
        + "\n".join(lines)
    )


async def cmd_wishlist_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["wishlist_clear_armed"] = True
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sim, limpar", callback_data="W:CLEAR:YES"),
            InlineKeyboardButton("❌ Cancelar", callback_data="W:CLEAR:NO"),
        ]
    ])
    await reply_text(
        update,
        "⚠️ Tem certeza que deseja remover TODAS as wishlists?",
        reply_markup=kb,
    )


async def cb_wishlist_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)

    if q.data == "W:CLEAR:NO":
        context.user_data.pop("wishlist_clear_armed", None)
        await q.edit_message_text("Cancelado.")
        return

    if not bool(context.user_data.pop("wishlist_clear_armed", False)):
        await q.edit_message_text("Confirmação expirada. Use /wishlist_clear novamente.")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        ok, msg = remove_all_wishlists(db, user.id)

    await q.edit_message_text("🔥 Todas as wishlists foram removidas." if ok else f"⚠️ {msg}")


# ---------- Wishlist Add (wizard) ----------

WADD_QUERY = 1


async def _safe_answer_callback(q) -> None:
    try:
        await q.answer()
    except BadRequest as exc:
        msg = str(exc).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            return
        raise


def _confirm_kb() -> InlineKeyboardMarkup:
    # callback_data pequeno (Telegram limita ~64 bytes)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Salvar", callback_data="W:ADD:SAVE"),
            InlineKeyboardButton("❌ Cancelar", callback_data="W:ADD:CANCEL"),
        ]
    ])


async def cmd_wishlist_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        max_w = get_max_wishlists_for_user(db, user.id)

        if len(wishlists) >= max_w:
            await reply_text(
                update,
                f"Limite atingido: {max_w} wishlists no seu plano. Use /wishlist_remove."
            )
            return ConversationHandler.END

    context.user_data.pop("wadd_query", None)
    await reply_text(
        update,
        "Digite os termos da wishlist.\n"
        "Ex: civic si\n\n"
        "Dica: você pode incluir diretivas que viram filtros automáticos (ano e preço).\n"
        "Exemplos (ano):\n"
        "• audi a6 entre 2014 e 2020\n"
        "• civic a partir de 1993\n"
        "• daihatsu cuore até 2005\n\n"
        "Exemplos (preço - BRL):\n"
        "• audi a6 entre 200k e 300k\n"
        "• civic até 90k\n"
        "• preço>=80k\n\n"
        "Dica: /wishlist help mostra todas as opções"
    )
    return WADD_QUERY


async def cmd_wishlist_add_on_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if len(query) < 3:
        await reply_text(update, "Texto muito curto. Ex: civic si")
        return WADD_QUERY

    context.user_data["wadd_query"] = query

    await reply_text(
        update,
        "Confirma criar esta wishlist?\n\n"
        f"🔎 {query}",
        reply_markup=_confirm_kb(),
    )
    return ConversationHandler.END


async def cb_wishlist_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await _safe_answer_callback(q)

    if q.data == "W:ADD:CANCEL":
        context.user_data.pop("wadd_query", None)
        await q.edit_message_text("Cancelado. Use /wishlist_add quando quiser.")
        return

    if q.data != "W:ADD:SAVE":
        await q.edit_message_text("Callback inválido. Use /wishlist_add novamente.")
        return

    query = (context.user_data.get("wadd_query") or "").strip()
    if not query:
        await q.edit_message_text("Sessão expirada. Use /wishlist_add novamente.")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        _ok, msg = add_wishlist(db, user.id, query)

    context.user_data.pop("wadd_query", None)
    await q.edit_message_text(msg + "\nUse /wishlist para listar.")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("wadd_query", None)
    await reply_text(update, "Cancelado.")
    return ConversationHandler.END


def wishlist_add_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("wishlist_add", cmd_wishlist_add_start)],
        states={
            WADD_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_wishlist_add_on_query)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        name="wishlist_add",
        persistent=False,
        per_chat=True,
        per_user=True,
        per_message=False,
    )


# ---------- Filtros (comandos diretos, simples) ----------

async def cmd_wishlist_filter_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_filter_list <n>"""
    args = normalize_args(context.args)
    n = parse_int(args[0]) if args else None
    if n is None:
        await reply_text(update, "Use: /wishlist_filter_list <n>")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if n < 1 or n > len(wishlists):
            await reply_text(update, "Wishlist inválida. Use /wishlist listar.")
            return

        wl = wishlists[n - 1]
        fs = list_filters(db, wl.id)

    if not fs:
        await reply_text(update, "(sem filtros)\nDica: /wishlist_filter_add <n> year lte 2005")
        return

    def _fmt_filter(f) -> str:
        if f.field == "mileage_km":
            if f.operator == "lte":
                return f"Quilometragem até {int(f.value):,} km".replace(",", ".")
            if f.operator == "gte":
                return f"Quilometragem a partir de {int(f.value):,} km".replace(",", ".")
            if f.operator == "between":
                lo_s, hi_s = [p.strip() for p in f.value.split(",", 1)]
                lo = f"{int(lo_s):,}".replace(",", ".")
                hi = f"{int(hi_s):,}".replace(",", ".")
                return f"Quilometragem entre {lo} e {hi} km"
        if f.field == "seller_type":
            label = {"private": "particular", "dealer": "loja/revenda"}.get((f.value or "").lower(), f.value)
            if f.operator == "eq":
                return f"Vendedor: {label}"
            if f.operator == "neq":
                return f"Excluir vendedor: {label}"
        if f.field == "body_type":
            label = {
                "suv": "SUV",
                "convertible": "conversível",
            }.get((f.value or "").lower(), f.value)
            if f.operator == "eq":
                return f"Carroceria: {label}"
            if f.operator == "neq":
                return f"Excluir carroceria: {label}"
        if f.field == "doors":
            if f.operator == "eq":
                return f"Portas: {int(f.value)}"
            if f.operator == "neq":
                return f"Excluir portas: {int(f.value)}"
            if f.operator == "lte":
                return f"Portas até {int(f.value)}"
            if f.operator == "gte":
                return f"Portas a partir de {int(f.value)}"
            if f.operator == "between":
                lo_s, hi_s = [p.strip() for p in f.value.split(",", 1)]
                return f"Portas entre {int(lo_s)} e {int(hi_s)}"
        return f"{f.field} {f.operator} {f.value}"

    lines = [f"{i+1}. {_fmt_filter(f)}" for i, f in enumerate(fs)]
    await reply_text(
        update,
        "Filtros da wishlist:\n"
        f"🔎 {wl.query}\n\n"
        + "\n".join(lines)
    )


async def cmd_wishlist_filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_filter_add <n> <field> <op> <value>"""
    if len(context.args or []) < 4:
        await reply_text(
            update,
            "Use: /wishlist_filter_add <n> <campo> <op> <valor>\n"
            "Ex: /wishlist_filter_add 1 year lte 2005\n"
            "Ex: /wishlist_filter_add 1 city eq Sao Paulo"
        )
        return

    n_s, field, op = context.args[0], context.args[1], context.args[2]
    value = " ".join(context.args[3:])

    n = parse_int(n_s)
    if n is None:
        await reply_text(update, "Primeiro argumento deve ser o número da wishlist.")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if n < 1 or n > len(wishlists):
            await reply_text(update, "Wishlist inválida. Use /wishlist listar.")
            return

        wl = wishlists[n - 1]
        _ok, msg = add_filter(db, wl.id, field, op, value)

    await reply_text(update, msg)


async def cmd_wishlist_filter_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_filter_remove <n> <k>"""
    if len(context.args or []) < 2:
        await reply_text(update, "Use: /wishlist_filter_remove <n> <k>")
        return

    n = parse_int(context.args[0])
    k = parse_int(context.args[1])
    if n is None or k is None:
        await reply_text(update, "Use: /wishlist_filter_remove <n> <k>")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if n < 1 or n > len(wishlists):
            await reply_text(update, "Wishlist inválida. Use /wishlist listar.")
            return

        wl = wishlists[n - 1]
        _ok, msg = remove_filter(db, wl.id, k)

    await reply_text(update, msg)


# ---------- Tracking de anúncios por wishlist ----------

async def cmd_wishlist_track_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_track_add <n> <url|external_id>"""
    if len(context.args or []) < 2:
        await reply_text(update, "Use: /wishlist_track_add <n> <url|external_id>")
        return

    n = parse_int(context.args[0])
    if n is None:
        await reply_text(update, "Wishlist inválida. Use /wishlist.")
        return

    listing_ref = " ".join(context.args[1:]).strip()

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        result = add_tracked_listing_result(db, user_id=user.id, wishlist_index=n, listing_ref=listing_ref)

    await reply_text(update, result.message)


async def cmd_wishlist_track_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_track_list [n]"""
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)

        if len(context.args or []) < 1:
            tracked_messages = []
            for i, _wl in enumerate(wishlists, start=1):
                _ok, msg = list_tracked_listings(db, user_id=user.id, wishlist_index=i)
                tracked_messages.append(msg)
            await reply_text(update, render_all_tracked_listings(wishlists, tracked_messages)[:3900])
            return

        n = parse_int(context.args[0])
        if n is None:
            await reply_text(update, "Wishlist inválida. Use /wishlist.")
            return

        _ok, msg = list_tracked_listings(db, user_id=user.id, wishlist_index=n)

    await reply_text(update, msg)


async def cmd_wishlist_track_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_track_remove <n> <slot>"""
    if len(context.args or []) < 2:
        await reply_text(update, "Use: /wishlist_track_remove <n> <slot>")
        return

    n = parse_int(context.args[0])
    slot = parse_int(context.args[1])
    if n is None or slot is None:
        await reply_text(update, "Use: /wishlist_track_remove <n> <slot>")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        _ok, msg = remove_tracked_listing(db, user_id=user.id, wishlist_index=n, slot=slot)

    await reply_text(update, msg)


async def cmd_wishlist_track_alert_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 2:
        await reply_text(update, "Use: /wishlist_track_alert_on <n> <slot>")
        return
    n = parse_int(context.args[0])
    slot = parse_int(context.args[1])
    if n is None or slot is None:
        await reply_text(update, "Use: /wishlist_track_alert_on <n> <slot>")
        return
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        if not user_has_tracking_automation(db, user_id=user.id):
            await reply_text(update, "Notificações automáticas de mudança são um recurso Premium.")
            return
        _ok, msg = set_price_drop_alert_enabled(db, user_id=user.id, wishlist_index=n, slot=slot, enabled=True)
    await reply_text(update, msg)


async def cmd_wishlist_track_alert_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args or []) < 2:
        await reply_text(update, "Use: /wishlist_track_alert_off <n> <slot>")
        return
    n = parse_int(context.args[0])
    slot = parse_int(context.args[1])
    if n is None or slot is None:
        await reply_text(update, "Use: /wishlist_track_alert_off <n> <slot>")
        return
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        _ok, msg = set_price_drop_alert_enabled(db, user_id=user.id, wishlist_index=n, slot=slot, enabled=False)
    await reply_text(update, msg)


def _extract_slot_from_message(msg: str) -> int | None:
    import re

    m = re.search(r"slot\s+(\d+)", str(msg or ""), flags=re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


async def _safe_edit_message_text(q, text: str) -> None:
    try:
        await q.edit_message_text(text)
    except BadRequest:
        return


async def cb_track_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    await _safe_answer_callback(q)
    logger.info("track_callback_received data=%s", data)

    short_msg = ""
    full_msg = ""
    try:
        with SessionLocal() as db:
            user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
            wishlists = list_wishlists(db, user.id)
            wishlist_idx_by_id = {str(w.id): i + 1 for i, w in enumerate(wishlists)}

            if data.startswith("TRACK:ADD:"):
                notification_id = data.split(":", 2)[2]
                n = db.query(Notification).filter(Notification.id == notification_id).first()
                if not n or not n.wishlist_id:
                    short_msg, full_msg = "Notificação inválida", "Não encontrei essa notificação. Tente rastrear a partir de uma notificação mais recente."
                else:
                    wl = db.query(Wishlist).filter(Wishlist.id == n.wishlist_id).first()
                    if not wl or wl.user_id != user.id:
                        short_msg, full_msg = "Sem permissão", "Wishlist não encontrada para sua conta."
                    else:
                        listing = db.query(CarListing).filter(CarListing.id == n.car_listing_id).first()
                        listing_ref = (listing.external_id or listing.url) if listing else None
                        widx = wishlist_idx_by_id.get(str(wl.id))
                        if not listing_ref:
                            short_msg, full_msg = "Anúncio indisponível", "Não consegui rastrear esse anúncio porque ele não está mais disponível."
                        elif widx is None:
                            short_msg, full_msg = "Wishlist inválida", "Wishlist não encontrada para sua conta."
                        else:
                            result = add_tracked_listing_result(db, user_id=user.id, wishlist_index=widx, listing_ref=listing_ref)
                            short_msg, full_msg = _format_track_result_message(result, str(getattr(wl, "query", "") or "wishlist"))
            elif data.startswith("TRACK:CHOOSE:"):
                listing_id = data.split(":", 2)[2].strip()
                if not listing_id:
                    short_msg, full_msg = "Inválido", "Não consegui rastrear agora. Tente novamente."
                elif not wishlists:
                    short_msg, full_msg = "Sem wishlist", "Você não tem wishlists. Use /wishlist_add para criar a primeira."
                else:
                    lines = ["Escolha uma wishlist para rastrear este anúncio:"]
                    for i, _wl in enumerate(wishlists[:3], start=1):
                        lines.append(f"/wishlist_track_add {i} {listing_id}")
                    if len(wishlists) > 3:
                        lines.append("Dica: use /wishlist para ver todos os índices disponíveis.")
                    short_msg, full_msg = "Escolha wishlist", "\n".join(lines)
            elif data.startswith("TRACK:ADDT:"):
                from app.services.tracking_callback_token_service import resolve_tracking_callback_token

                token = data.split(":", 2)[2].strip()
                payload, err = resolve_tracking_callback_token(token)
                if err == "expired":
                    short_msg, full_msg = "Expirado", "Essa ação expirou. Abra /buscar novamente e toque em ⭐ Rastrear."
                elif err or not payload:
                    short_msg, full_msg = "Inválido", "Não encontrei essa ação para sua conta. Tente novamente no /buscar."
                elif str(payload.get("u")) != str(user.id):
                    short_msg, full_msg = "Sem permissão", "Não encontrei essa ação para sua conta."
                else:
                    wishlist_id = str(payload.get("w") or "")
                    listing_id = str(payload.get("l") or "")
                    wl = db.query(Wishlist).filter(Wishlist.id == wishlist_id).first()
                    if not wl or wl.user_id != user.id:
                        short_msg, full_msg = "Sem permissão", "Wishlist não encontrada para sua conta."
                    else:
                        listing = db.query(CarListing).filter(CarListing.id == listing_id).first()
                        listing_ref = (listing.external_id or listing.url) if listing else None
                        widx = wishlist_idx_by_id.get(wishlist_id)
                        if not listing_ref:
                            short_msg, full_msg = "Anúncio indisponível", "Não consegui rastrear esse anúncio porque ele não está mais disponível."
                        elif widx is None:
                            short_msg, full_msg = "Wishlist inválida", "Wishlist não encontrada para sua conta."
                        else:
                            result = add_tracked_listing_result(db, user_id=user.id, wishlist_index=widx, listing_ref=listing_ref)
                            short_msg, full_msg = _format_track_result_message(result, str(getattr(wl, "query", "") or "wishlist"))
            elif data.startswith("TRACK:ADDWL:"):
                parts = data.split(":")
                if len(parts) != 4:
                    short_msg, full_msg = "Inválido", "Não consegui rastrear agora. Tente novamente."
                else:
                    wishlist_id, listing_id = parts[2], parts[3]
                    wl = db.query(Wishlist).filter(Wishlist.id == wishlist_id).first()
                    if not wl or wl.user_id != user.id:
                        short_msg, full_msg = "Sem permissão", "Wishlist não encontrada para sua conta."
                    else:
                        listing = db.query(CarListing).filter(CarListing.id == listing_id).first()
                        listing_ref = (listing.external_id or listing.url) if listing else None
                        widx = wishlist_idx_by_id.get(str(wishlist_id))
                        if not listing_ref:
                            short_msg, full_msg = "Anúncio indisponível", "Não consegui rastrear esse anúncio porque ele não está mais disponível."
                        elif widx is None:
                            short_msg, full_msg = "Wishlist inválida", "Wishlist não encontrada para sua conta."
                        else:
                            result = add_tracked_listing_result(db, user_id=user.id, wishlist_index=widx, listing_ref=listing_ref)
                            short_msg, full_msg = _format_track_result_message(result, str(getattr(wl, "query", "") or "wishlist"))
            else:
                short_msg, full_msg = "Inválido", "Não consegui rastrear agora. Tente novamente."
    except Exception as exc:
        logger.exception("track_callback_failed data=%s err=%s", data, type(exc).__name__)
        short_msg, full_msg = "Erro", "Não consegui rastrear agora. Tente novamente."

    try:
        await q.answer(short_msg[:180] or "OK", show_alert=False)
    except BadRequest:
        pass
    bot = getattr(context, "bot", None)
    if bot is not None:
        try:
            await bot.send_message(chat_id=update.effective_chat.id, text=full_msg)
        except Exception:
            logger.warning("track_callback_visible_confirmation_failed", exc_info=True)
    await _safe_edit_message_text(q, full_msg)


def _format_track_result_message(result: TrackedListingResult, wishlist_name: str) -> tuple[str, str]:
    slot = result.slot or 1
    wl_label = (wishlist_name or "wishlist").strip() or "wishlist"
    if result.status == "added":
        if bool(result.automation_enabled):
            return f"Rastreado no slot {slot}", f"✅ Anúncio rastreado no slot {slot} da wishlist {wl_label}.\n\nVou acompanhar preço e status automaticamente.\nVeja seus rastreados:\n/wishlist_track_list"
        return f"Rastreado no slot {slot}", f"✅ Anúncio rastreado no slot {slot} da wishlist {wl_label}.\n\nVocê pode acompanhar preço e status em:\n/wishlist_track_list\n\nNotificações automáticas são Premium."

    if result.status == "already_tracked":
        return "Já rastreado", f"Esse anúncio já está rastreado no slot {slot} da wishlist {wl_label}.\n\nVeja em:\n/wishlist_track_list"
    if result.status == "slots_full":
        return "Slots cheios", f"Você já usa todos os slots da wishlist {wl_label}.\n\nVeja e remova algum slot em:\n/wishlist_track_list"
    if result.status in {"listing_not_found", "unavailable"}:
        return "Anúncio indisponível", "Não consegui rastrear esse anúncio porque ele não está mais disponível."
    if result.status in {"wishlist_not_found", "invalid_slot"}:
        return "Wishlist inválida", "Wishlist não encontrada para sua conta."
    return "Erro", "Não consegui rastrear agora. Tente novamente."
