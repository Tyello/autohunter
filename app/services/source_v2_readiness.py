from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.services.source_impl_alignment import evaluate_source_impl_alignment
from app.services.source_v2_inventory import build_source_v2_inventory


READINESS_PRIORITY = {
    "candidate": 1,
    "needs_dual_run": 2,
    "blocked_or_unstable": 3,
    "done": 4,
    "disabled": 5,
    "no_v2": 6,
    "deprioritized": 7,
}

_STABLE_OK_RATE_MIN = 90
_BROWSER_FETCH_MODES = {"browser", "hybrid"}


@dataclass(frozen=True, slots=True)
class SourceV2RunStats:
    success_count: int = 0
    blocked_count: int = 0
    error_count: int = 0
    skip_count: int = 0
    ok_rate: int = 0
    avg_duration_ms: int | None = None
    last_success_at: datetime | None = None
    last_found: int | None = None
    last_matched: int | None = None
    last_thumb_rate: float | None = None
    last_runtime_impl: str | None = None
    has_recent_v2_runtime: bool = False

    @property
    def effective_count(self) -> int:
        return self.success_count + self.blocked_count + self.error_count


def _payload_as_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def extract_runtime_impl(payload: Any) -> str | None:
    data = _payload_as_dict(payload)
    runtime_impl = data.get("runtime_impl")
    if runtime_impl:
        return str(runtime_impl).strip().lower()
    run_summary = data.get("run_summary")
    if isinstance(run_summary, dict) and run_summary.get("runtime_impl"):
        return str(run_summary.get("runtime_impl")).strip().lower()
    return None


def _extract_thumb_rate(payload: Any) -> float | None:
    data = _payload_as_dict(payload)
    value = data.get("thumb_rate")
    if value is None:
        run_summary = data.get("run_summary")
        if isinstance(run_summary, dict):
            value = run_summary.get("thumb_rate")
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _build_run_stats(db: Any, source: str, *, now: datetime, window_hours: int = 24) -> SourceV2RunStats:
    since = now - timedelta(hours=max(1, int(window_hours or 24)))
    rows = (
        db.query(SourceRun)
        .filter(SourceRun.source == source)
        .filter(SourceRun.created_at >= since)
        .order_by(SourceRun.created_at.desc())
        .all()
    )

    success = blocked = error = skipped = 0
    duration_total = 0
    duration_count = 0
    last_success_at = None
    last_found = None
    last_matched = None
    last_thumb_rate = None
    last_runtime_impl = None
    has_recent_v2_runtime = False

    for row in rows:
        status = str(getattr(row, "status", "") or "").strip().lower()
        runtime_impl = extract_runtime_impl(getattr(row, "payload", None))
        if runtime_impl and last_runtime_impl is None:
            last_runtime_impl = runtime_impl
        if runtime_impl in {"v2", "v2_canary"}:
            has_recent_v2_runtime = True

        if status == "success":
            success += 1
            if last_success_at is None:
                last_success_at = getattr(row, "created_at", None)
                last_found = int(getattr(row, "items_found", 0) or 0)
                last_matched = int(getattr(row, "items_matched", 0) or 0)
                last_thumb_rate = _extract_thumb_rate(getattr(row, "payload", None))
        elif status == "blocked":
            blocked += 1
        elif status == "error":
            error += 1
        elif status == "skipped":
            skipped += 1

        if status != "skipped" and getattr(row, "duration_ms", None) is not None:
            duration_total += int(getattr(row, "duration_ms") or 0)
            duration_count += 1

    effective = success + blocked + error
    ok_rate = int(round((success / effective) * 100)) if effective else 0
    return SourceV2RunStats(
        success_count=success,
        blocked_count=blocked,
        error_count=error,
        skip_count=skipped,
        ok_rate=ok_rate,
        avg_duration_ms=int(duration_total / duration_count) if duration_count else None,
        last_success_at=last_success_at,
        last_found=last_found,
        last_matched=last_matched,
        last_thumb_rate=last_thumb_rate,
        last_runtime_impl=last_runtime_impl,
        has_recent_v2_runtime=has_recent_v2_runtime,
    )


