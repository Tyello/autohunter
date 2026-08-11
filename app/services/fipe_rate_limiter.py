from __future__ import annotations

import threading
import time


class FipeRateLimiter:
    """Limitador de taxa compartilhado entre múltiplos workers do crawler FIPE.

    Garante que a cadência agregada de requisições emitidas por todos os workers
    nunca ultrapasse rate_limit_ms entre requisições consecutivas (mesma garantia
    que o antigo _throttle() por-instância, agora centralizada). Escala o throttle
    em 429 e recupera gradualmente após sucessos consecutivos, para que um burst
    de 429 no início de um crawl de horas não deixe o resto do crawl permanentemente
    lento.
    """

    def __init__(
        self,
        *,
        rate_limit_ms: int,
        max_throttle_ms: int,
        recovery_after_successes: int,
    ) -> None:
        self._rate_limit_ms = int(rate_limit_ms)
        self._max_throttle_ms = int(max_throttle_ms)
        self._recovery_after_successes = max(1, int(recovery_after_successes))
        self._current_throttle_ms = self._rate_limit_ms
        self._last_request_time = 0.0
        self._consecutive_successes = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            earliest_start = self._last_request_time + (self._current_throttle_ms / 1000)
            start = max(now, earliest_start)
            self._last_request_time = start

        wait_s = start - time.monotonic()
        if wait_s > 0:
            time.sleep(wait_s)

    def on_success(self) -> None:
        with self._lock:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._recovery_after_successes:
                self._consecutive_successes = 0
                floor = self._rate_limit_ms
                if self._current_throttle_ms > floor:
                    self._current_throttle_ms = floor + (self._current_throttle_ms - floor) // 2

    def on_429(self) -> None:
        with self._lock:
            self._consecutive_successes = 0
            self._current_throttle_ms = min(self._current_throttle_ms * 2, self._max_throttle_ms)

    @property
    def current_throttle_ms(self) -> int:
        with self._lock:
            return self._current_throttle_ms
