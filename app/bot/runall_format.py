from __future__ import annotations
from typing import Any, Optional
def _coalesce_int(*vals: Any) -> Optional[int]:
    for v in vals:
        if v is None:
            continue
        try:
            return int(v)
        except Exception:
            continue
    return None
