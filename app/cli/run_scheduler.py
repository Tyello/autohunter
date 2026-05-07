from __future__ import annotations

import signal
import time

from app.core.shutdown import is_shutdown_requested, request_shutdown, shutdown_reason
from app.scheduler.run import start_scheduler


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
            print("[scheduler_cli] shutdown_complete")
        except Exception as e:
            print(f"[scheduler_cli] suppressed_exception stage=shutdown exc_type={type(e).__name__} impact=graceful_shutdown_failed fallback=systemd_timeout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
