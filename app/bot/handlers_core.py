from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists, get_user_plan_snapshot


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Comandos do AutoHunter\n\n"
        "Wishlist:\n"
        "• /wishlist — listar\n"
        "• /wishlist_add — criar (assistente)\n"
        "• /wishlist_remove — remover\n"
        "• /wishlist_clear — limpar tudo\n\n"
        "Filtros (por wishlist):\n"
        "• /wishlist_filter_list <n>\n"
        "• /wishlist_filter_add <n> <campo> <op> <valor>\n"
        "• /wishlist_filter_remove <n> <k>\n\n"
        "Campos: price | year | source\n"
        "Ops price/year: lt lte gt gte eq neq\n"
        "Ops source: eq neq\n"
        "Exemplos:\n"
        "• /wishlist_filter_add 1 year lte 2005\n"
        "• /wishlist_filter_add 1 price lte 90000\n"
        "• /wishlist_filter_add 1 source eq olx\n\n"
        "Dica (atalho no /wishlist_add):\n"
        "• \"daihatsu cuore até 2005\" (cria filtro year lte 2005 automaticamente)\n\n"
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
    await update.message.reply_text("🤖 AutoHunter (bot) — appv4")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        w = list_wishlists(db, user.id)
        snap = get_user_plan_snapshot(db, user.id)

    max_w = snap.get("max_wishlists")
    dal = snap.get("daily_alert_limit")
    plan_code = snap.get("plan_code") or "free"

    dal_txt = str(dal) if dal is not None else "—"

    await update.message.reply_text(
        "📊 Status\n\n"
        f"Plano: {plan_code}\n"
        f"Wishlists: {len(w)}/{max_w}\n"
        f"Alertas/dia: {dal_txt}\n"
        "Monitoramento: fontes via scheduler\n\n"
        "Use /wishlist para ver suas buscas monitoradas."
    )
