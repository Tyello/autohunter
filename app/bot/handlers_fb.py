from __future__ import annotations

from datetime import timezone

from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.integrations.facebook.constants import STATUS_DISABLED
from app.integrations.facebook.service import action_hint_for_status, disconnect_session, issue_pairing_code, pairing_link
from app.models.fb_session import FBSession


def _fmt_dt(dt):
    if not dt:
        return "-"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


async def cmd_fb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = [a.strip().lower() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /fb connect | /fb status | /fb disconnect")
        return

    action = args[0]
    user = update.effective_user
    if not user:
        await update.message.reply_text("Usuário inválido")
        return
    user_id = str(user.id)

    if action == "connect":
        with SessionLocal() as db:
            sess = issue_pairing_code(db, user_id)
        link = pairing_link(sess.pairing_code or "")
        await update.message.reply_text(
            "Conexão Facebook iniciada.\n"
            f"Código: {sess.pairing_code}\n"
            f"Link: {link}\n\n"
            "⚠️ Não envie cookies pelo Telegram. Faça login apenas na página web."
        )
        return

    if action == "status":
        with SessionLocal() as db:
            sess = db.query(FBSession).filter(FBSession.user_id == user_id).one_or_none()
        if not sess:
            await update.message.reply_text("Sem sessão Facebook. Use /fb connect.")
            return
        hint = action_hint_for_status(sess.status)
        await update.message.reply_text(
            "Facebook Marketplace\n"
            f"status={sess.status}\n"
            f"validated_at={_fmt_dt(sess.session_validated_at)}\n"
            f"last_check={_fmt_dt(sess.last_check_at)}\n"
            f"last_ok={_fmt_dt(sess.last_ok_at)}\n"
            f"last_error={sess.last_error_kind or '-'} / {(sess.last_error_message or '-')[:120]}\n"
            f"action_hint={hint}"
        )
        return

    if action == "disconnect":
        with SessionLocal() as db:
            sess = disconnect_session(db, user_id)
        if not sess:
            await update.message.reply_text("Nenhuma sessão para desconectar.")
            return
        await update.message.reply_text(f"Sessão desconectada (status={STATUS_DISABLED}). Limpeza de profile será feita depois.")
        return

    await update.message.reply_text("Ação inválida. Use: /fb connect | /fb status | /fb disconnect")
