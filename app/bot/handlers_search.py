from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.search_service import manual_search


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Use: /buscar <termos>\nEx: /buscar civic 2019")
        return

    with SessionLocal() as db:
        _user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        results = manual_search(db, query=query, limit=5)

    if not results:
        await update.message.reply_text("Nada encontrado agora.")
        return

    for item in results:
        # item aqui pode ser CarListing (model). Ajuste conforme seu retorno.
        price_text = f"R$ {item.price}" if item.price is not None else "—"

        text = (
            f"{item.title or 'Anúncio'}\n"
            f"Fonte: {item.source}\n"
            f"Preço: {price_text}\n"
            f"{item.url}"
        )

        if item.thumbnail_url:
            await update.message.reply_photo(photo=item.thumbnail_url, caption=text)
        else:
            await update.message.reply_text(text)
