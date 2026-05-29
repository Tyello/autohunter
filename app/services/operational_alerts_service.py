from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import psutil
from typing import Any, List, Optional, Set

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.notification import Notification
from app.models.scrape_job import ScrapeJob
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.models.system_log import SystemLog
from app.services.app_kv_service import get_kv, set_kv
from app.services.source_operational_policy import (
    classify_source_operational_role,
    should_include_in_critical_stale,
)
from app.services.source_staleness_service import evaluate_source_staleness
from app.sources.flags import read_source_impl_flags
from app.sources.registry import get_source



_MERCADOLIVRE = "mercadolivre"


def _status_is_backoff(status: Optional[str]) -> bool:
    return "backoff" in str(status or "").strip().lower()


def _is_skipped_backoff_run(run: SourceRun) -> bool:
    if str(getattr(run, "status", "") or "").lower() != "skipped":
        return False
    payload = getattr(run, "payload", None)
    if isinstance(payload, dict) and str(payload.get("reason") or "").lower() == "backoff":
        return True
    return "backoff" in str(getattr(run, "error", "") or "").lower()


def _extract_runtime_impl(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("runtime_impl"):
        return str(payload.get("runtime_impl"))
    run_summary = payload.get("run_summary")
    if isinstance(run_summary, dict) and run_summary.get("runtime_impl"):
        return str(run_summary.get("runtime_impl"))
    return None


def _source_ops_context(db: Session, src: str, cfg: SourceConfig, st: SourceState | None, now: datetime) -> dict[str, Any]:
    window_start = now - timedelta(minutes=int(getattr(settings, "autopilot_window_minutes", 30) or 30))
    runs = (
        db.query(SourceRun)
        .filter(SourceRun.source == src)
        .filter(SourceRun.created_at >= window_start)
        .filter(SourceRun.created_at < now)
        .order_by(SourceRun.created_at.desc())
        .all()
    )
    flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)
    runtime_impl = None
    for run in runs:
        runtime_impl = _extract_runtime_impl(getattr(run, "payload", None))
        if runtime_impl:
            break
    if not runtime_impl and st is not None:
        runtime_impl = _extract_runtime_impl(getattr(st, "last_payload", None))
    total = len(runs)
    blocked = sum(1 for r in runs if str(getattr(r, "status", "") or "").lower() == "blocked")
    success = sum(1 for r in runs if str(getattr(r, "status", "") or "").lower() == "success")
    skipped_backoff = sum(1 for r in runs if _is_skipped_backoff_run(r))
    canary_effective = (
        src == _MERCADOLIVRE
        and bool(flags.canary_v2_enabled)
        and bool(getattr(settings, "enable_playwright", False))
        and bool(getattr(cfg, "browser_fallback_enabled", False))
    )
    return {
        "source": src,
        "configured_impl": flags.impl,
        "runtime_impl": runtime_impl,
        "mercadolivre_v2_canary_enabled": bool(flags.canary_v2_enabled),
        "canary_effective": bool(canary_effective),
        "browser_fallback_enabled": bool(getattr(cfg, "browser_fallback_enabled", False)),
        "force_browser": bool(getattr(cfg, "force_browser", False)),
        "backoff_until": getattr(st, "next_allowed_at", None),
        "status": getattr(st, "last_status", None) if st else None,
        "blocked_count": blocked,
        "success_count": success,
        "skipped_backoff_count": skipped_backoff,
        "blocked_ratio": (float(blocked) / float(total)) if total else 0.0,
    }


def _source_status_commands(src: str, ctx: dict[str, Any]) -> str:
    if src == _MERCADOLIVRE and bool(ctx.get("canary_effective")):
        return (
            "Diagnóstico canary: /admin sources canary mercadolivre report\n"
            "Status: /admin sources show mercadolivre\n"
            "Health: /admin health"
        )
    return f"Status: /admin sources show {src}\nHealth: /admin health"

@dataclass
class OperationalAlert:
    key: str
    message: str
    cooldown_minutes: int


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)



