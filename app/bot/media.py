from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import urlparse

from app.services.http_session import get_shared_session

# RPi-friendly guardrails
MAX_IMAGE_BYTES = 3_500_000  # ~3.5MB


_EXT_TO_CTYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _infer_image_ctype(url: str, header_ctype: str | None, head: bytes) -> str | None:
    """Infer a safe image Content-Type.

    Some CDNs (incl. Cloudflare) occasionally return `application/octet-stream` for
    images (especially WEBP). Telegram rejects non-image content-types when we upload.
    """
    ct = (header_ctype or "").split(";", 1)[0].strip().lower()
    if ct.startswith("image/"):
        return ct

    # Signature-based sniffing
    if head.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    # WEBP: RIFF....WEBP
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"

    # Extension fallback
    try:
        p = urlparse(url)
        path = (p.path or "").lower()
        for ext, ect in _EXT_TO_CTYPE.items():
            if path.endswith(ext):
                return ect
    except Exception:
        return None

    return None


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

    # Always reduce referer to origin to maximize CDN acceptance.
    ref = _infer_referer(referer) if referer else None
    ref = ref or _infer_referer(url)
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
            header_ctype = (r.headers.get("Content-Type") or "")

            buf = bytearray()
            head = b""
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                if not head:
                    head = chunk[:512]
                    # Quick reject for HTML error pages
                    h = head.lstrip()[:20].lower()
                    if h.startswith(b"<!") or h.startswith(b"<html") or h.startswith(b"<script"):
                        return None

                buf.extend(chunk)
                if len(buf) > MAX_IMAGE_BYTES:
                    return None

            if not buf:
                return None

            ctype = _infer_image_ctype(url, header_ctype, head or bytes(buf[:512]))
            if not ctype:
                return None

            return bytes(buf), ctype
    except Exception:
        return None
