from __future__ import annotations

import asyncio
from typing import Any, Dict

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists
from app.bot.admin import is_admin
from app.bot.debug import run_once_for_wishlist, status_for_wishlist
from app.core.settings import settings


def _effective_limits() -> tuple[int, int]:
    """
    Retorna (hard_max, chunk_size) sempre respeitando o limite real do Telegram.
    """
    hard_max = settings.telegram_text_max

    safe_chunk_cfg = int(getattr(settings, "safe_chunk", settings.safe_chunk) or settings.safe_chunk)
    # chunk nunca pode ser >= hard_max
    chunk_size = min(safe_chunk_cfg, hard_max - 200)
    if chunk_size < 500:
        chunk_size = min(settings.safe_chunk, hard_max - 200)

    return hard_max, chunk_size


def _split_preserving_lines(text: str, chunk_size: int) -> list[str]:
    text = text or ""
    if len(text) <= chunk_size:
        return [text]

    out: list[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(n, start + chunk_size)

        # tenta cortar em quebra de linha (melhor UX)
        cut = text.rfind("\n", start, end)
        if cut <= start + 200:
            cut = end

        piece = text[start:cut].rstrip()
        if piece:
            out.append(piece)

        start = cut
        if start < n and text[start] == "\n":
            start += 1

    return out


def _hard_split_piece(piece: str, hard_max: int) -> list[str]:
    """
    Garante que cada pedaço fique <= hard_max, mesmo se settings estiverem errados.
    """
    piece = piece or ""
    if len(piece) <= hard_max:
        return [piece]

    out: list[str] = []
    start = 0
    n = len(piece)

    while start < n:
        end = min(n, start + hard_max)

        # corta preferencialmente em newline
        cut = piece.rfind("\n", start, end)
        if cut <= start + 200:
            cut = end

        part = piece[start:cut].rstrip()
        if part:
            # segurança final
            if len(part) > hard_max:
                part = part[: hard_max - 1] + "…"
            out.append(part)

        start = cut
        if start < n and piece[start] == "\n":
            start += 1

    return out


async def _reply_text_chunked(update, text: str) -> None:
    hard_max, chunk_size = _effective_limits()

    # Primeiro split “bonito”
    chunks = _split_preserving_lines(text, chunk_size)

    # Depois split “hard” para nunca passar de 4096
    safe_chunks: list[str] = []
    for c in chunks:
        safe_chunks.extend(_hard_split_piece(c, hard_max))

    # Envia, com fallback extra se o Telegram ainda reclamar
    for c in safe_chunks:
        try:
            await update.message.reply_text(c, disable_web_page_preview=True)
        except BadRequest as e:
            # fallback extremo: corta seco
            if "Message is too long" in str(e):
                await update.message.reply_text(c[: hard_max - 1] + "…", disable_web_page_preview=True)
            else:
                raise


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
            lines.append(f"- [{x['source']}] {x['price']} {_cap(x['title'], 180)}")
            lines.append(f"  {x['url']}")

        lines.append("\nÚltimos logs (top 5):")
        for l in s["last_logs"][:5]:
            lines.append(f"- {l['level']} {l['component']}: {_cap(l['message'], 260)}")

        await _reply_text_chunked(update, "\n".join(lines))

        return

    await update.message.reply_text("Ação inválida. Use: run|status")


def _cap(s: str, n: int = 220) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"