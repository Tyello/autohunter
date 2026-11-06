"""Worker thread helpers for scheduler.

Daemon threads that run a function on a fixed interval, respecting graceful shutdown.
Uses the shutdown event from app.core.shutdown for interruptible waits.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from app.core.shutdown import is_shutdown_requested, _shutdown_event


# Module-level registry of active worker threads
WORKER_THREADS: list[threading.Thread] = []


def _next_wait(seconds: int, idle_streak: int, max_idle_seconds: int | None) -> int:
    """Intervalo até a próxima chamada de fn().

    Sem teto (`max_idle_seconds` None) ou sem ociosidade (`idle_streak` 0),
    devolve `seconds`. Com ociosidade, dobra por streak até o teto. O intervalo
    ocioso nunca fica abaixo de `seconds` (teto configurado menor que o base).
    """
    if max_idle_seconds is None or idle_streak <= 0:
        return seconds
    # Expoente limitado: o teto já domina bem antes, e evita inteiros gigantes em ociosidade longa.
    return max(seconds, min(seconds * (2 ** min(idle_streak, 16)), max_idle_seconds))


def start_worker_thread(
    fn: Callable[[], None],
    *,
    seconds: int,
    name: str,
    max_idle_seconds: int | None = None,
) -> threading.Thread:
    """Start a daemon thread that calls fn() repeatedly on an interval.

    The thread checks for shutdown signals and waits interruptibly between calls.
    Exceptions in fn() are logged simply and do not kill the thread.

    Polling adaptativo: se `max_idle_seconds` for dado e fn() retornar exatamente
    `False` (ocioso), o intervalo cresce (`seconds * 2^streak`, limitado a
    `max_idle_seconds`). Qualquer outro retorno ou exceção volta ao intervalo base.

    Args:
        fn: Callable to invoke repeatedly (must accept no arguments).
        seconds: Interval in seconds between calls.
        name: Human-readable thread name.
        max_idle_seconds: Teto do intervalo quando fn() retorna False. None desativa.

    Returns:
        The started threading.Thread (already running).
    """
    def worker_loop():
        idle_streak = 0
        while not is_shutdown_requested():
            try:
                result = fn()
            except Exception as exc:
                # Log simply without derailing the loop
                print(
                    f"[{name}] suppressed_exception stage=worker.fn "
                    f"exc_type={type(exc).__name__} "
                    f"message={str(exc)[:280]}",
                    flush=True,
                )
                result = None

            if max_idle_seconds is not None and result is False:
                idle_streak += 1
            else:
                idle_streak = 0
            wait_s = _next_wait(seconds, idle_streak, max_idle_seconds)

            # Wait interruptibly: if shutdown is requested during this wait,
            # _shutdown_event.wait() will return True immediately and loop exits
            _shutdown_event.wait(wait_s)

    thread = threading.Thread(target=worker_loop, name=name, daemon=True)
    thread.start()
    WORKER_THREADS.append(thread)
    return thread


def stop_worker_threads(timeout: float = 10.0) -> None:
    """Join all registered worker threads with a total timeout.

    Each thread gets `timeout / num_threads` seconds to finish, with a minimum
    of 0.1s per thread. If threads do not join within the limit, the function
    returns anyway (threads are daemons and will not block process exit).

    Args:
        timeout: Total timeout in seconds across all threads.
    """
    if not WORKER_THREADS:
        return

    per_thread_timeout = max(0.1, timeout / len(WORKER_THREADS))
    for thread in WORKER_THREADS:
        thread.join(timeout=per_thread_timeout)

    # Clear the registry so repeated calls do not re-join already-dead threads
    WORKER_THREADS.clear()
