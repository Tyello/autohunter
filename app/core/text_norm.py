"""Text normalization utilities for lightweight matching on low-power hardware.

Design goals:
- Deterministic
- Fast (no heavy NLP)
- Works well for Portuguese listings mixed with abbreviations (SI, VTi, EG6, etc.)
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RE_WS = re.compile(r"\s+")


@lru_cache(maxsize=4096)
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


STOPWORDS: frozenset[str] = frozenset({
    "a","o","os","as","de","do","da","dos","das","e","em","no","na","nos","nas",
    "para","por","com","sem","ate","até","entre","apenas","so","só","somente",
    "partir","apartir","desde","ano","year","anos","valor","preco","preço","precos","preços",
})

def expand_alphanum_pairs(ts: list[str]) -> set[str]:
    out: set[str] = set()
    for i in range(len(ts) - 1):
        a = ts[i]
        b = ts[i + 1]
        if not a or not b:
            continue
        if a.isalpha() and len(a) <= 3 and b.isdigit() and len(b) <= 4:
            out.add(a + b)
        if a.isdigit() and len(a) <= 4 and b.isalpha() and len(b) <= 3:
            out.add(a + b)
    return out
