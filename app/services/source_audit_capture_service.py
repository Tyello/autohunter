from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CRITICAL_FIELDS = (
    "price",
    "title",
    "url",
    "source_listing_id",
    "location",
    "year",
    "km",
    "images",
    "thumbnail_url",
)

_DEFAULT_ROOT = Path(os.getenv("SOURCE_AUDIT_ROOT", "artifacts/source_audit_candidates"))
_MAX_SAMPLE_BYTES = int(os.getenv("SOURCE_AUDIT_MAX_BYTES", "250000"))


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _slug(value: str | None, fallback: str = "unknown") -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return fallback
    return re.sub(r"[^a-z0-9_.-]+", "_", raw)[:120] or fallback


def _sanitize_text(payload: str) -> str:
    out = payload
    out = re.sub(r"([\w.+-]+@[\w.-]+)", "[redacted-email]", out)
    out = re.sub(r"\b(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?\d{4,5}[-\s]?\d{4}\b", "[redacted-phone]", out)
    out = re.sub(r"([?&](?:token|auth|session|sig|signature|key)=)[^&\s]+", r"\1[redacted]", out, flags=re.I)
    return out


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, indent=2)


@dataclass(frozen=True)
class CaptureDecision:
    should_capture: bool
    reasons: tuple[str, ...]


class SourceAuditCaptureService:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or _DEFAULT_ROOT)

    def decide(self, *, explicit_reason: str | None = None, found: int | None = None, missing_critical: list[str] | None = None, quality_flags: list[str] | None = None, parse_error: bool = False, debug: bool = False) -> CaptureDecision:
        reasons: list[str] = []
        if explicit_reason:
            reasons.append(explicit_reason)
        if parse_error:
            reasons.append("parse_error")
        if found == 0:
            reasons.append("found_zero_suspect")
        if missing_critical:
            reasons.append("critical_fields_missing")
        if quality_flags and any(f.startswith("missing_") or f.startswith("invalid_") for f in quality_flags):
            reasons.append("quality_flags_critical_or_missing")
        if debug:
            reasons.append("debug_manual")
        uniq = tuple(dict.fromkeys([r for r in reasons if r]))
        return CaptureDecision(should_capture=bool(uniq), reasons=uniq)

    def register_runtime_fetch_sample(self, *, ctx: Any | None, source: str, kind: str, url: str, payload: str | dict | list, content_type: str = "text/html", stage: str = "fetch") -> None:
        if ctx is None:
            return
        extra = getattr(ctx, "extra", None)
        if not isinstance(extra, dict):
            return

        samples = extra.setdefault("_audit_fetch_samples", [])
        if not isinstance(samples, list):
            samples = []
            extra["_audit_fetch_samples"] = samples

        if isinstance(payload, (dict, list)):
            body = _safe_json(payload)
            ext = ".json"
        else:
            body = str(payload or "")
            ext = ".html" if "html" in (content_type or "").lower() else ".txt"

        body = _sanitize_text(body)
        if len(body.encode("utf-8", errors="ignore")) > _MAX_SAMPLE_BYTES:
            body = body[:_MAX_SAMPLE_BYTES] + "\n<!-- truncated -->"

        samples.append(
            {
                "source": _slug(source),
                "kind": "detail" if kind == "detail" else "listing",
                "url": url,
                "payload": body,
                "content_type": content_type,
                "stage": stage,
                "ext": ext,
                "timestamp": _utc_iso_now(),
            }
        )
        # keep tiny ring buffer in-memory only
        if len(samples) > 12:
            del samples[:-12]

    def capture_from_runtime_samples(self, *, ctx: Any | None, source: str, reasons: list[str] | tuple[str, ...], pipeline_stage: str, source_listing_id: str | None = None, extracted_snapshot: dict[str, Any] | None = None) -> list[Path]:
        if ctx is None:
            return []
        extra = getattr(ctx, "extra", None)
        samples = (extra or {}).get("_audit_fetch_samples") if isinstance(extra, dict) else None
        if not isinstance(samples, list) or not samples:
            return []

        saved: list[Path] = []
        for s in samples[-3:]:
            saved.append(
                self.capture_artifact(
                    source=source,
                    kind=s.get("kind") or "listing",
                    url=s.get("url") or "",
                    source_listing_id=source_listing_id,
                    reason=",".join(reasons),
                    pipeline_stage=pipeline_stage,
                    payload=s.get("payload") or "",
                    content_ext=s.get("ext") or ".txt",
                    extracted_snapshot=extracted_snapshot,
                )
            )
        return saved

    def capture_artifact(self, *, source: str, kind: str, url: str, source_listing_id: str | None, reason: str, pipeline_stage: str, payload: str | dict | list, content_ext: str = ".html", extracted_snapshot: dict[str, Any] | None = None) -> Path:
        src = _slug(source)
        kind_s = "detail" if kind == "detail" else "listing"
        sid = _slug(source_listing_id, fallback="na")
        ts = _utc_iso_now()
        checksum = hashlib.sha1(f"{url}|{reason}|{ts}".encode("utf-8")).hexdigest()[:8]

        out_dir = self.root / src
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = f"{kind_s}_{sid}_{ts}_{checksum}"
        payload_path = out_dir / f"{stem}{content_ext}"
        meta_path = out_dir / f"{stem}.meta.json"

        if isinstance(payload, (dict, list)):
            body = _safe_json(payload)
        else:
            body = str(payload or "")
        body = _sanitize_text(body)

        payload_path.write_text(body, encoding="utf-8")
        meta_path.write_text(
            _safe_json(
                {
                    "source": src,
                    "kind": kind_s,
                    "url": url,
                    "source_listing_id": source_listing_id,
                    "timestamp": ts,
                    "reason": reason,
                    "pipeline_stage": pipeline_stage,
                    "extracted_snapshot": extracted_snapshot or {},
                }
            ),
            encoding="utf-8",
        )
        return payload_path


source_audit_capture_service = SourceAuditCaptureService()
