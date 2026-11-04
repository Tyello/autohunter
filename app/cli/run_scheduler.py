from __future__ import annotations

import signal
import time

from app.core.shutdown import is_shutdown_requested, request_shutdown, shutdown_reason
from app.scheduler.run import start_scheduler
from app.scrapers.shared.browser_manager import shutdown_browser_manager
from app.services.playwright_pool import shutdown_playwright_pool
from app.scheduler.worker_threads import stop_worker_threads


def _handle(signum, _frame):
    sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    request_shutdown(sig_name)


def main() -> int:
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    sched = start_scheduler()
    try:
        while not is_shutdown_requested():
            time.sleep(1.0)
    finally:
        try:
            print("[scheduler_cli] shutdown_start reason=%s" % (shutdown_reason() or "unknown"))
            sched.pause()
            sched.shutdown(wait=True)
            stop_worker_threads(timeout=10)
            _close_browsers()
            print("[scheduler_cli] shutdown_complete")
        except Exception as e:
            print(f"[scheduler_cli] suppressed_exception stage=shutdown exc_type={type(e).__name__} impact=graceful_shutdown_failed fallback=systemd_timeout")
    return 0


def _close_browsers() -> None:
    """Fecha Playwright/Chromium antes de sair, para o restart nao exigir SIGKILL.

    Roda depois de sched.shutdown(wait=True) e dos worker threads, entao nenhum
    job ainda usa os browsers. Cada etapa e isolada: falha em uma nao impede a
    outra nem o shutdown_complete.
    """
    steps = (
        ("playwright_pool", shutdown_playwright_pool),
        ("browser_manager", shutdown_browser_manager),
    )
    for stage, fn in steps:
        try:
            res = fn()
            if res is not None:
                print(f"[scheduler_cli] browsers_closed stage={stage} result={res}")
        except Exception as e:
            print(f"[scheduler_cli] suppressed_exception stage=shutdown.{stage} exc_type={type(e).__name__} impact=browser_may_need_sigkill fallback=systemd_kill")


if __name__ == "__main__":
    raise SystemExit(main())
