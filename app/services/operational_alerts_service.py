from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

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
from app.services.source_operational_policy import should_include_in_critical_stale
from app.services.source_staleness_service import evaluate_source_staleness
from app.sources.registry import get_source


@dataclass
class OperationalAlert:
    key: str
    message: str
    cooldown_minutes: int


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


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


def collect_operational_alerts(db: Session, now: Optional[datetime] = None) -> List[OperationalAlert]:
    now = _now(now)
    alerts: List[OperationalAlert] = []

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
        if eval_.stale:
            alerts.append(OperationalAlert(f"source_stale:{src}", f"🚨 Source {src} stale age={eval_.age_minutes}m status={(getattr(st,'last_status',None) or '-').upper()}. Próximo passo: /admin audit ou /admin sources {src}.", 60))

        if st and st.next_allowed_at and st.next_allowed_at > now + timedelta(minutes=30):
            until = st.next_allowed_at.astimezone(timezone.utc).strftime("%H:%MZ")
            alerts.append(OperationalAlert(f"source_backoff:{src}", f"⚠️ Source {src} em backoff até {until}. Próximo passo: aguarde backoff ou valide bloqueio em /admin health.", 60))

    recent_err = db.query(SourceRun).filter(SourceRun.created_at >= now - timedelta(minutes=90), SourceRun.status.in_(["blocked", "error"])).order_by(SourceRun.created_at.desc()).limit(120).all()
    by_source_bucket = {}
    for r in recent_err:
        b = _bucket(r.status, r.http_status, r.error)
        k = (r.source, b)
        by_source_bucket[k] = by_source_bucket.get(k, 0) + 1
    for (src, b), n in by_source_bucket.items():
        if n >= 3 and src in configs:
            alerts.append(OperationalAlert(f"source_error:{src}:{b}", f"⚠️ Source {src} com recorrência {b} ({n}x/90m). Próximo passo: /admin audit e revisar source {src}.", 60))

    for queue in ("http", "browser"):
        running_old = db.query(func.count(ScrapeJob.id)).filter(ScrapeJob.queue == queue, ScrapeJob.status == "running", ScrapeJob.started_at < now - timedelta(minutes=45)).scalar() or 0
        queued = db.query(func.count(ScrapeJob.id)).filter(ScrapeJob.queue == queue, ScrapeJob.status == "queued").scalar() or 0
        if running_old > 0 or queued > 150:
            alerts.append(OperationalAlert(f"scrape_jobs_stuck:{queue}", f"⚠️ Fila {queue} com sinal de travamento: queued={queued} running_old={running_old}. Próximo passo: /admin audit.", 30))

    notif_old = db.query(func.count(Notification.id)).filter(Notification.status.in_(["queued", "processing"]), Notification.created_at < now - timedelta(minutes=45)).scalar() or 0
    if notif_old > 20:
        alerts.append(OperationalAlert("notifications_stuck", f"⚠️ Sender possivelmente parado: notifications antigas={notif_old}. Próximo passo: /admin health e /admin audit.", 30))

    due = [a for a in alerts if _is_cooldown_open(db, a.key, a.cooldown_minutes, now)]
    for a in due:
        _mark_sent(db, a.key, now)
    return due
