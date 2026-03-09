from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ErrorCategory = Literal["BUG", "NET", "PROXY", "BLOCKED", "PARSE", "DATA"]


@dataclass(frozen=True, slots=True)
class SourceError:
    category: ErrorCategory
    code: str
    message: str
    retriable: bool = True
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class NormalizedAd:
    source: str
    external_id: str | None
    url: str
    title: str | None = None
    price: int | None = None
    currency: str | None = "BRL"
    city: str | None = None
    uf: str | None = None
    year: int | None = None
    km: int | None = None
    make: str | None = None
    model: str | None = None
    images_count: int | None = None
    quality_flags: tuple[str, ...] = field(default_factory=tuple)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def source_listing_id(self) -> str | None:
        """Backward compatibility alias for legacy pipeline/tests."""
        return self.external_id

    def fingerprint(self) -> tuple[str | int | None, ...]:
        return (
            (self.make or "").strip().lower() or None,
            (self.model or "").strip().lower() or None,
            self.year,
            self.price,
            (self.city or "").strip().lower() or None,
            (self.uf or "").strip().upper() or None,
        )


@dataclass(frozen=True, slots=True)
class ResultMetadata:
    source: str
    impl: str
    duration_ms: int
    raw_count: int
    normalized_count: int
    blocked: bool = False
    partial_failure: bool = False
    warnings_count: int = 0
    reason_buckets: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
