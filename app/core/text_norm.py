"""Text normalization utilities for lightweight matching on low-power hardware.

Design goals:
- Deterministic
- Fast (no heavy NLP)
- Works well for Portuguese listings mixed with abbreviations (SI, VTi, EG6, etc.)
"""

from __future__ import annotations

import re
import unicodedata

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, remove accents, convert punctuation to spaces, collapse whitespace."""
    if not text:
        return ""
    text = text.strip().lower()
    # remove accents
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # convert punctuation/symbols to spaces, keep alnum
    text = _RE_NON_ALNUM.sub(" ", text)
    text = _RE_WS.sub(" ", text).strip()
    return text


def tokens(text: str) -> list[str]:
    """Tokenize normalized text into words."""
    n = normalize(text)
    return n.split() if n else []
