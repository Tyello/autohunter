"""Helpers for a compact Telegram UX.

Instead of printing huge URLs in message bodies/captions, we attach a
single URL button (Inline Keyboard): "Abrir anúncio".

This module is stdlib-only so it can be used by both:
  - bot handlers (python-telegram-bot)
  - scheduler sender (raw Telegram HTTP)
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse, urlunparse


def strip_query_fragment(url: str) -> str:
    """Remove querystring e fragment (#) para reduzir tamanho e tracking."""
    if not url:
        return ""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    except Exception:
        return url.split("#")[0].split("?")[0]


def canonical_ml_url(external_id: str) -> str:
    """URL canônica curta para Mercado Livre (veículos)."""
    m = re.match(r"^MLB[-]?(\d+)$", (external_id or "").upper())
    if not m:
        return ""
    return f"https://carro.mercadolivre.com.br/MLB-{m.group(1)}-_JM"


def normalize_listing_url(url: str, source: str | None = None, external_id: str | None = None) -> str:
    """Normaliza a URL do anúncio para ficar curta e estável."""
    u = (url or "").strip()
    if not u:
        return ""

    src = (source or "").lower().strip()
    if src == "mercadolivre":
        canonical = canonical_ml_url(external_id or "")
        if canonical:
            return canonical

        # fallback: extrai MLB-123... do path, se existir
        try:
            m = re.search(r"MLB-(\d+)", u)
            if m:
                return f"https://carro.mercadolivre.com.br/MLB-{m.group(1)}-_JM"
        except Exception:
            pass

    return strip_query_fragment(u)


def open_ad_reply_markup_json(url: str, button_text: str = "Abrir anúncio") -> str:
    """Return reply_markup JSON for Telegram HTTP API."""
    u = (url or "").strip()
    if not u:
        return ""
    payload = {"inline_keyboard": [[{"text": button_text, "url": u}]]}
    return json.dumps(payload, ensure_ascii=False)
