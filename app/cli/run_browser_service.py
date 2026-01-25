from __future__ import annotations

import os
import signal
import uvicorn

from app.core.settings import settings


_shutdown = False


def _handle(_signum, _frame):
    global _shutdown
    _shutdown = True


def main() -> int:
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    host = os.getenv("BROWSER_SERVICE_HOST") or getattr(settings, "playwright_service_host", "127.0.0.1")
    port = int(os.getenv("BROWSER_SERVICE_PORT") or getattr(settings, "playwright_service_port", 8787))

    # Single worker. Keep it simple + predictable on Raspberry Pi.
    uvicorn.run(
        "app.browser_service.main:app",
        host=host,
        port=port,
        workers=1,
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
