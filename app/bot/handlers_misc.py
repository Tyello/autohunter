from telegram import Update
from telegram.ext import ContextTypes

async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"chat_id={update.effective_chat.id}")