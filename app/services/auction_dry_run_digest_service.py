from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.system_log import SystemLog
from app.services.app_kv_service import get_kv
from app.services.auction_notification_settings_service import get_auction_notification_runtime_settings
from app.services.auction_source_config_service import list_user_eligible_auction_sources

_DRY_RUN_SAMPLES_KEY = "auction_last_dry_run_samples"
_EVENTS = {
    "auction_notification_scheduler_tick_finished",
    "auction_notification_scheduler_tick_skipped",
    "auction_notification_scheduler_tick_failed",
    "auction_notification_job_skipped",
}
_SKIP_KEYS = [
    "score_below_min",
    "stale_lot",
    "missing_lot_updated_at",
    "item_type_not_allowed",
    "missing_item_type",
    "duplicate",
    "daily_limit",
    "no_match",
    "missing_chat_id",
]


def _to_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _last_status(row: SystemLog | None, payload: dict) -> str:
    if not row:
        return "unknown"
    if row.message == "auction_notification_scheduler_tick_failed":
        return "error"
    if bool(payload.get("skipped")):
        return "disabled" if payload.get("reason") == "disabled" else "unknown"
    if bool(payload.get("dry_run", True)):
        return "dry_run"
    return "unknown"


def _build_recommendation(enabled: bool, dry_run: bool, runs: int, previews: int, errors: int, skips: dict, has_samples: bool) -> dict:
    if not enabled:
        return {"status": "no_data", "message": "Scheduler de leilões está desligado."}
    if not dry_run:
        return {"status": "needs_attention", "message": "Envio real aparentemente ativo. Revisar imediatamente."}
    if runs == 0 and not has_samples:
        return {"status": "no_data", "message": "Sem dados suficientes. Rode notify-run ou aguarde o scheduler."}
    if errors > 0:
        return {"status": "needs_attention", "message": "Há erros no dry-run. Corrigir antes de avançar."}
    if previews == 0 and (_to_int(skips.get("no_match")) + _to_int(skips.get("text_score_zero"))) > 0:
        return {"status": "needs_attention", "message": "Sem previews. Revisar buscas, sources ou matching."}
    if previews > 0 and errors == 0:
        return {"status": "keep_dry_run", "message": "Dry-run saudável. Manter coleta por mais ciclos. Pode iniciar piloto manual/controlado após mais validação."}
    return {"status": "no_data", "message": "Sem dados suficientes. Rode notify-run ou aguarde o scheduler."}


def build_auction_dry_run_digest(db, hours: int = 24) -> dict:
    hours = max(1, min(int(hours), 168))
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    cfg = get_auction_notification_runtime_settings(db)
    rows = (
        db.query(SystemLog)
        .filter(SystemLog.component == "scheduler", SystemLog.message.in_(_EVENTS), SystemLog.created_at >= since)
        .order_by(SystemLog.created_at.desc())
        .all()
    )
    latest = rows[0] if rows else None
    payload = latest.payload if latest and isinstance(latest.payload, dict) else {}

    out = {
        "window_hours": hours,
        "since": since.isoformat(),
        "runs": len(rows),
        "last_run_at": latest.created_at.astimezone(timezone.utc).isoformat() if latest and latest.created_at else None,
        "last_status": _last_status(latest, payload),
        "wishlists_scanned": 0,
        "wishlists_with_matches": 0,
        "previews": 0,
        "sent": 0,
        "errors": 0,
        "skips": {k: 0 for k in _SKIP_KEYS},
        "eligible_sources": sorted(list_user_eligible_auction_sources(db)),
        "source_summary": {},
        "latest_samples": [],
        "latest_rejections": [],
        "history_note": None,
        "recommendation": {"status": "no_data", "message": "Sem dados suficientes. Rode notify-run ou aguarde o scheduler."},
    }
    for src in out["eligible_sources"]:
        out["source_summary"][src] = {"runs": 0, "previews": 0, "errors": 0}

    for row in rows:
        p = row.payload if isinstance(row.payload, dict) else {}
        out["wishlists_scanned"] += _to_int(p.get("wishlists_scanned"))
        out["wishlists_with_matches"] += _to_int(p.get("wishlists_with_matches"))
        out["previews"] += _to_int(p.get("previews"))
        out["sent"] += _to_int(p.get("sent"))
        out["errors"] += _to_int(p.get("errors"))
        for key in _SKIP_KEYS:
            out["skips"][key] += _to_int(p.get(f"skipped_{key}"))
        src = p.get("source")
        if src:
            info = out["source_summary"].setdefault(src, {"runs": 0, "previews": 0, "errors": 0})
            info["runs"] += 1
            info["previews"] += _to_int(p.get("previews"))
            info["errors"] += _to_int(p.get("errors"))

    last_samples = get_kv(db, _DRY_RUN_SAMPLES_KEY) or {}
    if isinstance(last_samples, dict):
        summary = last_samples.get("summary") if isinstance(last_samples.get("summary"), dict) else {}
        complemented = False
        if summary:
            old = (out["wishlists_scanned"], out["wishlists_with_matches"], out["previews"], out["sent"], out["errors"])
            out["wishlists_scanned"] = max(out["wishlists_scanned"], _to_int(summary.get("wishlists_scanned")))
            out["wishlists_with_matches"] = max(out["wishlists_with_matches"], _to_int(summary.get("wishlists_with_matches")))
            out["previews"] = max(out["previews"], _to_int(summary.get("previews")))
            out["sent"] = max(out["sent"], _to_int(summary.get("sent")))
            out["errors"] = max(out["errors"], _to_int(summary.get("errors")))
            if old != (out["wishlists_scanned"], out["wishlists_with_matches"], out["previews"], out["sent"], out["errors"]):
                complemented = True
            for key in _SKIP_KEYS:
                before = out["skips"][key]
                out["skips"][key] = max(out["skips"][key], _to_int(summary.get(f"skipped_{key}")))
                if out["skips"][key] != before:
                    complemented = True
        out["latest_samples"] = (last_samples.get("samples") if isinstance(last_samples.get("samples"), list) else [])[:5]
        out["latest_rejections"] = (last_samples.get("rejections") if isinstance(last_samples.get("rejections"), list) else [])[:5]
        if out["runs"] > 0 and complemented:
            out["history_note"] = "Histórico parcial: usando último summary salvo para complementar counters."

    sample_source_counts: dict[str, int] = {}
    for item in out["latest_samples"]:
        if isinstance(item, dict):
            source = str(item.get("source") or "").strip()
            if source:
                sample_source_counts[source] = sample_source_counts.get(source, 0) + 1
    for bucket in (out["latest_samples"], out["latest_rejections"]):
        for item in bucket:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            if not source:
                continue
            info = out["source_summary"].setdefault(source, {"runs": 0, "previews": 0, "errors": 0})
            info["previews"] = max(info.get("previews", 0), sample_source_counts.get(source, 0))

    out["recommendation"] = _build_recommendation(
        enabled=bool(cfg.get("enabled", False)),
        dry_run=bool(cfg.get("dry_run", True)),
        runs=out["runs"],
        previews=out["previews"],
        errors=out["errors"],
        skips=out["skips"],
        has_samples=bool(out["latest_samples"] or out["latest_rejections"]),
    )
    return out
