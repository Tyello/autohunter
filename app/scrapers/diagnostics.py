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

    def count_status(self, prefix: str, status_code: int | None) -> None:
        if not prefix or status_code is None:
            return
        try:
            sc = int(status_code)
        except Exception:
            return
        m = self.notes.get(f"{prefix}_statuses")
        if not isinstance(m, dict):
            m = {}
            self.notes[f"{prefix}_statuses"] = m
        k = str(sc)
        m[k] = int(m.get(k, 0)) + 1

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


def merge_snapshots(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge two snapshot dicts.

    - ints are summed
    - bools are ORed
    - *_statuses dicts are merged by summing counts
    - everything else prefers `a` unless missing
    """

    out: Dict[str, Any] = dict(a or {})
    if not b:
        return out

    for k, v in b.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = bool(out.get(k, False)) or v
            continue
        if isinstance(v, int):
            if isinstance(out.get(k), int):
                out[k] = int(out.get(k, 0)) + v
            else:
                out[k] = v
            continue
        if k.endswith("_statuses") and isinstance(v, dict):
            cur = out.get(k)
            if not isinstance(cur, dict):
                cur = {}
                out[k] = cur
            for sk, sv in v.items():
                try:
                    cur[sk] = int(cur.get(sk, 0)) + int(sv)
                except Exception:
                    pass
            continue

        # default: keep existing unless missing
        if k not in out or out.get(k) in (None, ""):
            out[k] = v

    return out
