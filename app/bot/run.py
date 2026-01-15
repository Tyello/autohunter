import logging

from telegram import Update
from telegram.ext import ContextTypes, Application, CommandHandler

from app.core.settings import settings
from app.bot.handlers import cmd_buscar, cmd_wishlist, cmd_alertas
from app.bot.handlers_debug import cmd_debug
from app.bot.handlers_misc import cmd_me

logger = logging.getLogger(__name__)

async def on_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Bot error", exc_info=context.error)

    # tenta responder no chat
    try:
        if update and getattr(update, "message", None):
            await update.message.reply_text(f"Erro: {type(context.error).__name__}: {context.error}")
    except Exception:
        pass

def main():
    token = getattr(settings, "telegram_bot_token", None)
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado no .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("wishlist", cmd_wishlist))
    app.add_handler(CommandHandler("alertas", cmd_alertas))
    app.add_handler(CommandHandler("me", cmd_me))

    app.add_error_handler(on_error)

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
