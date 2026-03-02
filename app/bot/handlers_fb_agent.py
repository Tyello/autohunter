from __future__ import annotations

from datetime import timezone

from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.integrations.facebook.agent_service import disconnect_agent_session, issue_agent_pairing_code
from app.integrations.facebook.guards import action_hint_for_status
from app.integrations.facebook.service import pairing_link
from app.models.fb_agent_session import FBAgentSession


def _fmt_dt(dt):
    if not dt:
        return "-"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


async def cmd_fb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = [a.strip().lower() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /fb connect | /fb status | /fb disconnect")
        return

    user = update.effective_user
    if not user:
        await update.message.reply_text("Usuário inválido")
        return
    user_id = str(user.id)
    action = args[0]

    if action == "connect":
        with SessionLocal() as db:
            sess = issue_agent_pairing_code(db, user_id)
        link = pairing_link(sess.pairing_code or "")
        await update.message.reply_text(
            "Conexão Facebook (agent local) iniciada.\n"
            f"Código: {sess.pairing_code}\n"
            f"Link: {link}\n\n"
            "Execute o agent local no seu PC/Notebook.\n"
            "Nenhum cookie será enviado ao servidor."
        )
        return

    if action == "status":
        with SessionLocal() as db:
            sess = db.query(FBAgentSession).filter(FBAgentSession.user_id == user_id).one_or_none()
        if not sess:
            await update.message.reply_text("Sem sessão de agent Facebook. Use /fb connect.")
            return
        await update.message.reply_text(
            "Facebook Agent\n"
            f"status={sess.status}\n"
            f"last_seen={_fmt_dt(sess.last_seen_at)}\n"
            f"last_check={_fmt_dt(sess.last_check_at)}\n"
            f"last_ok={_fmt_dt(sess.last_ok_at)}\n"
            f"last_error={sess.last_error_kind or '-'} / {(sess.last_error_message or '-')[:120]}\n"
            f"action_hint={sess.action_hint or action_hint_for_status(sess.status)}"
        )
        return

    if action == "disconnect":
        with SessionLocal() as db:
            sess = disconnect_agent_session(db, user_id)
        if not sess:
            await update.message.reply_text("Nenhuma sessão para desconectar.")
            return
        await update.message.reply_text("Agent desconectado e sessão desabilitada (DISABLED).")
        return

    await update.message.reply_text("Ação inválida. Use: /fb connect | /fb status | /fb disconnect")
