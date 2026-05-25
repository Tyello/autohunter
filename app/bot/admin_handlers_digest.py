from __future__ import annotations

from typing import List

from telegram import Update

from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.weekly_digest_service import build_weekly_digest_candidates, build_weekly_digest_for_user
from app.bot.weekly_digest_renderer import render_weekly_digest, render_weekly_digest_candidates
from app.scheduler.weekly_digest_job import run_weekly_digest_once
from app.services.weekly_digest_preferences_service import (
    get_or_create_digest_preference,
    mark_digest_previewed,
    set_weekly_digest_enabled,
    update_weekly_digest_preferences,
)


async def admin_digest(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /admin digest user <telegram_chat_id> [1-30] | /admin digest candidates [1-30] [1-50] | /admin digest prefs <chat_id> | /admin digest enable <chat_id> | /admin digest disable <chat_id> | /admin digest config <chat_id> days|limit <valor> | /admin digest run [dry|live]")
        return
    sub = args[0].lower()
    if sub == "run":
        mode = (args[1].lower() if len(args) >= 2 else "dry")
        if mode not in {"dry", "live"}:
            await update.message.reply_text("Use: /admin digest run [dry|live]")
            return
        if mode == "live" and not bool(getattr(settings, "weekly_digest_job_enabled", False)):
            await update.message.reply_text("Live bloqueado: weekly_digest_job_enabled=false.")
            return
        stats = run_weekly_digest_once(dry_run=(mode != "live"))
        await update.message.reply_text(
            "Digest run summary\n"
            f"mode={mode}\n"
            f"checked={stats.get('checked', 0)}\n"
            f"eligible={stats.get('eligible', 0)}\n"
            f"sent={stats.get('sent', 0)}\n"
            f"skipped_recent={stats.get('skipped_recent', 0)}\n"
            f"skipped_empty={stats.get('skipped_empty', 0)}\n"
            f"failed={stats.get('failed', 0)}"
        )
        return

    if sub == "candidates":
        days = 7
        limit = 20
        if len(args) >= 2:
            try:
                days = int(args[1])
            except Exception:
                await update.message.reply_text("Janela inválida, usando padrão de 7 dias.")
                days = 7
        if len(args) >= 3:
            try:
                limit = int(args[2])
            except Exception:
                await update.message.reply_text("Limite inválido, usando padrão de 20.")
                limit = 20
        days = max(1, min(30, days))
        limit = max(1, min(50, limit))
        with SessionLocal() as db:
            candidates = build_weekly_digest_candidates(db, days=days, limit=limit)
        await update.message.reply_text(render_weekly_digest_candidates(candidates, days=days))
        return


    if sub in {"prefs", "enable", "disable", "config"}:
        if len(args) < 2:
            await update.message.reply_text("Informe o telegram_chat_id.")
            return
        try:
            chat_id = int(args[1])
        except Exception:
            await update.message.reply_text("telegram_chat_id inválido.")
            return
        with SessionLocal() as db:
            user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
            if not user:
                await update.message.reply_text("Usuário não encontrado para este telegram_chat_id.")
                return
            if sub == "prefs":
                pref = get_or_create_digest_preference(db, user.id)
            elif sub == "enable":
                pref = set_weekly_digest_enabled(db, user.id, True)
            elif sub == "disable":
                pref = set_weekly_digest_enabled(db, user.id, False)
            else:
                if len(args) < 4 or args[2].lower() not in {"days", "limit"}:
                    await update.message.reply_text("Use: /admin digest config <chat_id> days <1-30> | /admin digest config <chat_id> limit <1-20>")
                    return
                key = args[2].lower()
                try:
                    value = int(args[3])
                except Exception:
                    await update.message.reply_text("Valor inválido.")
                    return
                try:
                    pref = update_weekly_digest_preferences(db, user.id, **{key: value})
                except ValueError as exc:
                    await update.message.reply_text(str(exc))
                    return
            await update.message.reply_text(
                "Digest prefs\n"
                f"chat_id={chat_id}\n"
                f"enabled={'true' if pref.weekly_digest_enabled else 'false'}\n"
                f"days={pref.digest_days}\n"
                f"limit={pref.digest_limit}\n"
                f"last_sent_at={pref.last_digest_sent_at or '-'}\n"
                f"last_previewed_at={pref.last_digest_previewed_at or '-'}"
            )
        return
    if len(args) < 2 or sub != "user":
        await update.message.reply_text("Use: /admin digest user <telegram_chat_id> [1-30] | /admin digest candidates [1-30] [1-50] | /admin digest prefs <chat_id> | /admin digest enable <chat_id> | /admin digest disable <chat_id> | /admin digest config <chat_id> days|limit <valor> | /admin digest run [dry|live]")
        return

    try:
        chat_id = int(args[1])
    except Exception:
        await update.message.reply_text("telegram_chat_id inválido.")
        return

    days = 7
    if len(args) >= 3:
        try:
            days = int(args[2])
        except Exception:
            await update.message.reply_text("Janela inválida, usando padrão de 7 dias.")
            days = 7
    days = max(1, min(30, days))

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not user:
            await update.message.reply_text("Usuário não encontrado para este telegram_chat_id.")
            return
        payload = build_weekly_digest_for_user(db, user_id=user.id, days=days, limit=10)
        mark_digest_previewed(db, user.id, create_if_missing=True)

    await update.message.reply_text(render_weekly_digest(payload))
