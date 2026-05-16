from __future__ import annotations

from app.services.app_kv_service import get_kv

_DRY_RUN_SAMPLES_KEY = "auction_last_dry_run_samples"


def build_auction_notification_samples(db, limit: int = 10) -> dict:
    payload = get_kv(db, _DRY_RUN_SAMPLES_KEY) or {}
    samples = payload.get("samples") if isinstance(payload, dict) else []
    if not isinstance(samples, list):
        samples = []
    return {
        "created_at": (payload.get("created_at") if isinstance(payload, dict) else None) or "-",
        "summary": (payload.get("summary") if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) else {}),
        "samples": samples[: max(0, int(limit))],
    }
