from __future__ import annotations

import logging
import re
import json
from datetime import datetime, timedelta, timezone
from typing import Tuple
from zoneinfo import ZoneInfo

from app.core.settings import settings
from app.bot.media import download_image_bytes
from app.bot.text_sanitize import sanitize_for_telegram
from app.notifications.telegram_formatter import format_ad_message, format_tracked_price_drop_message
from app.services.http_session import get_shared_session

logger = logging.getLogger(__name__)


# Telegram limits
TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_TEXT_MAX = 4096


def _daily_limit_renews_text(now: datetime | None = None) -> str:
    tz_name = getattr(settings, "default_user_timezone", None) or "America/Sao_Paulo"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz_name = "America/Sao_Paulo"
        tz = ZoneInfo(tz_name)

    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    local_now = base.astimezone(tz)
    next_midnight = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    time_label = "00h" if next_midnight.minute == 0 else next_midnight.strftime("%Hh%M")
    tz_label = "horário de São Paulo" if tz_name == "America/Sao_Paulo" else f"horário local ({tz_name})"

    if next_midnight.date() == (local_now.date() + timedelta(days=1)):
        return f"O limite renova amanhã às {time_label} ({tz_label})."
    return f"O limite renova em {next_midnight.strftime('%d/%m')} às {time_label} ({tz_label})."


class _AdView:
    """Adapter: expose listing fields + notification score fields to the formatter."""

    def __init__(self, listing, notification=None):
        self._listing = listing
        self._notification = notification

        # Score fields are persisted on Notification (wishlist-specific)
        self.score_v2 = getattr(notification, 'score_v2', None) if notification is not None else None
        self.score_breakdown = getattr(notification, 'score_breakdown', None) if notification is not None else None
        self.notification_id = str(getattr(notification, 'id', '') or '') if notification is not None else ''
        self.reason = getattr(notification, 'reason', None) if notification is not None else None

        self.wishlist_query = None
        self.wishlist_filters = []
        try:
            w = getattr(notification, "wishlist", None) if notification is not None else None
            if w is not None:
                self.wishlist_query = getattr(w, "query", None)
                fs = getattr(w, "filters", None) or []
                self.wishlist_filters = [
                    {"field": getattr(f, "field", None), "operator": getattr(f, "operator", None), "value": getattr(f, "value", None)}
                    for f in fs
                ]
        except Exception:
            self.wishlist_query = None
            self.wishlist_filters = []

    def __getattr__(self, item):
        return getattr(self._listing, item)


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


_RE_KM = re.compile(r"\b(\d{1,3}(?:\.\d{3})*|\d+)\s*km\b", re.I)

def _extract_km(title: str) -> str | None:
    if not title:
        return None
    m = _RE_KM.search(title)
    if not m:
        return None
    km = m.group(1)
    # normaliza: "223000" -> "223.000" (melhor esforço)
    if km.isdigit() and len(km) >= 4:
        # insere separador de milhar
        parts = []
        s = km
        while s:
            parts.append(s[-3:])
            s = s[:-3]
        km = ".".join(reversed(parts))
    return km

def _clean_title_and_extract_km(title: str) -> tuple[str, str | None]:
    t = _clean_spaces(title or "")
    km = _extract_km(t)

    # remove KM do título (vai pra linha separada)
    t = _RE_KM.sub("", t)

    # remove combustível / câmbio por enquanto (pedido)
    t = re.sub(r"\bGasolina\b", "", t, flags=re.I)
    t = re.sub(r"\bMec[aâ]nico\b|\bMecanico\b", "", t, flags=re.I)

    # remove "Cidade , UF" no fim (evita duplicar com Local)
    t = re.sub(r"\s+[A-Za-zÀ-ÿ\s]+\s*,\s*[A-Z]{2}\b\s*$", "", t).strip()

    return _clean_spaces(t) or "Novo anúncio", km


def _extract_year(title: str) -> int | None:
    t = title or ""
    m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if not m:
        return None
    try:
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            return y
    except Exception:
        return None
    return None