def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _age_minutes(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((now - dt.astimezone(timezone.utc)).total_seconds() // 60))


def _bucket(status: str, http_status: Optional[int], error: Optional[str]) -> str:
    e = (error or "").lower()
    if status == "blocked" or http_status in (403, 429):
        return "BLOCKED"
    if "proxy" in e:
        return "PROXY"
    if any(x in e for x in ("timeout", "dns", "ssl", "connection", "timed out")):
        return "NET"
    if any(x in e for x in ("parse", "json", "selector", "schema")):
        return "PARSE"
    if status == "error":
        return "DATA"
    return "OK"


def _is_cooldown_open(db: Session, key: str, cooldown_m: int, now: datetime) -> bool:
    row = get_kv(db, f"ops_alert:{key}") or {}
    last = row.get("last_sent_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except Exception:
        return True
    return now - last_dt >= timedelta(minutes=cooldown_m)


def _mark_sent(db: Session, key: str, now: datetime) -> None:
    set_kv(db, f"ops_alert:{key}", {"last_sent_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})


def _dir_size_bytes(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    total = 0
    for node in path.rglob("*"):
        if node.is_file():
            try:
                total += node.stat().st_size
            except FileNotFoundError:
                continue
    return total


def _top_subdirs(path: Path, *, limit: int = 5, max_depth: int = 2) -> list[tuple[int, str]]:
    if not path.exists() or not path.is_dir():
        return []
    dir_sizes: dict[str, int] = {}
    base_depth = len(path.resolve().parts)
    for root, dirs, files in os.walk(path, topdown=True, onerror=lambda _e: None):
        root_p = Path(root)
        depth = len(root_p.parts) - base_depth
        if depth >= max_depth:
            dirs[:] = []
        for name in files:
            fp = root_p / name
            try:
                if fp.is_symlink():
                    continue
                size = int(fp.stat().st_size)
            except (FileNotFoundError, PermissionError, OSError):
                continue
            for d in (1, 2):
                if d > max_depth or depth < d:
                    continue
                anc = root_p.parents[depth - d]
                k = str(anc)
                dir_sizes[k] = dir_sizes.get(k, 0) + size
    rows = sorted([(size, p) for p, size in dir_sizes.items()], key=lambda x: x[0], reverse=True)
    rows.sort(key=lambda x: x[0], reverse=True)
    return rows[: max(1, int(limit))]


def _human_gb(n: int) -> str:
    return f"{(int(n) / (1024**3)):.2f}GB"


def _resource_cooldown_minutes(default_minutes: int = 30) -> int:
    default_seconds = max(1, int(default_minutes)) * 60
    seconds = int(getattr(settings, "resource_alert_throttle_seconds", default_seconds) or default_seconds)
    return max(1, seconds // 60)


def _add_once(
    alerts: List[OperationalAlert],
    emitted_keys: Set[str],
    logical_key: str,
    alert: OperationalAlert,
) -> None:
    if logical_key in emitted_keys:
        return
    emitted_keys.add(logical_key)
    alerts.append(alert)

def collect_operational_alerts(
    db: Session,
    now: Optional[datetime] = None,
    *,
    consume_cooldown: bool = True,
) -> List[OperationalAlert]:
    now = _now(now)
    alerts: List[OperationalAlert] = []
    emitted_source_alerts: Set[str] = set()

    last_hb = db.query(SystemLog).filter(SystemLog.component == "scheduler", SystemLog.message == "heartbeat").order_by(SystemLog.created_at.desc()).first()
    hb_age = _age_minutes(getattr(last_hb, "created_at", None), now)
    if hb_age is None or hb_age > 180:
        alerts.append(OperationalAlert("scheduler_stale_global", f"🚨 Scheduler sem heartbeat efetivo há {hb_age or '-'}m. Próximo passo: rode /admin health e /admin audit.", 30))

    configs = {c.source: c for c in db.query(SourceConfig).filter(SourceConfig.is_enabled == True).all()}
    states = {s.source: s for s in db.query(SourceState).all()}
    for src, cfg in configs.items():
        plugin = get_source(src)
        if not should_include_in_critical_stale(plugin, cfg):
            continue
        st = states.get(src)
        eval_ = evaluate_source_staleness(now=now, last_run_at=getattr(st, "last_effective_run_at", None) or getattr(st, "last_run_at", None), sched_minutes=int(cfg.sched_minutes or 0), factor=float(getattr(settings, "source_stale_factor", 2.0) or 2.0), min_global_minutes=int(getattr(settings, "source_stale_min_minutes", 180) or 180))
        ctx = _source_ops_context(db, src, cfg, st, now)
        backoff_until_dt = _as_utc(getattr(st, "next_allowed_at", None) if st else None)
        backoff_active = bool(backoff_until_dt and backoff_until_dt > _as_utc(now))
        status_backoff = _status_is_backoff(getattr(st, "last_status", None) if st else None)
        source_backoff_key = f"source_backoff:{src}"
        if eval_.stale:
            if backoff_active or status_backoff:
                until_dt = backoff_until_dt
                until = until_dt.astimezone(timezone.utc).strftime("%H:%MZ") if until_dt else "-"
                _add_once(
                    alerts,
                    emitted_source_alerts,
                    source_backoff_key,
                    OperationalAlert(
                        f"source_blocked_backoff:{src}",
                        f"⚠️ Source {src} em backoff ativo até {until}.\n"
                        f"Sem execução real há {eval_.age_minutes}m porque o circuit breaker/backoff está segurando novas tentativas.\n"
                        f"{_source_status_commands(src, ctx)}",
                        60,
                    ),
                )
            else:
                _add_once(
                    alerts,
                    emitted_source_alerts,
                    f"source_stale:{src}",
                    OperationalAlert(f"source_stale:{src}", f"🚨 Source {src} stale age={eval_.age_minutes}m status={(getattr(st,'last_status',None) or '-').upper()}. Próximo passo: /admin audit ou /admin sources show {src}.", 60),
                )

        if backoff_active and backoff_until_dt and backoff_until_dt > _as_utc(now + timedelta(minutes=30)):
            until = backoff_until_dt.astimezone(timezone.utc).strftime("%H:%MZ")
            _add_once(
                alerts,
                emitted_source_alerts,
                source_backoff_key,
                OperationalAlert(
                    f"source_blocked_backoff:{src}",
                    f"⚠️ Source {src} em backoff ativo até {until}.\n"
                    f"Próximo passo: aguarde backoff ou valide bloqueio em /admin health.\n"
                    f"{_source_status_commands(src, ctx)}",
                    60,
                ),
            )

    recent_err = db.query(SourceRun).filter(SourceRun.created_at >= now - timedelta(minutes=90), SourceRun.status.in_(["blocked", "error"])).order_by(SourceRun.created_at.desc()).limit(120).all()
    by_source_bucket = {}
    for r in recent_err:
        b = _bucket(r.status, r.http_status, r.error)
        k = (r.source, b)
        by_source_bucket[k] = by_source_bucket.get(k, 0) + 1
    for (src, b), n in by_source_bucket.items():
        if n >= 3 and src in configs:
            plugin = get_source(src)
            cfg = configs.get(src)
            op_class = classify_source_operational_role(plugin, cfg=cfg)
            if not op_class.include_in_critical_stale:
                continue
            st = states.get(src)
            st_next = _as_utc(getattr(st, "next_allowed_at", None) if st else None)
            if b == "BLOCKED" and st_next and st_next > _as_utc(now):
                continue
            alerts.append(OperationalAlert(f"source_error:{src}:{b}", f"⚠️ Source {src} com recorrência {b} ({n}x/90m). Próximo passo: /admin audit e revisar /admin sources show {src}.", 60))

    for queue in ("http", "browser"):
        running_old = db.query(func.count(ScrapeJob.id)).filter(ScrapeJob.queue == queue, ScrapeJob.status == "running", ScrapeJob.started_at < now - timedelta(minutes=45)).scalar() or 0
        queued = db.query(func.count(ScrapeJob.id)).filter(ScrapeJob.queue == queue, ScrapeJob.status == "queued").scalar() or 0
        if running_old > 0 or queued > 150:
            alerts.append(OperationalAlert(f"scrape_jobs_stuck:{queue}", f"⚠️ Fila {queue} com sinal de travamento: queued={queued} running_old={running_old}. Próximo passo: /admin audit.", 30))

    notif_old = db.query(func.count(Notification.id)).filter(Notification.status.in_(["queued", "processing"]), Notification.created_at < now - timedelta(minutes=45)).scalar() or 0
    if notif_old > 20:
        alerts.append(OperationalAlert("notifications_stuck", f"⚠️ Sender possivelmente parado: notifications antigas={notif_old}. Próximo passo: /admin health e /admin audit.", 30))

    try:
        mem = psutil.virtual_memory()
        ram_threshold = float(getattr(settings, "ram_alert_threshold", 85.0) or 85.0)
        if float(mem.percent) >= ram_threshold:
            alerts.append(OperationalAlert("ram_pressure", f"🚨 RAM em {mem.percent:.1f}% (threshold {ram_threshold:.1f}%).", _resource_cooldown_minutes()))
    except Exception:
        pass

    try:
        disk = shutil.disk_usage("/")
        used_pct = (disk.used / disk.total) * 100 if disk.total else 0.0
        disk_threshold = float(getattr(settings, "disk_alert_root_used_pct", 85.0) or 85.0)
        if used_pct >= disk_threshold:
            alerts.append(OperationalAlert("disk_root_pressure", f"🚨 Disco '/' em {used_pct:.1f}% (threshold {disk_threshold:.1f}%). Próximo passo: python scripts/disk_audit.py", _resource_cooldown_minutes()))
    except Exception:
        pass

    try:
        cache_limit_bytes = int(getattr(settings, "filesystem_cleanup_cache_max_bytes", 3 * (1024 ** 3)) or 3 * (1024 ** 3))
        cache_dir = Path(getattr(settings, "runtime_cache_dir", "/var/cache/autohunter")).expanduser().resolve()
        cache_size_bytes = _dir_size_bytes(cache_dir)
        alert_key = "disk_cache_pressure"
        cooldown_m = _resource_cooldown_minutes()
        if cache_size_bytes >= cache_limit_bytes > 0 and _is_cooldown_open(db, alert_key, cooldown_m, now):
            top = _top_subdirs(cache_dir, limit=5, max_depth=2)
            top_msg = ", ".join([f"{Path(p).name}={_human_gb(s)}" for s, p in top]) if top else "sem subdirs legíveis"
            over = max(0, cache_size_bytes - cache_limit_bytes)
            ts = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            alerts.append(OperationalAlert(alert_key, f"⚠️ Cache autohunter em {_human_gb(cache_size_bytes)} (limite {_human_gb(cache_limit_bytes)}, excesso {_human_gb(over)}) em {ts}. Top 5 dirs: {top_msg}. Próximo passo: python -m app.ops.cleanup_filesystem (dry-run) e depois python -m app.ops.cleanup_filesystem --apply.", cooldown_m))
    except Exception:
        pass

    due = [a for a in alerts if _is_cooldown_open(db, a.key, a.cooldown_minutes, now)]
    if consume_cooldown:
        for a in due:
            _mark_sent(db, a.key, now)
    return due