def _configured_enabled(row: dict[str, Any]) -> bool:
    value = row.get("configured_enabled")
    if value is None:
        return bool(row.get("default_enabled", True))
    return bool(value)


def _recommendation(*, source: str, status: str, fetch_mode: str, role: str) -> str:
    source = str(source or "").strip().lower()
    fetch_mode = str(fetch_mode or "").strip().lower()
    role = str(role or "").strip().lower()

    if status == "done":
        return "done_monitor_24h"
    if status == "disabled":
        if source == "webmotors" or role == "deprioritized":
            return "keep_disabled_until_strategy_changes"
        return "enable_only_if_product_strategy_requires_then_dual_run"
    if status == "no_v2":
        return "no_v2_registered_do_not_migrate"
    if status == "deprioritized":
        return "keep_disabled_until_strategy_changes" if source == "webmotors" else "review_operational_role_before_migration"
    if status == "blocked_or_unstable":
        return "stabilize_source_before_v2_migration"
    if status == "needs_dual_run":
        return "dual_run_first_due_browser_cost" if fetch_mode in _BROWSER_FETCH_MODES else "run_dual_report_then_consider_canary"
    if status == "candidate":
        if role == "experimental":
            return "review_operational_role_before_migration"
        if fetch_mode in _BROWSER_FETCH_MODES:
            return "dual_run_first_due_browser_cost"
        return "run_dual_report_then_consider_canary"
    return "review_manually"


def classify_v2_readiness(row: dict[str, Any]) -> tuple[str, str]:
    source = str(row.get("source") or "").strip().lower()
    role = str(row.get("operational_role") or "unknown").strip().lower()
    fetch_mode = str(row.get("fetch_mode") or "-").strip().lower()
    has_v2 = bool(row.get("has_v2"))
    supports_dual = bool(row.get("supports_dual"))
    enabled = bool(row.get("enabled"))
    configured_impl = str(row.get("configured_impl") or row.get("current_impl") or "-").strip().lower()
    last_runtime_impl = str(row.get("last_runtime_impl") or "-").strip().lower()
    alignment = str(row.get("impl_alignment") or "unknown").strip().lower()
    success_count = int(row.get("success_count") or 0)
    blocked_count = int(row.get("blocked_count") or 0)
    error_count = int(row.get("error_count") or 0)
    ok_rate = int(row.get("ok_rate") or 0)
    has_recent_v2_runtime = bool(row.get("has_recent_v2_runtime")) or last_runtime_impl in {"v2", "v2_canary"}

    if role == "deprioritized":
        status = "deprioritized"
    elif not enabled:
        status = "disabled"
    elif not has_v2:
        status = "no_v2"
    elif blocked_count > 0 or error_count > 0 or (success_count > 0 and ok_rate < _STABLE_OK_RATE_MIN):
        status = "blocked_or_unstable"
    elif configured_impl == "v2" and last_runtime_impl == "v2" and alignment == "ok" and success_count > 0:
        status = "done"
    elif has_v2 and supports_dual and configured_impl == "v1":
        if not has_recent_v2_runtime and fetch_mode in _BROWSER_FETCH_MODES:
            status = "needs_dual_run"
        elif success_count > 0 and ok_rate >= _STABLE_OK_RATE_MIN:
            status = "candidate"
        else:
            status = "needs_dual_run"
    elif has_v2 and supports_dual:
        status = "needs_dual_run"
    else:
        status = "blocked_or_unstable"

    return status, _recommendation(source=source, status=status, fetch_mode=fetch_mode, role=role)


