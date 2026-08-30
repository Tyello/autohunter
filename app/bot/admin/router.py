from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.admin import is_admin
from app.bot.admin.helpers import (
    fmt_dt as _fmt_dt,
)
from app.bot.admin.sources import (
    admin_sources_dispatch,
    admin_sources_show,
    admin_sources_set_simple,
    admin_sources_reset,
    _admin_sources,
    _admin_source_unified,
)
from app.bot.admin.deploy import admin_deploy as _admin_deploy_impl
from app.bot.admin.health import admin_health, admin_audit, admin_errors
from app.bot.admin.diagnostics import admin_dedupe, admin_tracking
from app.bot.admin.metrics import admin_metrics
from app.bot.admin.digest import admin_digest
from app.bot.admin.fipe import admin_fipe
from app.bot.admin.misc import (
    admin_db_io,
    _admin_cleanup,
    _admin_warmup,
    _admin_matchdebug,
    _admin_requeue,
    _admin_runall,
    _admin_premium,
    _admin_fb_sessions,
    _admin_reindex_wishlists,
)
from app.bot.admin.users import (
    _admin_users,
)
from app.bot.admin.auctions import _admin_auctions


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dispatcher.

    Usage:
      /admin sources
      /admin health
    """
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    args = [a.strip() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /admin sources | /admin auctions | /admin cleanup | /admin runall | /admin matchdebug | /admin requeue | /admin reindex_wishlists | /admin tokens | /admin health | /admin audit | /admin users | /admin errors | /admin deploy | /admin premium | /admin dedupe | /admin tracking | /admin digest | /admin fipe | /admin metrics | /admin db io")
        return

    action = args[0].lower()
    if action == "sources":
        await admin_sources_dispatch(
            update,
            args[1:],
            admin_sources_fn=_admin_sources,
            admin_sources_show_fn=admin_sources_show,
            admin_sources_set_simple_fn=admin_sources_set_simple,
            admin_sources_reset_fn=admin_sources_reset,
        )
        return
    if action == "source":
        await _admin_source_unified(update, args[1:])
        return
    if action == "health":
        await admin_health(update, args[1:])
        return
    if action == "audit":
        await admin_audit(update, args[1:])
        return
    if action == "users":
        await _admin_users(update, args[1:])
        return
    if action == "errors":
        await admin_errors(update, args[1:])
        return
    if action == "deploy":
        await _admin_deploy(update, context, args[1:])
        return
    if action == "fb_sessions":
        await _admin_fb_sessions(update)
        return
    if action == "runall":
        await _admin_runall(update, args[1:])
        return
    if action == "warmup":
        await _admin_warmup(update, args[1:])
        return
    if action == "premium":
        await _admin_premium(update, context, args[1:])
        return
    if action == "auctions":
        await _admin_auctions(update, args[1:])
        return
    if action == "dedupe":
        await admin_dedupe(update, args[1:])
        return
    if action == "tracking":
        await admin_tracking(update, args[1:])
        return
    if action == "digest":
        await admin_digest(update, args[1:])
        return
    if action == "fipe":
        await admin_fipe(update, args[1:])
        return
    if action == "metrics":
        await admin_metrics(update, args[1:])
        return

    if action == "db" and len(args) >= 2 and args[1].lower() == "io":
        await admin_db_io(update)
        return
    if action == "cleanup":
        await _admin_cleanup(update, args[1:])
        return

    if action == "matchdebug":
        await _admin_matchdebug(update, args[1:])
        return

    if action == "requeue":
        await _admin_requeue(update, args[1:])
        return

    if action == "reindex_wishlists":
        await _admin_reindex_wishlists(update, args[1:])
        return

    if action == "tokens":
        from app.bot.admin.tokens import admin_tokens_dispatch
        await admin_tokens_dispatch(update, args[1:])
        return

    await update.message.reply_text("Ação inválida. Use: /admin sources | /admin warmup | /admin auctions | /admin cleanup | /admin runall | /admin matchdebug | /admin requeue | /admin reindex_wishlists | /admin tokens | /admin health | /admin audit | /admin users | /admin errors | /admin deploy | /admin fb_sessions | /admin premium | /admin dedupe | /admin tracking | /admin digest | /admin fipe | /admin metrics | /admin db io")



async def _admin_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]):
    return await _admin_deploy_impl(update, args, fmt_dt=_fmt_dt)
