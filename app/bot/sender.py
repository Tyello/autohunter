from __future__ import annotations

import re
from typing import Optional, Tuple

import requests

from app.core.settings import settings
from app.bot.formatting import format_price
from app.bot.text_sanitize import sanitize_for_telegram


# Telegram limits
TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_TEXT_MAX = 4096

# RPi-friendly guardrails
MAX_IMAGE_BYTES = 3_500_000  # ~3.5MB


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _split(text: str, limit: int) -> Tuple[str, str]:
    if not text:
        return "", ""
    if len(text) <= limit:
        return text, ""
    return text[:limit], text[limit:]


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _build_text(listing) -> str:
    title = _clean_spaces(listing.title or "Novo anúncio")
    price_text = format_price(listing.price)
    loc = _clean_spaces(getattr(listing, "location", None) or "")

    lines = [title]
    lines.append(f"Preço: {price_text}")
    if loc:
        lines.append(f"Local: {loc}")
    lines.append(listing.url)

    text = "\n".join(lines)
    text = sanitize_for_telegram(text)
    return _truncate(text, TELEGRAM_TEXT_MAX)


def _download_image_bytes(url: str, timeout: int = 8) -> Optional[Tuple[bytes, str]]:
    """Baixa a imagem e valida Content-Type.

    Evita os erros 400 do Telegram quando você manda uma URL que:
    - não é imagem (HTML/403/redirect)
    - é lenta/bloqueada para o fetch do Telegram
    """
    if not url:
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        "Referer": "https://www.olx.com.br/",
    }

    try:
        with requests.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=True) as r:
            if r.status_code != 200:
                return None
            ctype = (r.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("image/"):
                return None

            buf = bytearray()
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > MAX_IMAGE_BYTES:
                    return None

            return bytes(buf), ctype
    except Exception:
        return None


def telegram_sender(notification, listing, user):
    """Envia notificação via HTTP para o Telegram.

    Corrige erros comuns:
    - caption too long (1024)
    - wrong type of the web page content (URL não é imagem)
    - failed to get HTTP URL content (Telegram não consegue baixar a URL)

    Estratégia:
    - se existir thumbnail: baixa a imagem e envia bytes (multipart)
    - caption é truncada; se sobrar conteúdo, manda follow-up em sendMessage
    - em texto: disable_web_page_preview para evitar erros/latência
    """
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado")

    chat_id = user.telegram_chat_id

    full_text = _build_text(listing)
    caption, remainder = _split(full_text, TELEGRAM_CAPTION_MAX)
    caption = _truncate(caption, TELEGRAM_CAPTION_MAX)

    # Preferimos enviar a imagem como bytes para não depender do fetch do Telegram.
    sent_photo = False

    if getattr(listing, "thumbnail_url", None):
        img = _download_image_bytes(listing.thumbnail_url)
        if img:
            img_bytes, ctype = img
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": ("thumb", img_bytes, ctype)},
                timeout=20,
            )

            if resp.status_code < 400:
                sent_photo = True
            else:
                # Se a foto falhar, cai pro texto.
                sent_photo = False

    if not sent_photo:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": full_text, "disable_web_page_preview": True},
            timeout=20,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")
        return

    # Foto enviada com caption curta. Se sobrou texto (muito raro), envia como follow-up.
    if remainder.strip():
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        extra = _truncate(remainder.strip(), TELEGRAM_TEXT_MAX)
        resp2 = requests.post(
            url,
            data={"chat_id": chat_id, "text": extra, "disable_web_page_preview": True},
            timeout=20,
        )
        if resp2.status_code >= 400:
            # não derruba a notificação: a foto já foi enviada
            return


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
        return False

    return True
