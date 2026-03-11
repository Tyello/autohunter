from __future__ import annotations

import signal
import time

from app.scheduler.run import start_scheduler


_shutdown = False


def _handle(_signum, _frame):
    global _shutdown
    _shutdown = True


def main() -> int:
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    sched = start_scheduler()
    try:
        while not _shutdown:
            time.sleep(1.0)
    finally:
        try:
            sched.shutdown(wait=False)
        except Exception as e:
            # shutdown best-effort with actionable context
            print(f"[scheduler_cli] suppressed_exception stage=shutdown exc_type={type(e).__name__} impact=graceful_shutdown_failed fallback=process_exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
