from __future__ import annotations

from typing import Optional

from app.health.models import LastError, RunStatus, RunSummary, utcnow

BUCKETS = {
    "queued",
    "already_notified",
    "filtered_year",
    "filtered_price",
    "filtered_location",
    "filtered_keyword",
    "missing_price",
    "missing_images",
    "missing_fields_other",
    "duplicate",
    "parse_error",
    "http_error",
    "timeout",
    "proxy_error",
    "blocked_captcha",
    "blocked_403",
    "blocked_429",
    "unknown_error",
}

COUNTERS = {
    "found",
    "inserted",
    "matched",
    "queued",
    "already_notified",
    "filtered_out",
    "skipped",
    "blocked",
    "errors",
}


class HealthCollector:
    def __init__(self, source_name: str):
        self.source_name = source_name
        self.started_at = utcnow()
        self._counters = {k: 0 for k in COUNTERS}
        self._buckets = {k: 0 for k in BUCKETS}
        self._last_error: Optional[LastError] = None
        self._notes: list[str] = []

    def count(self, bucket_name: str, n: int = 1) -> None:
        name = (bucket_name or "").strip().lower()
        inc = int(n or 0)
        if inc <= 0:
            return
        if name not in self._buckets:
            self._buckets["unknown_error"] += inc
            self._notes.append(f"invalid_bucket:{name}")
            return
        self._buckets[name] += inc

    def inc(self, counter_name: str, n: int = 1) -> None:
        name = (counter_name or "").strip().lower()
        if name not in self._counters:
            return
        inc = int(n or 0)
        if inc <= 0:
            return
        self._counters[name] += inc

    def set_error(
        self,
        category: str,
        message: str,
        http_status: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        self._last_error = LastError(
            category=str(category or "error"),
            message=str(message or ""),
            http_status=http_status,
            retryable=retryable,
        )

    def add_note(self, text: str) -> None:
        t = (text or "").strip()
        if t:
            self._notes.append(t)

    def finalize(self, status: RunStatus) -> RunSummary:
        ended_at = utcnow()
        dur_ms = int(max(0, (ended_at - self.started_at).total_seconds() * 1000))
        return RunSummary(
            source_name=self.source_name,
            started_at=self.started_at,
            ended_at=ended_at,
            dur_ms=dur_ms,
            status=status,
            reason_buckets={k: int(v) for k, v in self._buckets.items() if int(v) > 0},
            last_error=self._last_error,
            notes=list(self._notes),
            **self._counters,
        )
