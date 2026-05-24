import logging
import asyncio

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import ContextTypes, Application, CommandHandler, CallbackQueryHandler

from app.core.settings import settings

from app.bot.commands import setup_bot_commands
from app.bot.handlers_core import (
    cmd_help, cmd_start, cmd_status, cmd_version, cmd_wishlist_help, cmd_menu, cb_menu, cmd_digest,
    menu_create_wishlist_conversation, menu_filter_conversation, cb_session_guard,
)
from app.bot.handlers import cmd_buscar, cmd_wishlist, cmd_alertas, cmd_plan, cmd_upgrade, cmd_setplan, cmd_setlimit, cb_upgrade_plan_choice, quick_search_conversation
from app.bot.handlers_debug import cmd_debug
from app.bot.handlers_admin import cmd_admin
from app.bot.handlers_misc import cmd_me
from app.bot.handlers_fb_agent import cmd_fb
from app.bot.handlers_wishlist_ui import (
    wishlist_add_conversation,
    cb_wishlist_add_confirm,
    cb_wishlist_clear,
    cmd_wishlist_filter_add,
    cmd_wishlist_filter_list,
    cmd_wishlist_filter_remove,
    cmd_wishlist_clear,
    cmd_wishlist_remove,
    cmd_wishlist_track_add,
    cmd_wishlist_track_alert_off,
    cmd_wishlist_track_alert_on,
    cmd_wishlist_track_list,
    cmd_wishlist_track_remove,
    cb_track_add,
)
logger = logging.getLogger(__name__)


async def _post_init(application: Application):
    try:
        await setup_bot_commands(application.bot)
    except (TimedOut, NetworkError):
        logger.warning("telegram command registration skipped due to network timeout", exc_info=True)

    # Ensure queued notifications are delivered even when APScheduler isn't running
    # (common in Windows/local runs where only the bot is started).
    if bool(getattr(settings, "enable_sender_in_bot", True)):
        from app.scheduler.sender_job import job_send_notifications

        async def _sender_tick(_ctx):
            try:
                await asyncio.to_thread(job_send_notifications)
            except Exception:
                logger.exception("sender_in_bot tick failed")

        interval = int(getattr(settings, "sched_sender_seconds", 60) or 60)
        interval = max(10, interval)
        application.job_queue.run_repeating(
            _sender_tick,
            interval=interval,
            first=5,
            name="sender_in_bot",
        )


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

    # Smoke test Playwright no boot (somente alerta admins em caso de bug/config)
    if bool(getattr(settings, "playwright_smoke_on_boot", True)):
        try:
            from app.services.playwright_smoke import assert_playwright_ready
            from app.services.admin_programming_alerts import maybe_alert_programming_error
            try:
                assert_playwright_ready()
            except Exception as e:
                try:
                    maybe_alert_programming_error("boot/playwright(bot)", e)
                except Exception:
                    pass
        except Exception:
            pass

    app = Application.builder().token(token).post_init(_post_init).build()

    # core
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("wishlist_help", cmd_wishlist_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("version", cmd_version))

    # search + wishlist (modo antigo continua)
    app.add_handler(CommandHandler("buscar", cmd_buscar))
    app.add_handler(CommandHandler("wishlist", cmd_wishlist))
    app.add_handler(menu_create_wishlist_conversation())
    app.add_handler(menu_filter_conversation())

    # wishlist (UX nova)
    app.add_handler(wishlist_add_conversation())
    app.add_handler(CallbackQueryHandler(cb_wishlist_add_confirm, pattern=r"^W:ADD:(SAVE|CANCEL)$"))
    app.add_handler(CallbackQueryHandler(cb_wishlist_clear, pattern=r"^W:CLEAR:(YES|NO)$"))

    app.add_handler(CommandHandler("wishlist_filter_add", cmd_wishlist_filter_add))
    app.add_handler(CommandHandler("wishlist_filter_list", cmd_wishlist_filter_list))
    app.add_handler(CommandHandler("wishlist_filter_remove", cmd_wishlist_filter_remove))

    app.add_handler(CommandHandler("wishlist_clear", cmd_wishlist_clear))
    app.add_handler(CommandHandler("wishlist_remove", cmd_wishlist_remove))

    app.add_handler(CommandHandler("wishlist_track_add", cmd_wishlist_track_add))
    app.add_handler(CommandHandler("wishlist_track_list", cmd_wishlist_track_list))
    app.add_handler(CommandHandler("wishlist_track_remove", cmd_wishlist_track_remove))
    app.add_handler(CommandHandler("wishlist_track_alert_on", cmd_wishlist_track_alert_on))
    app.add_handler(CommandHandler("wishlist_track_alert_off", cmd_wishlist_track_alert_off))
    app.add_handler(CallbackQueryHandler(cb_track_add, pattern=r"^(TRACK:ADD:[^:]+|TRACK:ADDWL:[^:]+:[^:]+|TRACK:ADDT:[^:]+|TRACK:CHOOSE:[^:]+)$"))
    app.add_handler(quick_search_conversation())
    app.add_handler(CallbackQueryHandler(cb_session_guard, pattern=r"^SESSION:(RESUME|DISCARD:MENU)$"))
    app.add_handler(CallbackQueryHandler(cb_menu, pattern=r"^MENU:[A-Z_]+$"))
    # WL:FILTERS:<idx> é entry-point do menu_filter_conversation e não deve
    # ser capturado por handler global para preservar estado do ConversationHandler.
    app.add_handler(CallbackQueryHandler(cb_menu, pattern=r"^WL:(BACK|TRACKED|FILTERS_MENU|PAUSE_MENU|PAUSE:\d+|PAUSE_CONFIRM:\d+|RESUME_MENU|RESUME:\d+|RESUME_CONFIRM:\d+|REMOVE_MENU|REMOVE:\d+|REMOVE_CONFIRM:\d+)$"))

    # plan
    app.add_handler(CommandHandler("alertas", cmd_alertas))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("fb", cmd_fb))

    # misc
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("upgrade", cmd_upgrade))
    app.add_handler(CallbackQueryHandler(cb_upgrade_plan_choice, pattern=r"^UPGRADE:(MONTHLY|ANNUAL)$"))
    app.add_handler(CommandHandler("setplan", cmd_setplan))
    app.add_handler(CommandHandler("setlimit", cmd_setlimit))

    app.add_error_handler(on_error)

    # IMPORTANTE: agora precisa de callback_query por causa dos botões
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
