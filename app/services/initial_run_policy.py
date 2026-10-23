"""Politica da "primeira busca" disparada ao criar uma wishlist.

Evita bater varias vezes seguidas na mesma source:
- debounce: o job de primeira busca nasce com `run_at` no futuro (90-120s por default), entao
  criacoes proximas caem no mesmo job (dedupe por (source, queue)) em vez de uma varredura cada;
- cooldown: se a source rodou ha menos de N minutos, nao enfileira; a busca nova espera o
  proximo ciclo normal e ja recebe resultado imediato do estoque (ver backfill).

Funcoes puras: o acesso a banco/fila fica em `wishlists_service` e `source_execution_service`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.settings import settings

INITIAL_RUN_REASON = "wishlist_created"
# Jobs da fila nao carregam motivo; a prioridade distingue primeira busca (1) do ciclo normal (0).
INITIAL_RUN_PRIORITY = 1

# Sources sensiveis a anti-bot ficam mais conservadoras que o default global.
_DEFAULT_COOLDOWN_MINUTES_BY_SOURCE = {"mercadolivre": 60}


@dataclass(frozen=True)
class InitialRunPolicy:
    cooldown_minutes: int
    debounce_min_seconds: int
    debounce_max_seconds: int


def _non_negative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def read_initial_run_policy(source: str, extra: Optional[dict]) -> InitialRunPolicy:
    src = (source or "").strip().lower()
    cooldown = _non_negative_int(settings.initial_run_cooldown_minutes)
    if cooldown is None:
        cooldown = 30
    cooldown = _DEFAULT_COOLDOWN_MINUTES_BY_SOURCE.get(src, cooldown)

    override = (extra or {}).get("initial_run") if isinstance(extra, dict) else None
    if isinstance(override, dict):
        value = _non_negative_int(override.get("cooldown_minutes"))
        if value is not None:
            cooldown = value

    dmin = _non_negative_int(settings.initial_run_debounce_min_seconds)
    dmax = _non_negative_int(settings.initial_run_debounce_max_seconds)
    dmin = 90 if dmin is None else dmin
    dmax = 120 if dmax is None else dmax
    return InitialRunPolicy(cooldown_minutes=cooldown, debounce_min_seconds=dmin, debounce_max_seconds=max(dmin, dmax))


def debounce_delay_seconds(policy: InitialRunPolicy, rng: Optional[random.Random] = None) -> int:
    """Atraso aleatorio dentro da janela de debounce (jitter evita rajadas sincronizadas)."""
    r = rng or random
    return int(r.randint(policy.debounce_min_seconds, policy.debounce_max_seconds))


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def cooldown_remaining(last_effective_run_at: Optional[datetime], now: datetime, policy: InitialRunPolicy) -> timedelta:
    """Quanto falta para a source poder receber uma primeira busca (0 = liberado)."""
    if last_effective_run_at is None or policy.cooldown_minutes <= 0:
        return timedelta(0)
    elapsed = _as_utc(now) - _as_utc(last_effective_run_at)
    remaining = timedelta(minutes=policy.cooldown_minutes) - elapsed
    return remaining if remaining > timedelta(0) else timedelta(0)


def is_initial_run_reason(reason: Optional[str]) -> bool:
    return (reason or "").strip().lower() == INITIAL_RUN_REASON


def run_reason_for_job_priority(priority: Optional[int]) -> Optional[str]:
    try:
        return INITIAL_RUN_REASON if int(priority or 0) >= INITIAL_RUN_PRIORITY else None
    except (TypeError, ValueError):
        return None
