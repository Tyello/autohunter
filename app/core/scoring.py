"""Deal scoring helpers (fast + explainable).

This is deliberately simple: it gives the user a 'why' for an alert:
- how far from FIPE
- how fresh the listing is
- whether it matches a 'enthusiast vibe' (older + sporty keywords)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class DealScore:
    score_0_100: int
    pct_vs_fipe: float | None
    freshness_hours: float | None
    notes: tuple[str, ...] = ()


def _clamp(n: float, lo: float, hi: float) -> float:
    return lo if n < lo else hi if n > hi else n


def compute_deal_score(
    price: float | None,
    fipe: float | None,
    created_at: datetime | None,
    *,
    now: datetime | None = None,
) -> DealScore:
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []

    pct = None
    if price and fipe and fipe > 0:
        pct = (price - fipe) / fipe * 100.0  # +10% means 10% acima da FIPE
        if pct <= -10:
            notes.append("bem abaixo da FIPE")
        elif pct <= -5:
            notes.append("abaixo da FIPE")
        elif pct >= 15:
            notes.append("bem acima da FIPE")

    freshness_h = None
    if created_at:
        dt = created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        freshness_h = max(0.0, (now - dt).total_seconds() / 3600.0)

    # base score
    score = 50.0

    # FIPE impact: -20..+20
    if pct is not None:
        # negative pct improves score, positive worsens
        score += _clamp(-pct, -20.0, 20.0)

    # freshness impact: 0..+20 (newer => higher)
    if freshness_h is not None:
        freshness_bonus = _clamp((72.0 - freshness_h) / 72.0 * 20.0, 0.0, 20.0)
        score += freshness_bonus

    score = int(round(_clamp(score, 0.0, 100.0)))
    return DealScore(score_0_100=score, pct_vs_fipe=pct, freshness_hours=freshness_h, notes=tuple(notes))
