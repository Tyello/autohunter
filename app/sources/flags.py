from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceImplFlags:
    impl: str = "v1"
    dual_mode: str = "compare_only"
    compare_cfg: dict[str, Any] = field(default_factory=dict)
    canary_v2_enabled: bool = False


def read_source_impl_flags(extra: dict[str, Any] | None) -> SourceImplFlags:
    payload = extra or {}

    impl = str(payload.get("impl") or "v1").strip().lower()
    if impl not in {"v1", "v2", "dual"}:
        impl = "v1"

    dual_mode = str(payload.get("dual_mode") or "compare_only").strip().lower()
    if dual_mode not in {"compare_only", "compare_and_use_v1", "compare_and_use_v2"}:
        dual_mode = "compare_only"

    compare_cfg = payload.get("compare_cfg") if isinstance(payload.get("compare_cfg"), dict) else {}
    canary_v2_enabled = bool(payload.get("mercadolivre_v2_canary_enabled", False))

    return SourceImplFlags(
        impl=impl,
        dual_mode=dual_mode,
        compare_cfg=compare_cfg,
        canary_v2_enabled=canary_v2_enabled,
    )