def build_source_v2_readiness_report(db: Any, *, now: datetime | None = None, window_hours: int = 24) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    inventory = build_source_v2_inventory(db=db)
    states = {s.source: s for s in db.query(SourceState).all()}

    rows: list[dict[str, Any]] = []
    for item in inventory:
        source = str(item["source"]).strip().lower()
        stats = _build_run_stats(db, source, now=now, window_hours=window_hours)
        state = states.get(source)

        last_runtime_impl = stats.last_runtime_impl
        if not last_runtime_impl and state is not None:
            last_runtime_impl = extract_runtime_impl(getattr(state, "last_payload", None))

        configured_impl = str(item.get("current_impl") or "v1")
        alignment = evaluate_source_impl_alignment(
            source=source,
            configured_impl=configured_impl,
            last_runtime_impl=last_runtime_impl,
            canary_enabled=False,
            canary_effective=False,
        )
        enabled = _configured_enabled(item)

        row = {
            **item,
            "enabled": enabled,
            "configured_impl": configured_impl,
            "last_runtime_impl": alignment["last_runtime_impl"],
            "expected_runtime_impl": alignment["expected_runtime_impl"],
            "impl_alignment": alignment["impl_alignment"],
            "impl_alignment_reason": alignment["impl_alignment_reason"],
            "last_success_at": stats.last_success_at,
            "last_found": stats.last_found,
            "last_matched": stats.last_matched,
            "last_thumb_rate": stats.last_thumb_rate,
            "success_count": stats.success_count,
            "blocked_count": stats.blocked_count,
            "error_count": stats.error_count,
            "skip_count": stats.skip_count,
            "ok_rate": stats.ok_rate,
            "avg_duration_ms": stats.avg_duration_ms,
            "has_recent_v2_runtime": stats.has_recent_v2_runtime,
        }
        status, recommendation = classify_v2_readiness(row)
        row["v2_readiness_status"] = status
        row["recommendation"] = recommendation
        rows.append(row)

    return sorted(rows, key=_sort_key)


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    status = str(row.get("v2_readiness_status") or "").strip().lower()
    role = str(row.get("operational_role") or "").strip().lower()
    return (
        READINESS_PRIORITY.get(status, 99),
        0 if role == "primary" else 1,
        -int(row.get("ok_rate") or 0),
        int(row.get("blocked_count") or 0) + int(row.get("error_count") or 0),
        int(row.get("avg_duration_ms") or 999999999),
        -(int(row.get("last_found") or 0) + int(row.get("last_matched") or 0)),
        str(row.get("source") or ""),
    )


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _fmt_bool(value: Any) -> str:
    return "✅" if bool(value) else "❌"


def _fmt_thumb(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(round(float(value) * 100))}%"
    except Exception:
        return "-"


def render_source_v2_readiness_telegram(rows: list[dict[str, Any]]) -> str:
    lines = ["🧭 V1→V2 Readiness", ""]
    for idx, row in enumerate(rows, start=1):
        source = row.get("source")
        status = row.get("v2_readiness_status")
        lines.append(f"[{idx}] {source} — {status}")
        lines.append(
            "impl={impl} runtime={runtime} expected={expected} alignment={alignment}".format(
                impl=row.get("configured_impl") or "-",
                runtime=row.get("last_runtime_impl") or "-",
                expected=row.get("expected_runtime_impl") or "-",
                alignment=row.get("impl_alignment") or "-",
            )
        )
        lines.append(
            "enabled={enabled} has_v1{has_v1} has_v2{has_v2} dual{dual} role={role} fetch={fetch}".format(
                enabled=bool(row.get("enabled")),
                has_v1=_fmt_bool(row.get("has_v1")),
                has_v2=_fmt_bool(row.get("has_v2")),
                dual=_fmt_bool(row.get("supports_dual")),
                role=row.get("operational_role") or "-",
                fetch=row.get("fetch_mode") or "-",
            )
        )
        lines.append(
            "24h ok={ok} blk={blk} err={err} skip={skip} ok_rate={rate}% avg={avg}".format(
                ok=int(row.get("success_count") or 0),
                blk=int(row.get("blocked_count") or 0),
                err=int(row.get("error_count") or 0),
                skip=int(row.get("skip_count") or 0),
                rate=int(row.get("ok_rate") or 0),
                avg="-" if row.get("avg_duration_ms") is None else f"{int(row.get('avg_duration_ms') or 0)}ms",
            )
        )
        lines.append(
            "last success={success_at} found={found} match={matched} thumb={thumb}".format(
                success_at=_fmt_dt(row.get("last_success_at")),
                found="-" if row.get("last_found") is None else int(row.get("last_found") or 0),
                matched="-" if row.get("last_matched") is None else int(row.get("last_matched") or 0),
                thumb=_fmt_thumb(row.get("last_thumb_rate")),
            )
        )
        lines.append(f"ação: {row.get('recommendation')}")
        lines.append("")
    return "\n".join(lines).rstrip()
