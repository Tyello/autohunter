from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.services.search_service import manual_search
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import (
    list_wishlists, add_wishlist, remove_wishlist,
    add_filter, list_filters, remove_filter,
)
from app.bot.admin import is_admin

# debug pipeline:
from app.bot.debug import run_once_for_wishlist, status_for_wishlist


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Use: /buscar <termos>")
        return

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)

        results = manual_search(db, query=query, limit=5)  # retorna objetos/DTOs prontos pro bot

    if not results:
        await update.message.reply_text("Nada encontrado agora.")
        return

    # Envio simples: 1 msg por anúncio (MVP)
    for item in results:
        # item já deve trazer url, thumb, price, fipe, score_text
        text = (
            f"{item.title or 'Anúncio'}\n"
            f"Preço: {item.price_text}\n"
            f"FIPE: {item.fipe_text}\n"
            f"{item.score_text}\n"
            f"{item.url}"
        )
        if item.thumbnail_url:
            await update.message.reply_photo(photo=item.thumbnail_url, caption=text)
        else:
            await update.message.reply_text(text)


async def cmd_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = [a.strip() for a in (context.args or []) if a.strip()]
    sub = (args[0].lower() if args else "listar")

    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)

        # /wishlist listar
        if sub in ("listar",):
            w = list_wishlists(db, user.id)
            if not w:
                await update.message.reply_text("Você não tem wishlists. Use: /wishlist add <termos>")
                return
            lines = [f"{i+1}. {x.query}" for i, x in enumerate(w)]
            await update.message.reply_text("Wishlists:\n" + "\n".join(lines))
            return

        # /wishlist add <termos>
        if sub == "add":
            query = " ".join(args[1:]).strip()
            if not query:
                await update.message.reply_text("Use: /wishlist add <termos>")
                return
            ok, msg = add_wishlist(db, user.id, query)
            await update.message.reply_text(msg)
            return

        # /wishlist rm <numero>
        if sub == "rm":
            if len(args) < 2 or not args[1].isdigit():
                await update.message.reply_text("Use: /wishlist rm <numero>")
                return
            ok, msg = remove_wishlist(db, user.id, int(args[1]))
            await update.message.reply_text(msg)
            return

        # /wishlist filter ...
        if sub == "filter":
            if len(args) < 2:
                await update.message.reply_text(
                    "Use:\n"
                    "/wishlist filter add <n> price lte 90000\n"
                    "/wishlist filter add <n> source eq mercadolivre\n"
                    "/wishlist filter list <n>\n"
                    "/wishlist filter rm <n> <filter_num>"
                )
                return

            action = args[1].lower()
            w = list_wishlists(db, user.id)

            def get_wishlist_by_index(n: int):
                if n < 1 or n > len(w):
                    return None
                return w[n-1]

            if action == "list":
                if len(args) < 3 or not args[2].isdigit():
                    await update.message.reply_text("Use: /wishlist filter list <n>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
                    return
                fs = list_filters(db, wl.id)
                if not fs:
                    await update.message.reply_text("Sem filtros. Use /wishlist filter add ...")
                    return
                lines = [f"{i+1}. {f.field} {f.operator} {f.value}" for i, f in enumerate(fs)]
                await update.message.reply_text("Filtros:\n" + "\n".join(lines))
                return

            if action == "add":
                if len(args) < 6 or not args[2].isdigit():
                    await update.message.reply_text("Use: /wishlist filter add <n> <field> <op> <value>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
                    return
                field, op, value = args[3], args[4], args[5]
                ok, msg = add_filter(db, wl.id, field, op, value)
                await update.message.reply_text(msg)
                return

            if action == "rm":
                if len(args) < 4 or (not args[2].isdigit()) or (not args[3].isdigit()):
                    await update.message.reply_text("Use: /wishlist filter rm <n> <filter_num>")
                    return
                wi = int(args[2])
                wl = get_wishlist_by_index(wi)
                if not wl:
                    await update.message.reply_text("Wishlist inválida. Use /wishlist listar.")
                    return
                ok, msg = remove_filter(db, wl.id, int(args[3]))
                await update.message.reply_text(msg)
                return

            await update.message.reply_text("Ação inválida. Use: add|list|rm")
            return

        await update.message.reply_text("Use: /wishlist listar | /wishlist add <termos> | /wishlist rm <numero>")


async def cmd_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # MVP: só informa limites e estado (sem painel complexo)
    await update.message.reply_text(
        "Alertas do AutoHunter:\n"
        "- Monitoramento: a cada 30 min (Mercado Livre e OLX)\n"
        "- Limite: 10 alertas/dia\n"
        "Use /wishlist para gerenciar suas buscas monitoradas."
    )
