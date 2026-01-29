from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.search_service import manual_search
from app.bot.formatting import format_price
from app.bot.text_sanitize import sanitize_for_telegram


TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_TEXT_MAX = 4096


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _split(text: str, limit: int) -> tuple[str, str]:
    if not text:
        return "", ""
    if len(text) <= limit:
        return text, ""
    return text[:limit], text[limit:]


_RE_KM = re.compile(r"\b(\d{1,3}(?:\.\d{3})*|\d+)\s*km\b", re.I)

def _extract_km(title: str) -> str | None:
    if not title:
        return None
    m = _RE_KM.search(title)
    if not m:
        return None
    km = m.group(1)
    if km.isdigit() and len(km) >= 4:
        parts = []
        s = km
        while s:
            parts.append(s[-3:])
            s = s[:-3]
        km = ".".join(reversed(parts))
    return km

def _clean_title_and_extract_km(title: str) -> tuple[str, str | None]:
    t = re.sub(r"\s+", " ", (title or "")).strip()
    km = _extract_km(t)
    t = _RE_KM.sub("", t)
    t = re.sub(r"\bGasolina\b", "", t, flags=re.I)
    t = re.sub(r"\bMec[aâ]nico\b|\bMecanico\b", "", t, flags=re.I)
    t = re.sub(r"\s+[A-Za-zÀ-ÿ\s]+\s*,\s*[A-Z]{2}\b\s*$", "", t).strip()
    t = re.sub(r"\s+", " ", t).strip()
    return t or "Novo anúncio", km

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


def _score_from_title(title: str) -> int:
    # Score simples (diferencial imediato) – “entusiasta”
    t = (title or "").lower()

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


def _build_text(item) -> str:
    title = (getattr(item, "title", None) or "Anúncio").strip()
    price_text = format_price(getattr(item, "price", None))
    src = (getattr(item, "source", None) or "—").strip()
    url = (getattr(item, "url", None) or "").strip()

    year = _extract_year(raw_title)
    score = _score_from_title(raw_title)

    lines = [title]
    if year:
        lines.append(f"Ano: {year}")
    if km:
        lines.append(f"KM: {km}")
    lines.append(f"Fonte: {src}")
    lines.append(f"Preço: {price_text}")
    lines.append(f"Score: {score}/100")
    if url:
        lines.append(url)

    text = sanitize_for_telegram("\n".join(lines))
    return _truncate(text, TELEGRAM_TEXT_MAX)


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
        full_text = _build_text(item)
        caption, remainder = _split(full_text, TELEGRAM_CAPTION_MAX)

        # Foto: deixa o Telegram buscar a URL (mais simples no manual_search)
        # Se quebrar por fetch, você ainda recebe o texto.
        if getattr(item, "thumbnail_url", None):
            try:
                await update.message.reply_photo(
                    photo=item.thumbnail_url,
                    caption=_truncate(caption, TELEGRAM_CAPTION_MAX),
                )
                if remainder.strip():
                    await update.message.reply_text(
                        _truncate(remainder.strip(), TELEGRAM_TEXT_MAX),
                        disable_web_page_preview=True,
                    )
                continue
            except Exception:
                # fallback pro texto
                pass

        await update.message.reply_text(full_text, disable_web_page_preview=True)
