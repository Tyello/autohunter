from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def pick_from_srcset(
    srcset: str,
    *,
    max_width: int | None = 2048,
    prefer_last: bool = False,
) -> Optional[str]:
    """Pick a good URL from a srcset string."""
    if not srcset:
        return None

    parts = [p.strip() for p in srcset.split(",") if p.strip()]
    if not parts:
        return None

    if prefer_last:
        return parts[-1].split()[0].strip() or None

    candidates: list[tuple[int, str]] = []
    for part in parts:
        bits = part.split()
        url = bits[0].strip()
        size = 0
        if len(bits) >= 2:
            token = bits[1].strip().lower()
            if token.endswith("w"):
                try:
                    size = int(token[:-1])
                except Exception:
                    size = 0
            elif token.endswith("x"):
                try:
                    size = int(float(token[:-1]) * 1000)
                except Exception:
                    size = 0
        candidates.append((size, url))

    if not candidates:
        return None

    if max_width is None:
        return candidates[-1][1]

    candidates.sort(key=lambda x: x[0] or 0)
    under = [c for c in candidates if c[0] and c[0] <= max_width]
    if under:
        return under[-1][1]
    return candidates[-1][1]


def normalize_asset_url(raw: str, base_url: Optional[str] = None) -> Optional[str]:
    if not raw:
        return None
    u = raw.strip()
    if not u or u.startswith("data:"):
        return None
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/") and base_url:
        u = urljoin(base_url, u)
    return u
