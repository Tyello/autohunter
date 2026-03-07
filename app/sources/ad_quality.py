from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re

from app.sources.contract import NormalizedAd
from app.sources.media import derive_thumbnail_url, is_valid_http_url, normalize_image_urls


class QualitySeverity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_CRITICAL_FLAGS = {
    "invalid_url",
    "missing_url",
    "empty_title",
    "missing_source",
}

_RE_SPACES = re.compile(r"\s+")
_RE_LISTING_ID_OK = re.compile(r"^[A-Za-z0-9_.:-]+$")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ad: NormalizedAd
    quality_flags: tuple[str, ...]
    severity: str
    summary: dict[str, int | str | bool]

    @property
    def hard_fail(self) -> bool:
        return self.severity == QualitySeverity.CRITICAL


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    txt = _RE_SPACES.sub(" ", str(value).strip())
    return txt or None


def _is_valid_url(url: str | None) -> bool:
    return is_valid_http_url(url)


def _add_flag(flags: set[str], flag: str) -> None:
    if flag:
        flags.add(flag)


def enforce_ad_contract(ad: NormalizedAd) -> ValidationResult:
    flags: set[str] = set(ad.quality_flags or ())
    extras = dict(ad.extras or {})

    title = _clean_text(ad.title)
    source = _clean_text(ad.source)
    source_listing_id = _clean_text(ad.source_listing_id)
    city = _clean_text(ad.city)
    uf = (_clean_text(ad.uf) or "").upper() or None
    make = _clean_text(ad.make)
    model = _clean_text(ad.model)

    if not source:
        _add_flag(flags, "missing_source")

    if not source_listing_id:
        _add_flag(flags, "missing_source_listing_id")
    elif not _RE_LISTING_ID_OK.match(source_listing_id):
        _add_flag(flags, "invalid_source_listing_id")

    if not ad.url:
        _add_flag(flags, "missing_url")
    elif not _is_valid_url(ad.url):
        _add_flag(flags, "invalid_url")

    if title is None:
        _add_flag(flags, "empty_title")
    elif len(title) < 4:
        _add_flag(flags, "suspect_title")

    if ad.price is None:
        _add_flag(flags, "missing_price")
    elif ad.price <= 0 or ad.price > 50_000_000:
        _add_flag(flags, "suspect_price")

    now_year = datetime.now(timezone.utc).year
    if ad.year is None:
        _add_flag(flags, "missing_year")
    elif ad.year < 1950 or ad.year > (now_year + 1):
        _add_flag(flags, "suspect_year")

    if ad.km is None:
        _add_flag(flags, "missing_km")
    elif ad.km < 0 or ad.km > 1_500_000:
        _add_flag(flags, "suspect_km")

    if not city and not uf:
        _add_flag(flags, "missing_location")
    elif not city or not uf:
        _add_flag(flags, "incomplete_location")

    image_urls = extras.get("image_urls")
    if image_urls is not None:
        cleaned, duplicates, broken = normalize_image_urls(image_urls)
        duplicates = int(extras.get("image_duplicates") or 0) + duplicates
        broken = int(extras.get("image_broken") or 0) + broken
        if duplicates:
            _add_flag(flags, "duplicate_images")
        if broken:
            _add_flag(flags, "broken_images")
        extras["image_urls"] = cleaned
        extras.pop("image_duplicates", None)
        extras.pop("image_broken", None)
        thumb = derive_thumbnail_url(extras.get("thumbnail_url"), cleaned)
        if thumb is not None:
            extras["thumbnail_url"] = thumb
        elif "thumbnail_url" in extras:
            extras.pop("thumbnail_url", None)
        images_count = len(cleaned)
    else:
        images_count = ad.images_count if ad.images_count is not None else None
        thumb = derive_thumbnail_url(extras.get("thumbnail_url"), [])
        if thumb is not None:
            extras["thumbnail_url"] = thumb
        elif "thumbnail_url" in extras:
            extras.pop("thumbnail_url", None)

    has_valid_thumb = bool(derive_thumbnail_url(extras.get("thumbnail_url"), []))

    if (images_count is None or images_count <= 0) and not has_valid_thumb:
        _add_flag(flags, "missing_images")
        images_count = 0 if images_count is None else images_count

    severity = QualitySeverity.INFO
    if any(f in _CRITICAL_FLAGS for f in flags):
        severity = QualitySeverity.CRITICAL
    elif flags:
        severity = QualitySeverity.WARNING

    sanitized = replace(
        ad,
        source=source or "",
        source_listing_id=source_listing_id,
        title=title,
        city=city,
        uf=uf,
        make=make,
        model=model,
        images_count=images_count,
        quality_flags=tuple(sorted(flags)),
        extras=extras,
    )

    return ValidationResult(
        ad=sanitized,
        quality_flags=sanitized.quality_flags,
        severity=severity,
        summary={
            "flags_count": len(sanitized.quality_flags),
            "severity": severity,
            "hard_fail": severity == QualitySeverity.CRITICAL,
        },
    )


def enforce_ads_contract(ads: list[NormalizedAd]) -> tuple[list[NormalizedAd], dict[str, int]]:
    out: list[NormalizedAd] = []
    summary = {
        "total": 0,
        "info": 0,
        "warning": 0,
        "critical": 0,
        "hard_fail": 0,
    }
    for ad in ads or []:
        res = enforce_ad_contract(ad)
        out.append(res.ad)
        summary["total"] += 1
        summary[res.severity] += 1
        if res.hard_fail:
            summary["hard_fail"] += 1
    return out, summary
