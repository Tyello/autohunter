from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session

from app.core.text_norm import tokens as tokenize, STOPWORDS as _STOPWORDS
from app.models.wishlist import Wishlist
from app.models.wishlist_token import WishlistToken



_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


@dataclass(frozen=True)
class ReindexResult:
    wishlists_processed: int
    tokens_inserted: int


@dataclass(frozen=True)
class CandidateStats:
    listings: int
    candidates_total: int
    candidates_p50: int
    candidates_p95: int


def extract_tokens(text: str) -> list[str]:
    text = (text or "").lower()
    text = _YEAR_RE.sub(" ", text)

    raw = tokenize(text)
    out: list[str] = []
    for t in raw:
        if not t or len(t) < 2:
            continue
        if t in _STOPWORDS:
            continue
        if t.isdigit():
            continue
        out.append(t)

    seen=set()
    uniq=[]
    for t in out:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)

    return uniq[:12]


def rebuild_tokens_for_wishlist(db: Session, wishlist: Wishlist) -> int:
    tokens = extract_tokens(wishlist.query)
    db.execute(delete(WishlistToken).where(WishlistToken.wishlist_id == wishlist.id))
    if not tokens:
        return 0
    db.add_all([WishlistToken(wishlist_id=wishlist.id, token=t) for t in tokens])
    return len(tokens)


def reindex_active_wishlists(db: Session, batch_size: int = 200) -> ReindexResult:
    q = select(Wishlist).where(Wishlist.is_active.is_(True)).order_by(Wishlist.created_at.asc())
    wishlists = db.execute(q).scalars().all()

    processed = 0
    inserted = 0
    for w in wishlists:
        inserted += rebuild_tokens_for_wishlist(db, w)
        processed += 1
        if processed % batch_size == 0:
            db.commit()
    db.commit()
    return ReindexResult(wishlists_processed=processed, tokens_inserted=inserted)


def candidate_wishlist_ids_for_listing_tokens(
    db: Session,
    listing_tokens: Sequence[str],
    *,
    min_overlap: int = 2,
    max_candidates: int = 500,
) -> list:
    toks = [t for t in listing_tokens if t]
    if not toks:
        return []
    # group by wishlist_id, count overlaps
    q = (
        select(WishlistToken.wishlist_id, func.count(WishlistToken.token).label("c"))
        .where(WishlistToken.token.in_(toks))
        .group_by(WishlistToken.wishlist_id)
        .having(func.count(WishlistToken.token) >= int(min_overlap))
        .order_by(func.count(WishlistToken.token).desc())
        .limit(int(max_candidates))
    )
    rows = db.execute(q).all()
    return [r[0] for r in rows]


def compute_candidate_stats(counts: Sequence[int]) -> CandidateStats:
    if not counts:
        return CandidateStats(listings=0, candidates_total=0, candidates_p50=0, candidates_p95=0)
    xs = sorted(int(x) for x in counts)
    total = sum(xs)
    def pct(p: float) -> int:
        if not xs:
            return 0
        k = max(0, min(len(xs)-1, int(math.ceil((p/100.0)*len(xs))) - 1))
        return xs[k]
    import math
    return CandidateStats(
        listings=len(xs),
        candidates_total=total,
        candidates_p50=pct(50),
        candidates_p95=pct(95),
    )
