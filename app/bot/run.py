import logging

from telegram import Update
from telegram.ext import ContextTypes, Application, CommandHandler, CallbackQueryHandler

from app.core.settings import settings

from app.bot.commands import setup_bot_commands
from app.bot.handlers_core import cmd_help, cmd_status, cmd_version
from app.bot.handlers import cmd_buscar, cmd_wishlist, cmd_alertas, cmd_plan, cmd_upgrade, cmd_setplan, cmd_setlimit
from app.bot.handlers_debug import cmd_debug
from app.bot.handlers_admin import cmd_admin
from app.bot.handlers_misc import cmd_me
from app.bot.handlers_wishlist_ui import (
    wishlist_add_conversation,
    cb_wishlist_add_confirm,
    cb_wishlist_clear,
    cmd_wishlist_filter_add,
    cmd_wishlist_filter_list,
    cmd_wishlist_filter_remove,
    cmd_wishlist_clear,
    cmd_wishlist_remove,
)
logger = logging.getLogger(__name__)


async def _post_init(application: Application):
    await setup_bot_commands(application.bot)


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

    app = Application.builder().token(token).post_init(_post_init).build()

    # core
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("version", cmd_version))

    # search + wishlist (modo antigo continua)
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("wishlist", cmd_wishlist))

    # wishlist (UX nova)
    app.add_handler(wishlist_add_conversation())
    app.add_handler(CallbackQueryHandler(cb_wishlist_add_confirm, pattern=r"^W:ADD:(SAVE|CANCEL)$"))
    app.add_handler(CallbackQueryHandler(cb_wishlist_clear, pattern=r"^W:CLEAR:(YES|NO)$"))

    app.add_handler(CommandHandler("wishlist_filter_add", cmd_wishlist_filter_add))
    app.add_handler(CommandHandler("wishlist_filter_list", cmd_wishlist_filter_list))
    app.add_handler(CommandHandler("wishlist_filter_remove", cmd_wishlist_filter_remove))

    app.add_handler(CommandHandler("wishlist_clear", cmd_wishlist_clear))
    app.add_handler(CommandHandler("wishlist_remove", cmd_wishlist_remove))

    # plan
    app.add_handler(CommandHandler("alertas", cmd_alertas))
    app.add_handler(CommandHandler("me", cmd_me))

    # misc
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CommandHandler("setplan", cmd_setplan))
    app.add_handler(CommandHandler("setlimit", cmd_setlimit))

    app.add_error_handler(on_error)

    # IMPORTANTE: agora precisa de callback_query por causa dos botões
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
