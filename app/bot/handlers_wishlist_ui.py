# app/bot/handlers_wishlist_ui.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import (
    list_wishlists,
    add_wishlist,
    remove_wishlist,
    MAX_WISHLISTS_PER_USER,
)


# ---------- Wishlist Remove / Clear (UX simples e previsível) ----------

async def cmd_wishlist_remove2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Novo comando: /wishlist_remove [n]

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
            ok, msg = remove_wishlist(db, user.id, n)
            await update.message.reply_text(msg)
            return

    # sem args: guia
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

    # YES
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        wishlists = list_wishlists(db, user.id)
        for w in wishlists:
            db.delete(w)
        db.commit()

    await q.edit_message_text("🔥 Todas as wishlists foram removidas.")


# ---------- Wishlist Add (wizard compatível com schema atual: só query) ----------

WADD_QUERY = 1
WADD_CONFIRM = 2


def _confirm_kb():
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
        if len(wishlists) >= MAX_WISHLISTS_PER_USER:
            await update.message.reply_text(
                f"Limite atingido: {MAX_WISHLISTS_PER_USER} wishlists por usuário. Use /wishlist_remove."
            )
            return ConversationHandler.END

    context.user_data.pop("wadd_query", None)
    await update.message.reply_text("Digite os termos da wishlist. Ex: civic g10 2019")
    return WADD_QUERY


async def cmd_wishlist_add_on_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if len(query) < 3:
        await update.message.reply_text("Texto muito curto. Ex: civic g10 2019")
        return WADD_QUERY

    await update.message.reply_text(
        "Confirma criar esta wishlist?\n\n"
        f"🔎 {query}",
        reply_markup=_confirm_kb(query),
    )
    # ✅ encerra Conversation aqui
    return ConversationHandler.END


async def cmd_wishlist_add_on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "W:ADD:CANCEL":
        context.user_data.pop("wadd_query", None)
        await q.edit_message_text("Cancelado. Use /wishlist_add quando quiser.")
        return ConversationHandler.END

    query = context.user_data.get("wadd_query")
    if not query:
        await q.edit_message_text("Sessão expirada. Use /wishlist_add novamente.")
        return ConversationHandler.END

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        ok, msg = add_wishlist(db, user.id, query)

    context.user_data.pop("wadd_query", None)
    await q.edit_message_text(msg + "\nUse /wishlist para listar.")
    return ConversationHandler.END


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



async def cb_wishlist_add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data  # W:ADD:SAVE:<query>  ou W:ADD:CANCEL
    if data == "W:ADD:CANCEL":
        await q.edit_message_text("Cancelado. Use /wishlist_add quando quiser.")
        return

    # SAVE
    # parse: W:ADD:SAVE:<query>
    parts = data.split(":", 3)
    if len(parts) != 4:
        await q.edit_message_text("Callback inválido. Use /wishlist_add novamente.")
        return

    query = parts[3].strip()
    if not query:
        await q.edit_message_text("Sessão expirada. Use /wishlist_add novamente.")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        ok, msg = add_wishlist(db, user.id, query)

    await q.edit_message_text(msg + "\nUse /wishlist para listar.")
