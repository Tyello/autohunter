from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from telegram import Update

from app.bot.text_sanitize import sanitize_for_telegram
from app.db.session import SessionLocal


async def admin_tokens_health(update: Update) -> None:
    """Shows top wishlist tokens."""
    from sqlalchemy import select, func
    from app.models.wishlist_token import WishlistToken

    with SessionLocal() as db:
        total = db.execute(select(func.count()).select_from(WishlistToken)).scalar_one() or 0
        rows = db.execute(
            select(WishlistToken.token, func.count().label("c"))
            .group_by(WishlistToken.token)
            .order_by(func.count().desc())
            .limit(25)
        ).all()

    lines = [
        "🧩 AutoHunter — tokens health (admin)",
        f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}",
        f"total_tokens={total}",
        "",
        "Top tokens:",
    ]
    if not rows:
        lines.append("- (vazio)")
    else:
        for t, c in rows:
            lines.append(f"- {t}: {int(c)}")

    await update.effective_message.reply_text(sanitize_for_telegram("\n".join(lines)))


async def admin_tokens_dispatch(update: Update, args: List[str]) -> None:
    sub = (args[0].lower() if args else "health")
    if sub != "health":
        await update.effective_message.reply_text("Use: /admin tokens health")
        return
    await admin_tokens_health(update)
