from __future__ import annotations
from typing import Any, Mapping, Optional
def _coalesce_int(*vals: Any) -> Optional[int]:
    for v in vals:
        if v is None:
            continue
        try:
            return int(v)
        except Exception:
            continue
    return None
def format_dur_ms(*candidates: Any) -> str:
    ms=_coalesce_int(*candidates)
    return f"{ms}ms" if ms is not None else "-"
def short_blocked_diag(payload: Mapping[str, Any] | None) -> str:
    payload=payload or {}
    diag=payload.get("diag") or payload.get("diagnostics") or {}
    provider=diag.get("blocked_provider") or payload.get("blocked_provider")
    title=diag.get("blocked_title") or payload.get("blocked_title")
    if not provider and not title:
        return ""
    s=""
    if provider:
        s+=f" provider={provider}"
    if title:
        t=str(title).replace("\n"," ").strip()
        s+=f" title='{t[:60]}'"
    return s
