from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session

from app.models.wishlist import Wishlist
from app.models.wishlist_token import WishlistToken


_STOPWORDS = {
    "de","da","do","das","dos","a","o","as","os","e","ou","em","no","na","nos","nas","para","por",
    "com","sem","um","uma","uns","umas","entre","ate","até","apartir","a partir","desde","ao","à",
    "ano","anos","modelo","versao","versão",
}

# years: 1900..2099
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


@dataclass(frozen=True)
class ReindexResult:
    wishlists_processed: int
    tokens_inserted: int


def extract_tokens(text: str) -> list[str]:
    """Extract stable tokens for inverted index. Conservative and language-agnostic."""
    text = (text or "").lower()
    # remove year numbers (they are filters, not match terms)
    text = _YEAR_RE.sub(" ", text)
    # normalize separators
    text = text.replace("-", " ").replace("_", " ").replace("/", " ")
    raw = _TOKEN_RE.findall(text)
    out: list[str] = []
    for t in raw:
        if len(t) < 2:
            continue
        if t in _STOPWORDS:
            continue
        # avoid pure digits (after year removal)
        if t.isdigit():
            continue
        out.append(t)
    # de-dup but keep order
    seen=set()
    uniq=[]
    for t in out:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    return uniq[:12]  # cap to keep index tight


def rebuild_tokens_for_wishlist(db: Session, wishlist: Wishlist) -> int:
    """Rebuild token rows for a single wishlist. Returns tokens inserted."""
    tokens = extract_tokens(wishlist.query)

    db.execute(delete(WishlistToken).where(WishlistToken.wishlist_id == wishlist.id))

    if not tokens:
        return 0

    rows = [WishlistToken(wishlist_id=wishlist.id, token=t) for t in tokens]
    db.add_all(rows)
    return len(rows)


def reindex_active_wishlists(db: Session, batch_size: int = 200) -> ReindexResult:
    """Rebuild token index for all active wishlists."""
    q = select(Wishlist).where(Wishlist.is_active.is_(True)).order_by(Wishlist.created_at.asc())
    wishlists = db.execute(q).scalars().all()

    processed = 0
    inserted = 0

    for i, w in enumerate(wishlists, start=1):
        inserted += rebuild_tokens_for_wishlist(db, w)
        processed += 1
        if processed % batch_size == 0:
            db.commit()

    db.commit()
    return ReindexResult(wishlists_processed=processed, tokens_inserted=inserted)
