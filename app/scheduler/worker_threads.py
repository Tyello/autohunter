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


def start_worker_thread(
    fn: Callable[[], None],
    *,
    seconds: int,
    name: str,
) -> threading.Thread:
    """Start a daemon thread that calls fn() repeatedly on an interval.

    The thread checks for shutdown signals and waits interruptibly between calls.
    Exceptions in fn() are logged simply and do not kill the thread.

    Args:
        fn: Callable to invoke repeatedly (must accept no arguments).
        seconds: Interval in seconds between calls.
        name: Human-readable thread name.

    Returns:
        The started threading.Thread (already running).
    """
    def worker_loop():
        while not is_shutdown_requested():
            try:
                fn()
            except Exception as exc:
                # Log simply without derailing the loop
                print(
                    f"[{name}] suppressed_exception stage=worker.fn "
                    f"exc_type={type(exc).__name__} "
                    f"message={str(exc)[:280]}",
                    flush=True,
                )

            # Wait interruptibly: if shutdown is requested during this wait,
            # _shutdown_event.wait() will return True immediately and loop exits
            _shutdown_event.wait(seconds)

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
