from __future__ import annotations

import threading

_shutdown_event = threading.Event()
_shutdown_reason: str | None = None


def request_shutdown(reason: str = "signal") -> None:
    global _shutdown_reason
    if not _shutdown_event.is_set():
        _shutdown_reason = reason
    _shutdown_event.set()


def is_shutdown_requested() -> bool:
    return _shutdown_event.is_set()


def shutdown_reason() -> str | None:
    return _shutdown_reason
