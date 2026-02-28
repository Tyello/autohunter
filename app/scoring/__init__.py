"""Scoring package (v2).

Goal: keep scoring deterministic, explainable and cheap to compute on limited
hardware (Raspberry Pi).

The v2 score is component-based and produces a persisted breakdown used by the
Telegram message formatter ("decisão em 3 segundos").
"""

from .types import MarketStats, ScoreResult
from .score_v2 import score_ad

__all__ = ["MarketStats", "ScoreResult", "score_ad"]
