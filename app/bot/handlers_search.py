from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.search_service import manual_search
from app.bot.formatting import format_price
from app.bot.text_sanitize import sanitize_for_telegram
from app.bot.listing_sender import send_listing_message
from app.core.enthusiast import compute_enthusiast_score, detect_signals
from app.models.source_run import SourceRun


# On Raspberry Pi, keep /buscar default fast (HTTP-first) unless the user forces sources via @...
DEFAULT_MANUAL_SOURCES = ["olx", "mercadolivre", "chavesnamao", "gogarage", "mobiauto"]


TELEGRAM_TEXT_MAX = 4096


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


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


def _auction_label(signals) -> str | None:
    if not signals:
        return None
    if getattr(signals, "is_auction", False) and getattr(signals, "is_salvage", False):
        return "⚠️ LEILÃO / SINISTRO"
    if getattr(signals, "is_auction", False):
        return "⚠️ LEILÃO"
    if getattr(signals, "is_salvage", False):
        return "⚠️ SINISTRO / SUCATA"
    return None


def _parse_query_sources(raw: str) -> tuple[str, list[str]]:
    """Parse /buscar syntax.

    Examples:
      /buscar polo @icarros
      /buscar civic si 1998 @olx @gogarage

    Returns:
      (clean_query, sources)
    """
    toks = (raw or "").split()
    sources: list[str] = []
    terms: list[str] = []
    for tok in toks:
        if tok.startswith("@") and len(tok) > 1:
            # allow comma-separated: @icarros,kavak
            for s in tok[1:].split(","):
                s2 = (s or "").strip().lower()
                if s2:
                    sources.append(s2)
            continue
        terms.append(tok)
    # dedupe sources while keeping order
    seen = set()
    uniq: list[str] = []
    for s in sources:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return " ".join(terms).strip(), uniq


def _build_text(item) -> str:
    raw_title = (getattr(item, "title", None) or "Anúncio").strip()
    title, km = _clean_title_and_extract_km(raw_title)

    # If the scraper already extracted KM/year, prefer that (more reliable than parsing title).
    if not km:
        km_field = getattr(item, "km", None)
        if km_field:
            km = str(km_field).strip()

    price_text = format_price(getattr(item, "price", None))
    src = (getattr(item, "source", None) or "—").strip()
    url = (getattr(item, "url", None) or "").strip()
    loc = (getattr(item, "location", None) or "").strip()

    signals = detect_signals(raw_title, loc)
    score = compute_enthusiast_score(raw_title, loc)

    lines = [title]
    year_field = getattr(item, "year", None)
    if year_field:
        try:
            lines.append(f"Ano: {int(year_field)}")
        except Exception:
            lines.append(f"Ano: {str(year_field).strip()}")
    elif signals.year:
        lines.append(f"Ano: {signals.year}")
    if km:
        lines.append(f"KM: {km}")
    lab = _auction_label(signals)
    if lab:
        lines.append(lab)
    lines.append(f"Fonte: {src}")
    lines.append(f"Preço: {price_text}")
    if loc:
        lines.append(f"Local: {loc}")
    lines.append(f"Score: {score}/100")
    if url:
        lines.append(url)

    text = sanitize_for_telegram("\n".join(lines))
    return _truncate(text, TELEGRAM_TEXT_MAX)


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text("Use: /buscar <termos> [@fonte]\nEx: /buscar civic si 1998 @olx")
        return

    query, sources = _parse_query_sources(raw)
    if not query:
        await update.message.reply_text("Use: /buscar <termos> [@fonte]\nEx: /buscar civic si 1998 @olx")
        return

    # Default to fast sources unless user explicitly chooses.
    sources_effective = sources or DEFAULT_MANUAL_SOURCES

    with SessionLocal() as db:
        _user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        results = manual_search(db, query=query, limit=5, sources=sources_effective)

        # If user forced sources and got nothing, surface the last run statuses.
        if not results and sources:
            # latest run per source for this query
            rows = (
                db.query(SourceRun)
                .filter(SourceRun.kind == "manual")
                .filter(SourceRun.query == query)
                .filter(SourceRun.source.in_(sources))
                .order_by(SourceRun.created_at.desc())
                .limit(20)
                .all()
            )
            if rows:
                seen = set()
                diag_lines = []
                for r in rows:
                    if r.source in seen:
                        continue
                    seen.add(r.source)
                    status = (r.status or "").lower()
                    if status in ("success",) and (r.items_found or 0) > 0:
                        continue
                    err = (r.error or "").strip()
                    if "Playwright disabled" in err or "playwright" in err.lower():
                        err = "browser desabilitado (PLAYWRIGHT_SOURCES)"
                    elif status == "blocked":
                        err = "bloqueado (anti-bot)"
                    elif status == "skipped":
                        err = err or "skipped"
                    elif status == "error":
                        err = "erro na coleta"
                    diag_lines.append(f"- {r.source}: {status or '—'}{(' | ' + err) if err else ''}")

                if diag_lines:
                    await update.message.reply_text(
                        sanitize_for_telegram(
                            "Nada encontrado agora. Diagnóstico:\n" + "\n".join(diag_lines[:8])
                        ),
                        disable_web_page_preview=True,
                    )
                    return

    if not results:
        await update.message.reply_text("Nada encontrado agora.")
        return

    for item in results:
        await send_listing_message(
            update,
            text=_build_text(item),
            thumbnail_url=getattr(item, "thumbnail_url", None),
            referer_url=getattr(item, "url", None),
            disable_web_page_preview=True,
            prefer_photo_url=True,
            allow_local_image_download=False,
        )
