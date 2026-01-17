from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists, MAX_WISHLISTS_PER_USER


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Comandos do AutoHunter\n\n"
        "Wishlist:\n"
        "• /wishlist — listar\n"
        "• /wishlist_add — criar (assistente)\n"
        "• /wishlist_remove — remover\n"
        "• /wishlist_clear — limpar tudo\n\n"
        "Busca manual:\n"
        "• /buscar civic 2019 até 90000 sp\n\n"
        "Alertas:\n"
        "• /alertas\n\n"
        "Planos:\n"
        "• /plan\n" 
        "• /upgrade\n\n"       
        "Sistema:\n"
        "• /status\n"
        "• /version\n"
        "• /me"
    )


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Se você já tem versionamento via env/commit, substitua aqui.
    await update.message.reply_text("🤖 AutoHunter (bot) — appv4")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        w = list_wishlists(db, user.id)

    await update.message.reply_text(
        "📊 Status\n\n"
        f"Wishlists: {len(w)}/{MAX_WISHLISTS_PER_USER}\n"
        "Alertas/dia: 10\n"
        "Monitoramento: ML/OLX (scheduler)\n\n"
        "Use /wishlist para ver suas buscas monitoradas."
    )
