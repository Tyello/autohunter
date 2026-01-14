import logging

from telegram.ext import Application, CommandHandler

from app.core.settings import settings
from app.bot.handlers import cmd_buscar, cmd_wishlist, cmd_alertas
from app.bot.handlers_debug import cmd_debug

logger = logging.getLogger(__name__)


def main():
    token = getattr(settings, "telegram_bot_token", None)
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado no .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("wishlist", cmd_wishlist))
    app.add_handler(CommandHandler("alertas", cmd_alertas))

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
