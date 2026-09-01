from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.utils.time_windows import day_window_utc, local_date


def test_local_date_requires_timezone_aware_input():
    with pytest.raises(ValueError):
        local_date(datetime(2026, 1, 1), "America/Sao_Paulo")


def test_local_date_converts_utc_to_local_calendar_day():
    now_utc = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
    assert local_date(now_utc, "America/Sao_Paulo").isoformat() == "2025-12-31"


def test_day_window_utc_requires_timezone_aware_input():
    with pytest.raises(ValueError):
        day_window_utc(datetime(2026, 1, 1), "America/Sao_Paulo")


def test_day_window_utc_spans_full_local_day():
    now_utc = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    window = day_window_utc(now_utc, "America/Sao_Paulo")
    assert window.start_utc < now_utc < window.end_utc
    assert (window.end_utc - window.start_utc).total_seconds() == 24 * 3600


def test_day_window_utc_boundaries_map_to_local_midnight():
    now_utc = datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    window = day_window_utc(now_utc, "America/Sao_Paulo")
    assert local_date(window.start_utc, "America/Sao_Paulo") == local_date(now_utc, "America/Sao_Paulo")
    assert local_date(window.end_utc, "America/Sao_Paulo") != local_date(now_utc, "America/Sao_Paulo")