def _build_text(listing, notification=None) -> str:
    """Build vNext message text (no URL in body; URL is in the button)."""

    ad_view = _AdView(listing, notification)
    if getattr(notification, "reason", None) == "tracked_price_drop":
        payload = format_tracked_price_drop_message(notification, ad_view)
    else:
        payload = format_ad_message(ad_view)
    text = sanitize_for_telegram(payload.text)
    return _truncate(text, TELEGRAM_TEXT_MAX)


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

    ad_view = _AdView(listing, notification)
    if getattr(notification, "reason", None) == "tracked_price_drop":
        payload = format_tracked_price_drop_message(notification, ad_view)
    else:
        payload = format_ad_message(ad_view)
    full_text = _truncate(sanitize_for_telegram(payload.text), TELEGRAM_TEXT_MAX)
    caption, remainder = _split(full_text, TELEGRAM_CAPTION_MAX)
    caption = _truncate(caption, TELEGRAM_CAPTION_MAX)

    sent_photo = False
    reply_markup = payload.reply_markup_json() or None

    session = get_shared_session("telegram")

    listing_thumbnail_url = getattr(listing, "thumbnail_url", None)
    listing_url = getattr(listing, "url", None)
    if listing_thumbnail_url:
        img = download_image_bytes(listing_thumbnail_url, referer=listing_url)
        if img:
            img_bytes, ctype = img
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            resp = session.post(
                url,
                data={"chat_id": chat_id, "caption": caption, **({"reply_markup": reply_markup} if reply_markup else {})},
                files={"photo": ("thumb", img_bytes, ctype)},
                timeout=20,
            )

            if resp.status_code < 400:
                sent_photo = True
            else:
                logger.warning(
                    "telegram_sender: sendPhoto failed (status=%s) for listing_url=%s thumbnail_url=%s, falling back to text: %s",
                    resp.status_code, listing_url, listing_thumbnail_url, resp.text,
                )
        else:
            logger.warning(
                "telegram_sender: could not download thumbnail for listing_url=%s thumbnail_url=%s, falling back to text",
                listing_url, listing_thumbnail_url,
            )
    else:
        logger.warning(
            "telegram_sender: listing has no thumbnail_url (source=%s, listing_url=%s), sending text-only alert",
            getattr(listing, "source", None), listing_url,
        )

    if not sent_photo:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = session.post(
            url,
            data={
                "chat_id": chat_id,
                "text": full_text,
                "disable_web_page_preview": True,
                **({"reply_markup": reply_markup} if reply_markup else {}),
            },
            timeout=20,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")
        return

    if remainder.strip():
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        extra = _truncate(remainder.strip(), TELEGRAM_TEXT_MAX)
        resp2 = session.post(
            url,
            data={"chat_id": chat_id, "text": extra, "disable_web_page_preview": True},
            timeout=20,
        )
        if resp2.status_code >= 400:
            return


def send_daily_limit_notice_http(user, limit: int):
    token = settings.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN não configurado")

    chat_id = user.telegram_chat_id
    text = render_daily_limit_notice(limit=limit, renews_text=_daily_limit_renews_text())
    reply_markup = json.dumps(
        {"inline_keyboard": [[{"text": "🚀 Ver Premium", "callback_data": "MENU:UPGRADE"}]]},
        ensure_ascii=False,
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = get_shared_session("telegram").post(
        url,
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True, "reply_markup": reply_markup},
        timeout=15,
    )

    if resp.status_code >= 400:
        return False

    return True


def render_daily_limit_notice(
    limit: int,
    missed_count: int | None = None,
    renews_text: str | None = None,
    premium_limit: int | None = None,
) -> str:
    renews_line = renews_text or "O limite renova automaticamente amanhã."

    lines = [
        "⚠️ Limite diário atingido",
        "",
        f"Você já recebeu {int(limit)} alertas hoje nesta busca.",
    ]

    if missed_count is not None and int(missed_count) > 0:
        lines.append(
            f"Encontrei mais {int(missed_count)} anúncio(s) compatíveis, mas eles não foram enviados por causa do limite do plano."
        )

    lines.extend(["", renews_line, ""])

    if premium_limit is not None and int(premium_limit) > 0:
        lines.append(f"Com Premium, você recebe até {int(premium_limit)} alertas por dia por busca.")
    elif missed_count is not None and int(missed_count) > 0:
        lines.append("Com Premium, você recebe mais alertas por dia e reduz a chance de perder oportunidade boa.")
    else:
        lines.append("Com Premium, você recebe mais alertas por dia e acompanha mais oportunidades sem esperar o dia seguinte.")

    return "\n".join(lines)


def send_plain_text_to_user(chat_id: int, text: str) -> bool:
    token = settings.telegram_bot_token
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = get_shared_session("telegram").post(
        url,
        data={"chat_id": int(chat_id), "text": _truncate(sanitize_for_telegram(text), TELEGRAM_TEXT_MAX), "disable_web_page_preview": True},
        timeout=15,
    )
    return resp.status_code < 400
