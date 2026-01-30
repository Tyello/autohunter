from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import (
    list_wishlists,
    add_wishlist,
    remove_wishlist,
    add_filter,
    list_filters,
    remove_filter,
    get_max_wishlists_for_user,
)


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
            await update.message.reply_text("Você não tem wishlists. Use /wishlist_add.")
            return

        if context.args and str(context.args[0]).isdigit():
            n = int(context.args[0])
            _ok, msg = remove_wishlist(db, user.id, n)
            await update.message.reply_text(msg)
            return

    lines = [f"{i+1}. {w.query}" for i, w in enumerate(wishlists)]
    sug = "\n".join([f"/wishlist_remove {i+1}" for i in range(min(len(wishlists), 9))])

    await update.message.reply_text(
        "🗑️ Remover wishlist\n\n"
        "Escolha o número e envie um dos comandos abaixo:\n\n"
        + sug
        + "\n\nWishlists atuais:\n"
        + "\n".join(lines)
    )


async def cmd_wishlist_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sim, limpar", callback_data="W:CLEAR:YES"),
            InlineKeyboardButton("❌ Cancelar", callback_data="W:CLEAR:NO"),
        ]
    ])
    await update.message.reply_text(
        "⚠️ Tem certeza que deseja remover TODAS as wishlists?",
        reply_markup=kb,
    )


async def cb_wishlist_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "W:CLEAR:NO":
        await q.edit_message_text("Cancelado.")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        for w in wishlists:
            db.delete(w)
        db.commit()

    await q.edit_message_text("🔥 Todas as wishlists foram removidas.")


# ---------- Wishlist Add (wizard) ----------

WADD_QUERY = 1


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
            await update.message.reply_text(
                f"Limite atingido: {max_w} wishlists no seu plano. Use /wishlist_remove."
            )
            return ConversationHandler.END

    context.user_data.pop("wadd_query", None)
    await update.message.reply_text(
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
        await update.message.reply_text("Texto muito curto. Ex: civic si")
        return WADD_QUERY

    context.user_data["wadd_query"] = query

    await update.message.reply_text(
        "Confirma criar esta wishlist?\n\n"
        f"🔎 {query}",
        reply_markup=_confirm_kb(),
    )
    return ConversationHandler.END


async def cb_wishlist_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

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
    await update.message.reply_text("Cancelado.")
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
    if not context.args or not str(context.args[0]).isdigit():
        await update.message.reply_text("Use: /wishlist_filter_list <n>")
        return
    n = int(context.args[0])

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if n < 1 or n > len(wishlists):
            await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
            return

        wl = wishlists[n - 1]
        fs = list_filters(db, wl.id)

    if not fs:
        await update.message.reply_text("(sem filtros)\nDica: /wishlist_filter_add <n> year lte 2005")
        return

    lines = [f"{i+1}. {f.field} {f.operator} {f.value}" for i, f in enumerate(fs)]
    await update.message.reply_text(
        "Filtros da wishlist:\n"
        f"🔎 {wl.query}\n\n"
        + "\n".join(lines)
    )


async def cmd_wishlist_filter_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_filter_add <n> <field> <op> <value>"""
    if len(context.args or []) < 4:
        await update.message.reply_text(
            "Use: /wishlist_filter_add <n> <campo> <op> <valor>\n"
            "Ex: /wishlist_filter_add 1 year lte 2005"
        )
        return

    n_s, field, op = context.args[0], context.args[1], context.args[2]
    value = " ".join(context.args[3:])

    if not str(n_s).isdigit():
        await update.message.reply_text("Primeiro argumento deve ser o número da wishlist.")
        return
    n = int(n_s)

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if n < 1 or n > len(wishlists):
            await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
            return

        wl = wishlists[n - 1]
        _ok, msg = add_filter(db, wl.id, field, op, value)

    await update.message.reply_text(msg)


async def cmd_wishlist_filter_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use: /wishlist_filter_remove <n> <k>"""
    if len(context.args or []) < 2:
        await update.message.reply_text("Use: /wishlist_filter_remove <n> <k>")
        return

    if (not str(context.args[0]).isdigit()) or (not str(context.args[1]).isdigit()):
        await update.message.reply_text("Use: /wishlist_filter_remove <n> <k>")
        return

    n = int(context.args[0])
    k = int(context.args[1])

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        if n < 1 or n > len(wishlists):
            await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
            return

        wl = wishlists[n - 1]
        _ok, msg = remove_filter(db, wl.id, k)

    await update.message.reply_text(msg)
