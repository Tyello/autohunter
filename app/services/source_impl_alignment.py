from __future__ import annotations

from typing import Any

_MISSING = "-"
_OK = "ok"
_WARNING = "warning"
_UNKNOWN = "unknown"


def _normalize_impl(value: str | None) -> str | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v or v == _MISSING:
        return None
    return v


def _warning_reason(prefix: str, runtime_impl: str) -> str:
    return f"{prefix}_but_runtime_{runtime_impl}"


def evaluate_source_impl_alignment(
    *,
    source: str,
    configured_impl: str | None,
    last_runtime_impl: str | None,
    canary_enabled: bool = False,
    canary_effective: bool = False,
) -> dict[str, Any]:
    """Evaluate desired source implementation vs observed runtime implementation.

    The helper is intentionally source-agnostic. Callers may pass source-specific
    canary state, but alignment rules remain generic and never trigger promotion
    or rollback automatically.
    """

    _ = source, canary_enabled  # kept for a stable, explicit public signature.
    cfg_impl = _normalize_impl(configured_impl)
    runtime_impl = _normalize_impl(last_runtime_impl)

    result: dict[str, Any] = {
        "configured_impl": cfg_impl or _MISSING,
        "expected_runtime_impl": _MISSING,
        "last_runtime_impl": runtime_impl or _MISSING,
        "impl_alignment": _UNKNOWN,
        "impl_alignment_reason": "configured_impl_missing",
    }

    if not cfg_impl:
        return result

    if cfg_impl == "v2":
        expected = "v2"
        reason_prefix = "configured_v2"
    elif cfg_impl == "v1" and bool(canary_effective):
        expected = "v2_canary"
        reason_prefix = "canary_effective"
    elif cfg_impl == "v1":
        expected = "v1"
        reason_prefix = "configured_v1"
    else:
        return result

    result["expected_runtime_impl"] = expected
    if not runtime_impl:
        result["impl_alignment"] = _UNKNOWN
        result["impl_alignment_reason"] = "runtime_impl_missing"
        return result

    if runtime_impl == expected:
        result["impl_alignment"] = _OK
        result["impl_alignment_reason"] = "ok"
        return result

    result["impl_alignment"] = _WARNING
    result["impl_alignment_reason"] = _warning_reason(reason_prefix, runtime_impl)
    return result
