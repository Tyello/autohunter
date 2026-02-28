from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class MarketStats:
    """Market statistics for a cohort (make+model+year).

    Notes:
    - make/model are expected to be normalized (lowercase) at storage/query time.
    - prices are Decimals (BRL).
    """

    make: str
    model: str
    year: int
    median_price: Decimal
    p25_price: Decimal | None = None
    p75_price: Decimal | None = None
    sample_size: int = 0


@dataclass(frozen=True)
class ScoreResult:
    total: int
    components: dict[str, int]
    caps_applied: list[str]
    reasons: list[str]
    delta_vs_median_pct: float | None = None
    market_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": int(self.total),
            "components": {k: int(v) for k, v in (self.components or {}).items()},
            "caps_applied": list(self.caps_applied or []),
            "reasons": list(self.reasons or []),
            "delta_vs_median_pct": self.delta_vs_median_pct,
            "market_context": self.market_context,
        }

    @staticmethod
    def from_dict(d: dict[str, Any] | None) -> "ScoreResult" | None:
        if not d:
            return None
        return ScoreResult(
            total=int(d.get("total") or 0),
            components=dict(d.get("components") or {}),
            caps_applied=list(d.get("caps_applied") or []),
            reasons=list(d.get("reasons") or []),
            delta_vs_median_pct=d.get("delta_vs_median_pct"),
            market_context=d.get("market_context"),
        )
