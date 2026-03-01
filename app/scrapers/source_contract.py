from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Iterable

from app.scrapers.contract import finalize_listings


@dataclass(frozen=True, slots=True)
class SourceError:
    code: str
    message: str
    retriable: bool = True
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class NormalizedAd:
    source: str
    external_id: str
    url: str
    title: str = ""
    price: Any = None
    currency: str = "BRL"
    location: str = ""
    thumbnail_url: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_listing(cls, listing: dict[str, Any]) -> "NormalizedAd":
        core_keys = {
            "source",
            "external_id",
            "url",
            "title",
            "price",
            "currency",
            "location",
            "thumbnail_url",
        }
        extras = {k: v for k, v in (listing or {}).items() if k not in core_keys and v is not None}
        return cls(
            source=str((listing or {}).get("source") or "").strip().lower(),
            external_id=str((listing or {}).get("external_id") or "").strip(),
            url=str((listing or {}).get("url") or "").strip(),
            title=str((listing or {}).get("title") or "").strip(),
            price=(listing or {}).get("price"),
            currency=str((listing or {}).get("currency") or "BRL").strip() or "BRL",
            location=str((listing or {}).get("location") or "").strip(),
            thumbnail_url=(listing or {}).get("thumbnail_url"),
            extras=extras,
        )

    def to_listing(self) -> dict[str, Any]:
        out = {
            "source": self.source,
            "external_id": self.external_id,
            "url": self.url,
            "title": self.title,
            "price": self.price,
            "currency": self.currency,
            "location": self.location,
            "thumbnail_url": self.thumbnail_url,
        }
        if self.extras:
            out.update(self.extras)
        return out


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


@dataclass(frozen=True, slots=True)
class SourceResult:
    ads: list[NormalizedAd]
    metadata: ResultMetadata
    error: SourceError | None = None


def normalize_raw_items(source: str, raw_items: Iterable[Any]) -> list[NormalizedAd]:
    normalized = finalize_listings(source, raw_items)
    return [NormalizedAd.from_listing(it) for it in normalized]


def timed_normalize(source: str, raw_items: Iterable[Any], *, impl: str, raw_count: int | None = None) -> SourceResult:
    t0 = perf_counter()
    try:
        normalized = normalize_raw_items(source, raw_items)
        duration_ms = int((perf_counter() - t0) * 1000)
        return SourceResult(
            ads=normalized,
            metadata=ResultMetadata(
                source=source,
                impl=impl,
                duration_ms=duration_ms,
                raw_count=int(raw_count if raw_count is not None else len(normalized)),
                normalized_count=len(normalized),
            ),
        )
    except Exception as exc:  # keep adapter error compact/retriable
        duration_ms = int((perf_counter() - t0) * 1000)
        return SourceResult(
            ads=[],
            metadata=ResultMetadata(
                source=source,
                impl=impl,
                duration_ms=duration_ms,
                raw_count=0,
                normalized_count=0,
                partial_failure=True,
            ),
            error=SourceError(code="normalize_error", message=str(exc), retriable=True),
        )
