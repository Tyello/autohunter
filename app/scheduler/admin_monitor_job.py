from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
import hashlib

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.system_log import SystemLog
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.services.app_kv_service import get_kv, set_kv
from app.services.admin_alerts_service import send_admin_text
from app.models.source_config import SourceConfig
from app.services.source_staleness_service import evaluate_source_staleness, heartbeat_is_stale
from app.services.system_logs_service import log


KV_KEY = "admin_monitor:cursor"
KV_KEY_GLOBAL_STALE = "admin_monitor:global_stale"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # allow 'Z'
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2)
    except Exception:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_status(status: str, err: str | None) -> str:
    h = hashlib.sha1()
    h.update((status or "").encode("utf-8"))
    h.update(b"\n")
    h.update((err or "").encode("utf-8"))
    return h.hexdigest()


def _get_cursor(db: Session) -> datetime:
    v = get_kv(db, KV_KEY) or {}
    dt = _parse_iso(v.get("last_checked_at"))
    if dt:
        return dt
    # primeira execução: olha um pouco pra trás, mas sem spam
    return _utcnow() - timedelta(seconds=int(getattr(settings, "admin_monitor_seconds", 60) or 60))


def _set_cursor(db: Session, dt: datetime) -> None:
    set_kv(db, KV_KEY, {"last_checked_at": _iso(dt)})


def _should_alert_source(db: Session, source: str, status: str, err: str | None, now: datetime) -> bool:
    throttle_s = int(getattr(settings, "admin_alerts_throttle_seconds", 300) or 300)
    st = db.query(SourceState).filter(SourceState.source == source).first()
    if not st:
        st = SourceState(source=source)
        db.add(st)
        db.flush()

    new_hash = _hash_status(status, (err or "")[:200])
    # se nunca alertou, ok
    if not st.last_admin_alert_at:
        st.last_admin_alert_at = now
        st.last_admin_alert_status = status
        st.last_admin_alert_error_hash = new_hash
        db.add(st)
        return True

    # se mudou status/erro, alerta mesmo dentro do throttle (sinal novo)
    if (st.last_admin_alert_status != status) or (st.last_admin_alert_error_hash != new_hash):
        st.last_admin_alert_at = now
        st.last_admin_alert_status = status
        st.last_admin_alert_error_hash = new_hash
        db.add(st)
        return True

    # se não mudou, respeita throttle
    if (now - st.last_admin_alert_at).total_seconds() >= throttle_s:
        st.last_admin_alert_at = now
        db.add(st)
        return True

    return False


