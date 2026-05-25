from __future__ import annotations

from typing import List

from telegram import Update

from app.bot.admin_dedupe_diagnostics import (
    parse_dedupe_collisions_limit,
    render_cross_source_dedupe_collisions,
)
from app.bot.admin_dedupe_shadow_report import (
    parse_dedupe_shadow_args,
    render_cross_source_dedupe_shadow_report,
)
from app.bot.admin_tracking_diagnostics import (
    parse_tracking_window_hours,
    render_tracking_diagnostics,
)
from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.cross_source_dedupe_observability_service import (
    build_cross_source_dedupe_shadow_report,
)
from app.services.cross_source_dedupe_service import (
    find_cross_source_fingerprint_collisions,
)
from app.services.tracking_diagnostics_service import build_tracking_diagnostics


def _truncate_admin_message(text: str, max_chars: int = 3500) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    suffix = "\n\nDiagnóstico reduzido para caber no Telegram."
    allowed = max(0, max_chars - len(suffix))
    return text[:allowed].rstrip() + suffix, True


async def admin_tracking(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if args and args[0].lower() not in {"status", "price_drop"}:
        await update.message.reply_text("Use: /admin tracking | /admin tracking status [horas] | /admin tracking price_drop [horas]")
        return

    window_hours = parse_tracking_window_hours(args[1:] if args else [])
    with SessionLocal() as db:
        payload = build_tracking_diagnostics(db, window_hours=window_hours)
    rendered = render_tracking_diagnostics(payload)
    msg, _ = _truncate_admin_message(rendered, max_chars=3500)
    await update.message.reply_text(msg)


async def admin_dedupe(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if args and args[0].lower() not in {"collisions", "shadow"}:
        await update.message.reply_text("Use: /admin dedupe | /admin dedupe collisions [N] | /admin dedupe shadow [horas] [limite]")
        return

    if args and args[0].lower() == "shadow":
        hours, examples_limit = parse_dedupe_shadow_args(args)
        with SessionLocal() as db:
            report = build_cross_source_dedupe_shadow_report(db, hours=hours, limit=examples_limit)
        rendered = render_cross_source_dedupe_shadow_report(report)
    else:
        limit = parse_dedupe_collisions_limit(args)
        with SessionLocal() as db:
            collisions = find_cross_source_fingerprint_collisions(db, limit=limit)

        rendered = render_cross_source_dedupe_collisions(
            collisions,
            dedupe_flags={
                "enabled": bool(getattr(settings, "cross_source_dedupe_enabled", False)),
                "shadow_mode": bool(getattr(settings, "cross_source_dedupe_shadow_mode", True)),
                "window_days": int(getattr(settings, "cross_source_dedupe_window_days", 30) or 30),
            },
        )
    msg, _ = _truncate_admin_message(rendered, max_chars=3500)
    await update.message.reply_text(msg)
