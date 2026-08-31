from __future__ import annotations

"""Lightweight scrape diagnostics (Pi-friendly).

This module provides a *tiny* counter/flag collector wired through:
  - app.scrapers.base.fetch_response (HTTP)
  - app.services.browser_fetcher (Playwright)
  - app.scheduler.jobs pipeline wrappers

It is intentionally simple: counters are integers and flags are booleans.
The snapshot is stored in SourceRun.payload["diag"].
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


_CURRENT: ContextVar["ScrapeDiagnostics | None"] = ContextVar("scrape_diagnostics", default=None)


@dataclass
class ScrapeDiagnostics:
    source: str
    url: Optional[str] = None
    kind: Optional[str] = None

    counters: Dict[str, int] = field(default_factory=dict)
    flags: Dict[str, bool] = field(default_factory=dict)
    notes: Dict[str, Any] = field(default_factory=dict)

    def inc(self, key: str, n: int = 1) -> None:
        if not key:
            return
        try:
            n = int(n)
        except Exception:
            n = 1
        self.counters[key] = int(self.counters.get(key, 0)) + n

    def flag(self, key: str, value: bool = True) -> None:
        if not key:
            return
        self.flags[key] = bool(value)

    def note(self, key: str, value: Any) -> None:
        if not key:
            return
        self.notes[key] = value

    def snapshot(self) -> Dict[str, Any]:
        # Flat keys make admin formatting trivial.
        snap: Dict[str, Any] = {}

        # Counters
        for k, v in (self.counters or {}).items():
            if v:
                snap[k] = int(v)

        # Flags
        for k, v in (self.flags or {}).items():
            if v:
                snap[k] = bool(v)

        # Selected notes
        for k, v in (self.notes or {}).items():
            if v is None:
                continue
            snap[k] = v

        # Always keep these for traceability (cheap strings)
        if self.source:
            snap["source"] = self.source
        if self.url:
            snap["url"] = self.url
        if self.kind:
            snap["kind"] = self.kind

        return snap


def current_diagnostics() -> ScrapeDiagnostics | None:
    return _CURRENT.get()


@contextmanager
def using_diagnostics(diag: ScrapeDiagnostics):
    token = _CURRENT.set(diag)
    try:
        yield diag
    finally:
        _CURRENT.reset(token)


