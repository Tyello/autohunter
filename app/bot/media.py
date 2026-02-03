from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import urlparse

from app.services.http_session import get_shared_session

# RPi-friendly guardrails
MAX_IMAGE_BYTES = 3_500_000  # ~3.5MB


def _infer_referer(url: str) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}/"
    except Exception:
        return None
    return None


def download_image_bytes(
    url: str,
    *,
    referer: str | None = None,
    timeout: int = 8,
) -> Optional[Tuple[bytes, str]]:
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
    }

    ref = referer or _infer_referer(url)
    if ref:
        headers["Referer"] = ref

    try:
        with get_shared_session("media").get(
            url,
            headers=headers,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        ) as r:
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