def job_admin_monitor() -> None:
    if not getattr(settings, "admin_monitor_enabled", True):
        return

    now = _utcnow()
    with SessionLocal() as db:
        cursor = _get_cursor(db)

        # 1) system logs (warn/error)
        logs = (
            db.query(SystemLog)
            .filter(SystemLog.created_at > cursor)
            .filter(SystemLog.level.in_(["warn", "error"]))
            .order_by(SystemLog.created_at.asc())
            .limit(50)
            .all()
        )

        # 2) source runs (blocked/error)
        runs = (
            db.query(SourceRun)
            .filter(SourceRun.created_at > cursor)
            .filter(SourceRun.status.in_(["blocked", "error"]))
            .order_by(SourceRun.created_at.asc())
            .limit(50)
            .all()
        )

        # 3) staleness snapshot (source + global scheduler)
        configs = db.query(SourceConfig).all()
        states = {s.source: s for s in db.query(SourceState).all()}
        stale_rows: list[tuple[str, int | None, int, int | None]] = []
        for cfg in configs:
            if not bool(cfg.is_enabled):
                continue
            st = states.get(cfg.source)
            eval_ = evaluate_source_staleness(
                now=now,
                last_run_at=(st.last_run_at if st else None),
                sched_minutes=int(cfg.sched_minutes or 0),
                factor=float(getattr(settings, "source_stale_factor", 2.0) or 2.0),
                min_global_minutes=int(getattr(settings, "source_stale_min_minutes", 180) or 180),
            )
            if eval_.stale:
                stale_rows.append((cfg.source, eval_.age_minutes, eval_.threshold_minutes, eval_.overdue_minutes))

        last_hb = (
            db.query(SystemLog)
            .filter(SystemLog.component == "scheduler")
            .filter(SystemLog.message == "heartbeat")
            .order_by(SystemLog.created_at.desc())
            .first()
        )
        last_hb_at = getattr(last_hb, "created_at", None)
        hb_stale = heartbeat_is_stale(
            now,
            last_hb_at,
            stale_after_minutes=int(getattr(settings, "scheduler_heartbeat_stale_minutes", 15) or 15),
        )

        enabled_count = sum(1 for c in configs if bool(c.is_enabled))
        stale_count = len(stale_rows)
        stale_ratio = (stale_count / enabled_count) if enabled_count else 0.0
        is_global_stale = (
            stale_count >= int(getattr(settings, "scheduler_global_stale_min_sources", 3) or 3)
            and stale_ratio >= float(getattr(settings, "scheduler_global_stale_ratio", 0.6) or 0.6)
        ) or hb_stale

        # Avança cursor já (evita loop se falhar envio)
        _set_cursor(db, now)
        db.commit()

        # Alert por fonte (throttle)
        by_source: dict[str, SourceRun] = {}
        for r in runs:
            by_source[r.source] = r  # fica com o mais recente por source (asc -> sobrescreve)

        for source, r in by_source.items():
            err = r.error or ""
            if not _should_alert_source(db, source, r.status, err, now):
                continue
            msg = (
                f"⚠️ Fonte {source}: {r.status.upper()}\n"
                f"quando: {r.created_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}\n"
                f"http: {r.http_status or '-'}\n"
                f"dur: {r.duration_ms or '-'}ms\n"
                f"err: {(err[:240] + ('…' if len(err) > 240 else '')) or '-'}"
            )
            send_admin_text(msg)

        for source, age_m, threshold_m, overdue_m in stale_rows:
            err = f"source stale age={age_m}m threshold={threshold_m}m overdue={overdue_m}m"
            if not _should_alert_source(db, source, "stale", err, now):
                continue
            send_admin_text(f"⚠️ Fonte {source}: STALE\n{err}")

        prev_global = get_kv(db, KV_KEY_GLOBAL_STALE) or {}
        prev_state = bool(prev_global.get("is_global_stale", False))
        if is_global_stale and not prev_state:
            send_admin_text(
                "🚨 Scheduler possivelmente stale/parado\n"
                f"stale_sources={stale_count}/{enabled_count} ({int(round(stale_ratio * 100))}%)\n"
                f"last_heartbeat={_iso(last_hb_at) if last_hb_at else '-'}"
            )
            log(
                db,
                "warn",
                "admin_monitor",
                "scheduler_global_stale_detected",
                {
                    "stale_sources": stale_count,
                    "enabled_sources": enabled_count,
                    "stale_ratio": stale_ratio,
                    "last_heartbeat": _iso(last_hb_at) if last_hb_at else None,
                },
                event_type="scheduler_global_stale",
            )
        if (not is_global_stale) and prev_state:
            log(
                db,
                "info",
                "admin_monitor",
                "scheduler_global_stale_recovered",
                {
                    "stale_sources": stale_count,
                    "enabled_sources": enabled_count,
                    "stale_ratio": stale_ratio,
                    "last_heartbeat": _iso(last_hb_at) if last_hb_at else None,
                },
                event_type="scheduler_global_stale",
            )
        set_kv(db, KV_KEY_GLOBAL_STALE, {"is_global_stale": is_global_stale, "updated_at": _iso(now)})

        # Digest de system logs (evita spam, manda 1 mensagem compacta)
        limit = int(getattr(settings, "admin_errors_digest_limit", 10) or 10)
        if logs:
            items = logs[-limit:] if len(logs) > limit else logs
            lines = ["🧯 AutoHunter — novos erros/logs"]
            for row in items:
                lines.append(
                    f"- [{row.level}] {row.component}: {(row.message or '')[:180]}"
                )
            send_admin_text("\n".join(lines))

        db.commit()
