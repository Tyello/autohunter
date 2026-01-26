from __future__ import annotations

import re
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse

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


def _strip_query_fragment(url: str) -> str:
    """Remove querystring e fragment.

    Isso evita:
    - URLs gigantes no Telegram
    - tokens de tracking causando falsos positivos no matching
    """
    if not url:
        return ""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return url.split("#")[0].split("?")[0]


def _canonical_ml_url(external_id: str) -> str:
    """URL canônica curta para anúncios de veículos do Mercado Livre."""
    m = re.match(r"^MLB[-]?(\d+)$", (external_id or "").upper())
    if not m:
        return ""
    return f"https://carro.mercadolivre.com.br/MLB-{m.group(1)}-_JM"


def _normalize_listing_url(url: str, source: str | None, external_id: str | None) -> str:
    """Normaliza URLs antes de mandar pro Telegram.

    Regras:
    - Sempre remove ?query e #fragment
    - MercadoLivre: se tiver MLB id (external_id), usa URL canônica curta.
      Isso evita mandar URLs de tracking (click1...) para o usuário.
    """
    url = _clean_spaces(url or "")
    if not url:
        return ""

    src = (source or "").lower()
    if src == "mercadolivre":
        canonical = _canonical_ml_url(external_id or "")
        if canonical:
            return canonical

        # fallback: tenta extrair MLB-123... do path
        try:
            m = re.search(r"MLB-(\d+)", url)
            if m:
                return f"https://carro.mercadolivre.com.br/MLB-{m.group(1)}-_JM"
        except Exception:
            pass

    return _strip_query_fragment(url)


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
    title = _clean_spaces(getattr(listing, "title", None) or "Novo anúncio")
    loc = _clean_spaces(getattr(listing, "location", None) or "")
    url = _normalize_listing_url(
        getattr(listing, "url", None) or "",
        getattr(listing, "source", None) or "",
        getattr(listing, "external_id", None) or "",
    )
    price_text = format_price(getattr(listing, "price", None))

    year = _extract_year(title)
    score = _score_from_text(" ".join([title, loc]))

    # Se no futuro você salvar FIPE/score no banco, aqui já “aparece” automaticamente:
    fipe = getattr(listing, "fipe_price", None)
    if fipe is None and notification is not None:
        fipe = getattr(notification, "fipe_price", None)

    deal_score = getattr(listing, "deal_score", None)
    if deal_score is None and notification is not None:
        deal_score = getattr(notification, "deal_score", None)

    lines = [title]
    if year:
        lines.append(f"Ano: {year}")
    lines.append(f"Preço: {price_text}")
    if loc:
        lines.append(f"Local: {loc}")

    # diferencial: score (offline)
    lines.append(f"Score: {score}/100")

    # se você passar FIPE / deal_score, aparece
    if fipe is not None:
        try:
            lines.append(f"FIPE: {format_price(fipe)}")
        except Exception:
            lines.append(f"FIPE: {fipe}")
    if deal_score is not None:
        lines.append(f"Deal: {deal_score}")

    if url:
        lines.append(url)

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
        "User-Agent": "Mozilla/5.0 (X11; Linux arm64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
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

    full_text = _build_text(listing, notification=notification)
    caption, remainder = _split(full_text, TELEGRAM_CAPTION_MAX)
    caption = _truncate(caption, TELEGRAM_CAPTION_MAX)

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

    if remainder.strip():
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        extra = _truncate(remainder.strip(), TELEGRAM_TEXT_MAX)
        resp2 = requests.post(
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
    resp = requests.post(
        url,
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=15,
    )

    if resp.status_code >= 400:
        return False

    return True
