from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, Optional


def stable_json(obj: Any) -> str:
    """Stable JSON for hashing.

    - Sort keys
    - Convert unknown types to string
    """
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    except Exception:
        return str(obj)


def compute_fingerprint(
    *,
    source: Optional[str],
    event_type: str,
    message: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
    tags: Optional[Iterable[str]] = None,
) -> str:
    """Compute a stable fingerprint for dedupe.

    Goal: same underlying issue => same fingerprint, even if timestamps differ.
    """
    h = hashlib.sha1()
    h.update((source or "").strip().lower().encode("utf-8"))
    h.update(b"\n")
    h.update((event_type or "").strip().lower().encode("utf-8"))

    # message is optional; keep it short to avoid noise
    if message:
        h.update(b"\n")
        h.update(message.strip().encode("utf-8")[:200])

    # evidence: only hash the stable subset (caller should keep it compact)
    if evidence:
        h.update(b"\n")
        h.update(stable_json(evidence).encode("utf-8")[:4000])

    if tags:
        h.update(b"\n")
        h.update(",".join([t.strip().lower() for t in tags if t]).encode("utf-8")[:500])

    return h.hexdigest()
