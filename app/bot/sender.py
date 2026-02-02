from __future__ import annotations

import json
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



def _infer_referer(url: str) -> str:
    try:
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}/"
    except Exception:
        pass
    return "https://www.chavesnamao.com.br/"


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
    raw_title = _clean_spaces(getattr(listing, "title", None) or "Novo anúncio")
    title, km = _clean_title_and_extract_km(raw_title)
    loc = _clean_location(getattr(listing, "location", None) or "")
    url = _normalize_listing_url(
        getattr(listing, "url", None) or "",
        getattr(listing, "source", None) or "",
        getattr(listing, "external_id", None) or "",
    )
    price_text = format_price(getattr(listing, "price", None))

    year = _extract_year(raw_title)
    score = _score_from_text(" ".join([raw_title, loc]))

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
    if km:
        lines.append(f"KM: {km}")
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

    # Não imprimimos URL no texto para economizar espaço.
    # O link vai no botão "Abrir anúncio" (Inline Keyboard).

    text = "\n".join(lines)
    text = sanitize_for_telegram(text)
    return _truncate(text, TELEGRAM_TEXT_MAX)


def _download_image_bytes(url: str, *, referer: str | None = None, timeout: int = 8) -> Optional[Tuple[bytes, str]]:
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
        "Referer": (referer or _infer_referer(url)),
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

    open_url = _normalize_listing_url(
        getattr(listing, "url", None) or "",
        getattr(listing, "source", None) or None,
        getattr(listing, "external_id", None) or "",
    )
    reply_markup = (
        json.dumps({"inline_keyboard": [[{"text": "Abrir anúncio", "url": open_url}]]}, ensure_ascii=False)
        if open_url
        else None
    )

    if getattr(listing, "thumbnail_url", None):
        img = _download_image_bytes(listing.thumbnail_url, referer=getattr(listing, 'url', None))
        if img:
            img_bytes, ctype = img
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, **({"reply_markup": reply_markup} if reply_markup else {})},
                files={"photo": ("thumb", img_bytes, ctype)},
                timeout=20,
            )

            if resp.status_code < 400:
                sent_photo = True

    if not sent_photo:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
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
