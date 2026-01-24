from __future__ import annotations

import asyncio
from typing import Any, Dict

from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists
from app.bot.admin import is_admin
from app.bot.debug import run_once_for_wishlist, status_for_wishlist


def _debug_worker(action: str, chat_id: int, username: str | None, idx: int) -> Dict[str, Any]:
    """Executa o debug fora do event-loop.

    PlaywrightPool usa a Sync API. Se chamar dentro do asyncio loop do
    python-telegram-bot, dá erro: "Playwright Sync API inside the asyncio loop".
    """
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, chat_id, username)
        wishlists = list_wishlists(db, user.id)

        if idx < 1 or idx > len(wishlists):
            return {"error": "Wishlist inválida. Use /wishlist listar."}

        wl = wishlists[idx - 1]

        if action == "run":
            r = run_once_for_wishlist(db, wl)
            return {"action": "run", "result": r}

        if action == "status":
            s = status_for_wishlist(db, wl)
            return {"action": "status", "result": s}

        return {"error": "Ação inválida. Use: run|status"}


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Acesso negado.")
        return

    args = [a.strip() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /debug run <n> | /debug status <n>")
        return

    action = args[0].lower()
    if len(args) < 2 or not args[1].isdigit():
        await update.message.reply_text("Use: /debug run <n> | /debug status <n>")
        return
    idx = int(args[1])

    res = await asyncio.to_thread(_debug_worker, action, chat_id, update.effective_user.username, idx)

    if "error" in res:
        await update.message.reply_text(res["error"])
        return

    if res["action"] == "run":
        r = res["result"]
        await update.message.reply_text(
            "Rodada debug executada:\n"
            f"- query: {r['query']}\n"
            f"- ML: {r['ml_url']}\n"
            f"- OLX: {r['olx_url']}\n"
            "Agora rode: /debug status <n>"
        )
        return

    if res["action"] == "status":
        s = res["result"]

        lines = []
        lines.append(f"Wishlist: {s['wishlist']['query']} (id {s['wishlist']['id'][:8]}...)")
        lines.append("Filtros:")
        if s["filters"]:
            for f in s["filters"]:
                lines.append(f"- {f['field']} {f['operator']} {f['value']}")
        else:
            lines.append("- (nenhum)")

        lines.append("\nNotifications:")
        if s["notifications"]:
            for k, v in s["notifications"].items():
                lines.append(f"- {k}: {v}")
        else:
            lines.append("- (nenhuma)")

        lines.append("\nDedupe:")
        if s["dupes"]:
            lines.append("❌ Duplicados encontrados (isso não pode acontecer):")
            for d in s["dupes"]:
                lines.append(f"- {d['source']} {d['external_id']} cnt={d['cnt']}")
        else:
            lines.append("✔ Sem duplicados (ok)")

        lines.append("\nÚltimos anúncios (top 3):")
        for x in s["last_listings"][:3]:
            lines.append(f"- [{x['source']}] {x['price']} {x['title']}")
            lines.append(f"  {x['url']}")

        lines.append("\nÚltimos logs (top 5):")
        for l in s["last_logs"][:5]:
            lines.append(f"- {l['level']} {l['component']}: {l['message']}")

        await update.message.reply_text("\n".join(lines))
        return

    await update.message.reply_text("Ação inválida. Use: run|status")
