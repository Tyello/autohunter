from __future__ import annotations

import re
from typing import Tuple

from app.core.settings import settings
from app.bot.media import download_image_bytes
from app.bot.text_sanitize import sanitize_for_telegram
from app.notifications.telegram_formatter import format_ad_message
from app.services.http_session import get_shared_session


# Telegram limits
TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_TEXT_MAX = 4096


class _AdView:
    """Adapter: expose listing fields + notification score fields to the formatter."""

    def __init__(self, listing, notification=None):
        self._listing = listing
        self._notification = notification

        # Score fields are persisted on Notification (wishlist-specific)
        self.score_v2 = getattr(notification, 'score_v2', None) if notification is not None else None
        self.score_breakdown = getattr(notification, 'score_breakdown', None) if notification is not None else None

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

def _clean_location(loc: str) -> str:
    s = _clean_spaces(loc or "")
    if not s:
        return ""

    # Se vier poluído, tenta recuperar "Cidade-UF" no final
    noise = {"km", "gasolina", "mecânico", "mecanico"}

    # padrão "Curitiba , PR"
    matches = list(re.finditer(r"([A-Za-zÀ-ÿ\s]+)\s*,\s*([A-Z]{2})\b", s))
    if matches:
        m = matches[-1]
        city_raw = " ".join((m.group(1) or "").split())
        uf = m.group(2)
        toks = [t for t in city_raw.split() if t.lower() not in noise]
        city = " ".join(toks[-4:])
        return f"{city}-{uf}" if city else uf

    # padrão "Curitiba-PR"
    m2 = re.search(r"(.+)-([A-Z]{2})\b\s*$", s)
    if m2:
        city_raw = " ".join((m2.group(1) or "").split())
        uf = m2.group(2)
        toks = [t for t in city_raw.split() if t.lower() not in noise]
        city = " ".join(toks[-4:])
        return f"{city}-{uf}" if city else uf

    return s



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


def _score_from_text(text: str) -> int:
    # Score simples, imediato e 100% offline.
    t = (text or "").lower()

    score = 50
    plus = [
        ("turbo", 10), ("manual", 8), ("si", 8), ("vti", 8), ("vtec", 6),
        ("hatch", 5), ("hatchback", 5), ("jdm", 7), ("swap", 8),
        ("k20", 6), ("b16", 6), ("track", 4),
    ]
    minus = [
        ("batido", -20), ("sinistr", -20), ("leil", -15),
        ("sucata", -30), ("recuperad", -20), ("multa", -8),
        ("documento", -8),
    ]

    for k, w in plus:
        if k in t:
            score += w
    for k, w in minus:
        if k in t:
            score += w

    return max(0, min(100, int(score)))


def _build_text(listing, notification=None) -> str:
    """Build vNext message text (no URL in body; URL is in the button)."""

    payload = format_ad_message(_AdView(listing, notification))
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

    payload = format_ad_message(_AdView(listing, notification))
    full_text = _truncate(sanitize_for_telegram(payload.text), TELEGRAM_TEXT_MAX)
    caption, remainder = _split(full_text, TELEGRAM_CAPTION_MAX)
    caption = _truncate(caption, TELEGRAM_CAPTION_MAX)

    sent_photo = False
    reply_markup = payload.reply_markup_json() or None

    session = get_shared_session("telegram")

    if getattr(listing, "thumbnail_url", None):
        img = download_image_bytes(listing.thumbnail_url, referer=getattr(listing, "url", None))
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
    text = (
        f"⚠️ Você atingiu seu limite de {limit} alertas hoje.\n"
        "Amanhã libera de novo.\n"
        "Para aumentar o limite, use /upgrade"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = get_shared_session("telegram").post(
        url,
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=15,
    )

    if resp.status_code >= 400:
        return False

    return True
