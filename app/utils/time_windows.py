from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DayWindowUTC:
    """Janela [start_utc, end_utc) que representa um "dia" em um timezone local."""

    start_utc: datetime
    end_utc: datetime


def local_date(now_utc: datetime, tz_name: str) -> date:
    """Retorna a data local (YYYY-MM-DD) para um instante em UTC."""
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware (UTC)")
    tz = ZoneInfo(tz_name)
    return now_utc.astimezone(tz).date()


def day_window_utc(now_utc: datetime, tz_name: str) -> DayWindowUTC:
    """Calcula a janela de um dia local e converte para UTC.

    Retorna [start_utc, end_utc), onde start_utc e end_utc sao timezone-aware.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware (UTC)")

    tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(tz)
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    return DayWindowUTC(start_utc=start_utc, end_utc=end_utc)
