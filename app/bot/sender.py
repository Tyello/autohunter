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
    if not url:
        return ""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return url.split("#")[0].split("?")[0]


def _is_ml_tracking(url: str) -> bool:
    if not url:
        return False
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").lower()
        if "mercadolivre.com.br" not in host:
            return False
        if host.startswith("click") or host.startswith("clk"):
            return True
        if "brand_ads/clicks" in path:
            return True
    except Exception:
        pass
    return False


def _canonical_ml_url(external_id: str) -> str:
    m = re.match(r"^MLB(\d+)$", (external_id or "").upper())
    if not m:
        return ""
    # curto e estável para veículos
    return f"https://carro.mercadolivre.com.br/MLB-{m.group(1)}-_JM"


def _clean_url_for_telegram(listing) -> str:
    """Evita mandar URL gigantes (tracking) que quebram texto/caption e confundem matching."""
    url = (getattr(listing, "url", None) or "").strip()
    if not url:
        return ""

    # completa esquema
    if url.startswith("//"):
        url = "https:" + url
    if url and not url.startswith("http"):
        url = "https://" + url.lstrip("/")

    source = (getattr(listing, "source", None) or "").lower()
    external_id = getattr(listing, "external_id", None) or ""

    # Mercado Livre: troca tracking por URL canônica curta
    if source == "mercadolivre" and (_is_ml_tracking(url) or len(url) > 300):
        canon = _canonical_ml_url(external_id)
        if canon:
            return canon

    # padrão: remove query/fragment (reduz demais o tamanho)
    cleaned = _strip_query_fragment(url)

    # se ainda estiver absurdo e for ML com id, força canônica
    if source == "mercadolivre" and len(cleaned) > 300:
        canon = _canonical_ml_url(external_id)
        if canon:
            return canon

    return cleaned


def _build_text(listing) -> str:
    title = _clean_spaces(listing.title or "Novo anúncio")
    price_text = format_price(listing.price)
    loc = _clean_spaces(getattr(listing, "location", None) or "")
    url = _clean_url_for_telegram(listing)

    lines = [title]
    lines.append(f"Preço: {price_text}")
    if loc:
        lines.append(f"Local: {loc}")
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

    # Foto enviada com caption curta. Se sobrou texto, envia como follow-up (capado)
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
