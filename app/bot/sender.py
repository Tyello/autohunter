import requests

from app.core.settings import settings
from app.bot.formatting import format_score, format_price


def telegram_sender(notification, listing, user):
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado")

    chat_id = user.telegram_chat_id

    # Se você já calculou FIPE/score no matching, use isso.
    # MVP: aqui manda preço e link. FIPE entra quando seu matching já estiver abastecendo.
    price_text = format_price(listing.price)

    text = (
        f"{listing.title or 'Novo anúncio'}\n"
        f"Preço: {price_text}\n"
        f"{listing.url}"
    )

    # Se tiver thumb: manda foto
    if listing.thumbnail_url:
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        resp = requests.post(url, data={"chat_id": chat_id, "photo": listing.thumbnail_url, "caption": text}, timeout=15)
    else:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=15)

    if resp.status_code >= 400:
        raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")

def send_daily_limit_notice_http(user, limit: int):
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado")

    chat_id = user.telegram_chat_id
    text = (
        f"⚠️ Você atingiu seu limite de {limit} alertas hoje.\n"
        "Amanhã libera de novo.\n"
        "Para aumentar o limite, use /upgrade"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=15,
    )

    # Se falhar, não derrube o sender inteiro (aviso é best-effort)
    if resp.status_code >= 400:
        # você pode logar em system_logs se quiser
        return False
