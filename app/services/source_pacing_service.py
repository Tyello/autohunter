"""Pacing opcional por source: rajadas menores, mais espacadas e irregulares.

Tudo vem de `source_configs.extra` e e DESLIGADO por padrao (sem chaves = comportamento
atual). Exemplo para o mercadolivre (3 buscas por rodada, pausa de 40-150s entre buscas,
ordem aleatoria, horario de rodada variando +-25% e cursor de rotacao):

    {"pacing": {"inter_group_delay_s": [40, 150], "shuffle_groups": true,
                "max_groups_per_run": 3, "sched_jitter_pct": 25}}

Com `max_groups_per_run`, cada rodada atende as buscas atendidas ha mais tempo (cursor em
`AppKV`), entao todas sao visitadas ao longo de varias rodadas; reduza `sched_minutes` para
manter a cobertura (ex.: 10 buscas / 3 por rodada = 4 rodadas -> sched 180 = ciclo de 12h).
O delay entre buscas so vale nas sources que rodam grupos em sequencia (mercadolivre, olx,
webmotors).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

CURSOR_KV_PREFIX = "source_group_cursor:"

_MAX_DELAY_S = 600.0
_MAX_JITTER_PCT = 50.0


@dataclass(frozen=True, slots=True)
class Pacing:
    inter_group_delay_s: Tuple[float, float] = (0.0, 0.0)
    shuffle_groups: bool = False
    max_groups_per_run: int = 0
    sched_jitter_pct: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(
            self.inter_group_delay_s[1] > 0
            or self.shuffle_groups
            or self.max_groups_per_run > 0
            or self.sched_jitter_pct > 0
        )


def read_pacing(extra: Optional[Mapping[str, Any]]) -> Pacing:
    raw = (extra or {}).get("pacing") if isinstance(extra, Mapping) else None
    if not isinstance(raw, Mapping):
        return Pacing()

    lo, hi = 0.0, 0.0
    delay = raw.get("inter_group_delay_s")
    if isinstance(delay, (list, tuple)) and len(delay) == 2:
        try:
            a, b = float(delay[0]), float(delay[1])
            lo, hi = sorted((max(0.0, a), max(0.0, b)))
        except (TypeError, ValueError):
            lo, hi = 0.0, 0.0
    elif isinstance(delay, (int, float)) and not isinstance(delay, bool):
        lo = hi = max(0.0, float(delay))

    try:
        max_groups = max(0, int(raw.get("max_groups_per_run") or 0))
    except (TypeError, ValueError):
        max_groups = 0
    try:
        jitter = min(_MAX_JITTER_PCT, max(0.0, float(raw.get("sched_jitter_pct") or 0.0)))
    except (TypeError, ValueError):
        jitter = 0.0

    return Pacing(
        inter_group_delay_s=(min(lo, _MAX_DELAY_S), min(hi, _MAX_DELAY_S)),
        shuffle_groups=bool(raw.get("shuffle_groups")),
        max_groups_per_run=max_groups,
        sched_jitter_pct=jitter,
    )


def jittered_minutes(minutes: int, last_effective_run_at: Optional[datetime], pct: float) -> int:
    """Intervalo efetivo entre rodadas, variando +-pct%.

    O desvio e deterministico a partir do ultimo `last_effective_run_at`: todos os ticks que
    avaliam a mesma rodada chegam ao mesmo horario, mas cada rodada tem um intervalo diferente.
    """
    if minutes <= 0 or pct <= 0 or last_effective_run_at is None:
        return minutes
    digest = hashlib.sha256(last_effective_run_at.astimezone(timezone.utc).isoformat().encode()).digest()
    frac = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF  # 0..1
    return max(1, round(minutes * (1.0 + (pct / 100.0) * (2.0 * frac - 1.0))))


def pick_groups(
    urls: Sequence[str],
    *,
    last_served: Mapping[str, str],
    max_groups: int,
) -> List[str]:
    """Ate `max_groups` buscas, priorizando as nunca atendidas / atendidas ha mais tempo."""
    if max_groups <= 0 or len(urls) <= max_groups:
        return list(urls)
    # nunca atendida = "" (ordena antes de qualquer data ISO); empate mantem a ordem original.
    ranked = sorted(range(len(urls)), key=lambda i: (last_served.get(urls[i]) or "", i))
    return [urls[i] for i in sorted(ranked[:max_groups])]


def order_groups(urls: Sequence[str], *, shuffle: bool, rng: Optional[random.Random] = None) -> List[str]:
    out = list(urls)
    if shuffle:
        (rng or random).shuffle(out)
    return out


def delay_seconds(pacing: Pacing, rng: Optional[random.Random] = None) -> float:
    lo, hi = pacing.inter_group_delay_s
    if hi <= 0:
        return 0.0
    return (rng or random).uniform(lo, hi)


def mark_served(cursor: Optional[Mapping[str, Any]], urls: Sequence[str], *, now: datetime, keep: Sequence[str]) -> Dict[str, str]:
    """Atualiza o cursor com as buscas atendidas e descarta URLs que nao existem mais."""
    alive = set(keep)
    out = {u: str(v) for u, v in (cursor or {}).items() if u in alive}
    stamp = now.astimezone(timezone.utc).isoformat()
    for u in urls:
        out[u] = stamp
    return out
