from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.core.settings import settings
from app.models.source_run import SourceRun
from app.models.system_log import SystemLog
from app.models.autopilot_finding import AutopilotFinding
from app.models.scrape_job import ScrapeJob
from app.models.notification import Notification
from app.services.scrape_jobs_service import has_active_source_queue_partial_index


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sha1(s: str) -> str:
    h = hashlib.sha1()
    h.update((s or "").encode("utf-8"))
    return h.hexdigest()


def _err_class(err: Optional[str]) -> str:
    if not err:
        return ""
    # expected format: "TypeError: message"
    if ":" in err:
        return (err.split(":", 1)[0] or "").strip()
    return (err.split("\n", 1)[0] or "").strip()


def _err_head(err: Optional[str], n: int = 180) -> str:
    if not err:
        return ""
    s = (err or "").strip().replace("\r", " ")
    s = " ".join(s.split())
    return s[:n]


@dataclass
class FindingCandidate:
    kind: str
    source: Optional[str]
    fingerprint: str
    title: str
    severity: str
    evidence: Dict[str, Any]
    suggested_actions: str


def _window_bounds(now: datetime) -> Tuple[datetime, datetime]:
    window_m = int(getattr(settings, "autopilot_window_minutes", 30) or 30)
    window_m = max(5, min(window_m, 24 * 60))
    start = now - timedelta(minutes=window_m)
    return start, now


def _baseline_bounds(now: datetime) -> Tuple[datetime, datetime]:
    # baseline: last 7d excluding current window
    end = now - timedelta(minutes=int(getattr(settings, "autopilot_window_minutes", 30) or 30))
    start = end - timedelta(days=7)
    return start, end


def _calc_rates(total: int, part: int) -> float:
    if total <= 0:
        return 0.0
    return float(part) / float(total)


def _candidate_blocked_spike(db: Session, now: datetime) -> List[FindingCandidate]:
    start, end = _window_bounds(now)
    b_start, b_end = _baseline_bounds(now)

    # Aggregate window by source
    window = (
        db.query(
            SourceRun.source.label("source"),
            func.count(SourceRun.id).label("total"),
            func.sum(case((SourceRun.status == "blocked", 1), else_=0)).label("blocked"),
        )
        .filter(SourceRun.created_at >= start)
        .filter(SourceRun.created_at < end)
        .group_by(SourceRun.source)
        .all()
    )

    out: List[FindingCandidate] = []
    for row in window:
        src = row.source
        total = int(row.total or 0)
        blocked = int(row.blocked or 0)
        if total < 5:
            continue
        blocked_rate = _calc_rates(total, blocked)

        # Baseline blocked rate for this source
        b = (
            db.query(
                func.count(SourceRun.id).label("total"),
                func.sum(case((SourceRun.status == "blocked", 1), else_=0)).label("blocked"),
            )
            .filter(SourceRun.source == src)
            .filter(SourceRun.created_at >= b_start)
            .filter(SourceRun.created_at < b_end)
            .first()
        )
        b_total = int((b.total if b else 0) or 0)
        b_blocked = int((b.blocked if b else 0) or 0)
        b_rate = _calc_rates(b_total, b_blocked)

        # Trigger: blocked >= 30% and significantly above baseline
        if blocked_rate < 0.30:
            continue
        if b_total >= 10 and blocked_rate < max(0.30, b_rate * 2.0 + 0.10):
            continue

        # Evidence samples
        samples = (
            db.query(SourceRun)
            .filter(SourceRun.source == src)
            .filter(SourceRun.created_at >= start)
            .filter(SourceRun.created_at < end)
            .filter(SourceRun.status == "blocked")
            .order_by(SourceRun.created_at.desc())
            .limit(5)
            .all()
        )
        sample_ids = [str(s.id) for s in samples]
        sample_urls = [s.url for s in samples if s.url][:5]
        http = samples[0].http_status if samples else None

        fp = _sha1(f"blocked_spike|{src}|{http or ''}|{start.isoformat()}")
        out.append(
            FindingCandidate(
                kind="blocked_spike",
                source=src,
                fingerprint=fp,
                title=f"Fonte {src}: spike de bloqueios ({blocked}/{total} = {blocked_rate:.0%})",
                severity="warn" if blocked_rate < 0.60 else "error",
                evidence={
                    "window": {"start": start.isoformat(), "end": end.isoformat()},
                    "total": total,
                    "blocked": blocked,
                    "blocked_rate": blocked_rate,
                    "baseline": {"total": b_total, "blocked": b_blocked, "blocked_rate": b_rate},
                    "sample_run_ids": sample_ids,
                    "sample_urls": sample_urls,
                    "http_status": http,
                },
                suggested_actions=(
                    "Ações sugeridas: reduzir rate, aumentar cooldown/backoff, alternar proxy, "
                    "habilitar browser_fallback/force_browser para a fonte e coletar evidência (HTML/screenshot) "
                    "para ajustar o scraper."
                ),
            )
        )
    return out


def _candidate_error_burst(db: Session, now: datetime) -> List[FindingCandidate]:
    start, end = _window_bounds(now)

    min_hits = int(getattr(settings, "autopilot_min_hits", 3) or 3)
    min_hits = max(2, min(min_hits, 50))

    # group by source + err_class + http_status
    rows = (
        db.query(
            SourceRun.source.label("source"),
            func.coalesce(SourceRun.http_status, 0).label("http_status"),
            func.count(SourceRun.id).label("cnt"),
            func.min(SourceRun.created_at).label("first_at"),
            func.max(SourceRun.created_at).label("last_at"),
            func.max(SourceRun.error).label("err_any"),
        )
        .filter(SourceRun.created_at >= start)
        .filter(SourceRun.created_at < end)
        .filter(SourceRun.status == "error")
        .group_by(SourceRun.source, func.coalesce(SourceRun.http_status, 0), func.substr(SourceRun.error, 1, 80))
        .order_by(func.count(SourceRun.id).desc())
        .limit(25)
        .all()
    )

    out: List[FindingCandidate] = []
    for r in rows:
        cnt = int(r.cnt or 0)
        if cnt < min_hits:
            continue
        src = r.source
        http = int(r.http_status or 0) or None
        err_any = (r.err_any or "").strip()
        err_cls = _err_class(err_any)
        err_head = _err_head(err_any, 160)

        samples = (
            db.query(SourceRun)
            .filter(SourceRun.source == src)
            .filter(SourceRun.created_at >= start)
            .filter(SourceRun.created_at < end)
            .filter(SourceRun.status == "error")
            .filter(SourceRun.error.ilike(f"{err_cls}%") if err_cls else True)
            .order_by(SourceRun.created_at.desc())
            .limit(5)
            .all()
        )
        sample_ids = [str(s.id) for s in samples]
        sample_urls = [s.url for s in samples if s.url][:5]

        fp = _sha1(f"error_burst|{src}|{http or ''}|{err_cls}|{err_head}")
        out.append(
            FindingCandidate(
                kind="error_burst",
                source=src,
                fingerprint=fp,
                title=f"Fonte {src}: burst de erros ({cnt}x) — {err_cls or 'Exception'}",
                severity="error",
                evidence={
                    "window": {"start": start.isoformat(), "end": end.isoformat()},
                    "count": cnt,
                    "http_status": http,
                    "error_class": err_cls,
                    "error_head": err_head,
                    "sample_run_ids": sample_ids,
                    "sample_urls": sample_urls,
                },
                suggested_actions=(
                    "Ações sugeridas: abrir evidência (URL/HTML), validar seletores/parsers, "
                    "e se for erro de rede: aumentar timeout/retries ou ajustar proxy/DNS."
                ),
            )
        )
    return out


def _candidate_found_drop(db: Session, now: datetime) -> List[FindingCandidate]:
    start, end = _window_bounds(now)
    b_start, b_end = _baseline_bounds(now)

    # window avg found per source
    window = (
        db.query(
            SourceRun.source.label("source"),
            func.count(SourceRun.id).label("total"),
            func.avg(func.coalesce(SourceRun.items_found, 0)).label("avg_found"),
        )
        .filter(SourceRun.created_at >= start)
        .filter(SourceRun.created_at < end)
        .filter(SourceRun.status == "success")
        .group_by(SourceRun.source)
        .all()
    )

    out: List[FindingCandidate] = []
    for w in window:
        src = w.source
        total = int(w.total or 0)
        if total < 5:
            continue
        avg_found = float(w.avg_found or 0.0)

        b = (
            db.query(
                func.count(SourceRun.id).label("total"),
                func.avg(func.coalesce(SourceRun.items_found, 0)).label("avg_found"),
            )
            .filter(SourceRun.source == src)
            .filter(SourceRun.created_at >= b_start)
            .filter(SourceRun.created_at < b_end)
            .filter(SourceRun.status == "success")
            .first()
        )
        b_total = int((b.total if b else 0) or 0)
        b_avg = float((b.avg_found if b else 0.0) or 0.0)

        if b_total < 20 or b_avg < 3:
            continue

        # Trigger: drop > 80%
        if avg_found > b_avg * 0.2:
            continue

        samples = (
            db.query(SourceRun)
            .filter(SourceRun.source == src)
            .filter(SourceRun.created_at >= start)
            .filter(SourceRun.created_at < end)
            .filter(SourceRun.status == "success")
            .order_by(SourceRun.created_at.desc())
            .limit(5)
            .all()
        )
        sample_urls = [s.url for s in samples if s.url][:5]
        fp = _sha1(f"found_drop|{src}|{int(b_avg)}|{int(avg_found)}")
        out.append(
            FindingCandidate(
                kind="found_drop",
                source=src,
                fingerprint=fp,
                title=f"Fonte {src}: queda forte de itens encontrados (média {avg_found:.1f} vs {b_avg:.1f})",
                severity="warn",
                evidence={
                    "window": {"start": start.isoformat(), "end": end.isoformat()},
                    "avg_found": avg_found,
                    "baseline": {"total": b_total, "avg_found": b_avg},
                    "sample_urls": sample_urls,
                },
                suggested_actions=(
                    "Ações sugeridas: validar se houve mudança no HTML/JSON da fonte, "
                    "checagem de filtros/URLs, e coletar 1-2 páginas para atualizar o parser."
                ),
            )
        )
    return out


def _candidate_system_log_errors(db: Session, now: datetime) -> List[FindingCandidate]:
    start, end = _window_bounds(now)
    min_hits = int(getattr(settings, "autopilot_min_hits", 3) or 3)
    min_hits = max(2, min(min_hits, 50))

    rows = (
        db.query(
            SystemLog.component.label("component"),
            func.coalesce(SystemLog.event_type, "").label("event_type"),
            func.coalesce(SystemLog.source, "").label("source"),
            func.coalesce(SystemLog.level, "").label("level"),
            func.coalesce(SystemLog.fingerprint, "").label("fingerprint"),
            func.max(SystemLog.message).label("sample_message"),
            func.count(SystemLog.id).label("cnt"),
        )
        .filter(SystemLog.created_at >= start)
        .filter(SystemLog.created_at < end)
        .filter(SystemLog.level.in_(["warn", "error"]))
        .group_by(
            SystemLog.component,
            func.coalesce(SystemLog.event_type, ""),
            func.coalesce(SystemLog.source, ""),
            func.coalesce(SystemLog.level, ""),
            func.coalesce(SystemLog.fingerprint, ""),
        )
        .order_by(func.count(SystemLog.id).desc())
        .limit(25)
        .all()
    )

    out: List[FindingCandidate] = []
    for r in rows:
        cnt = int(r.cnt or 0)
        if cnt < min_hits:
            continue
        comp = r.component
        msg = (r.sample_message or "")[:200]
        fp = _sha1(f"log_burst|{comp}|{r.event_type}|{r.source}|{r.level}|{r.fingerprint}")
        samples = (
            db.query(SystemLog)
            .filter(SystemLog.created_at >= start)
            .filter(SystemLog.created_at < end)
            .filter(SystemLog.level.in_(["warn", "error"]))
            .filter(SystemLog.component == comp)
            .filter(func.coalesce(SystemLog.event_type, "") == (r.event_type or ""))
            .filter(func.coalesce(SystemLog.source, "") == (r.source or ""))
            .filter(func.coalesce(SystemLog.level, "") == (r.level or ""))
            .filter(func.coalesce(SystemLog.fingerprint, "") == (r.fingerprint or ""))
            .order_by(SystemLog.created_at.desc())
            .limit(5)
            .all()
        )
        out.append(
            FindingCandidate(
                kind="log_error_burst",
                source=None,
                fingerprint=fp,
                title=f"Erros recorrentes: {comp} — {msg} ({cnt}x)",
                severity="warn" if cnt < (min_hits * 2) else "error",
                evidence={
                    "window": {"start": start.isoformat(), "end": end.isoformat()},
                    "count": cnt,
                    "component": comp,
                    "event_type": r.event_type,
                    "source": r.source,
                    "level": r.level,
                    "fingerprint": r.fingerprint,
                    "sample_message": msg,
                    "sample_log_ids": [str(s.id) for s in samples],
                },
                suggested_actions="Ações sugeridas: abrir stacktrace (payload.tb) nos logs e corrigir o fluxo.",
            )
        )
    return out


def _candidate_operational(db: Session, now: datetime) -> List[FindingCandidate]:
    out: List[FindingCandidate] = []
    queued_threshold = int(getattr(settings, "autopilot_scrape_jobs_queued_threshold", 100) or 100)
    running_old_minutes = int(getattr(settings, "autopilot_scrape_jobs_running_old_minutes", 20) or 20)
    sender_idle_minutes = int(getattr(settings, "autopilot_sender_idle_minutes", 60) or 60)
    cutoff_running = now - timedelta(minutes=running_old_minutes)
    running_old = db.query(func.count(ScrapeJob.id)).filter(ScrapeJob.status == "running", ScrapeJob.started_at.isnot(None), ScrapeJob.started_at < cutoff_running).scalar() or 0
    queued = db.query(func.count(ScrapeJob.id)).filter(ScrapeJob.status == "queued").scalar() or 0
    if int(queued) >= queued_threshold or int(running_old) > 0:
        out.append(FindingCandidate(kind="scrape_jobs_stuck", source=None, fingerprint=_sha1("scrape_jobs_stuck_global"), title=f"Fila scrape_jobs degradada (queued={int(queued)}, running_old={int(running_old)})", severity="error" if int(running_old) > 0 else "warn", evidence={"queued": int(queued), "running_old": int(running_old), "thresholds": {"queued": queued_threshold, "running_old_minutes": running_old_minutes}}, suggested_actions="Ações sugeridas: validar workers/scheduler e requeue de jobs running antigos."))

    hb = db.query(SystemLog).filter(SystemLog.component == "scheduler", SystemLog.message == "heartbeat").order_by(SystemLog.created_at.desc()).first()
    hb_at = _as_utc(hb.created_at) if hb else None
    source_runs_window_m = int(getattr(settings, "autopilot_source_runs_zero_window_minutes", 30) or 30)
    sr_cut = now - timedelta(minutes=source_runs_window_m)
    runs_recent = db.query(func.count(SourceRun.id)).filter(SourceRun.created_at >= sr_cut).scalar() or 0
    if hb_at and hb_at >= sr_cut and int(runs_recent) == 0:
        out.append(FindingCandidate(kind="scheduler_heartbeat_without_runs", source=None, fingerprint=_sha1("scheduler_heartbeat_without_runs"), title="Scheduler heartbeat ativo, mas source_runs zerado na janela", severity="error", evidence={"heartbeat_at": hb_at.isoformat(), "window_minutes": source_runs_window_m, "source_runs_count": int(runs_recent)}, suggested_actions="Ações sugeridas: revisar scheduler tick/enqueue e conectividade do worker com o banco."))

    sent_cut = now - timedelta(minutes=sender_idle_minutes)
    sent_recent = db.query(func.count(Notification.id)).filter(Notification.sent_at.isnot(None), Notification.sent_at >= sent_cut).scalar() or 0
    queued_old = db.query(func.count(Notification.id)).filter(Notification.status == "queued", Notification.created_at < sent_cut).scalar() or 0
    if int(sent_recent) == 0 and int(queued_old) > 0:
        out.append(FindingCandidate(kind="sender_idle_with_backlog", source=None, fingerprint=_sha1("sender_idle_with_backlog"), title=f"Sender sem envios na janela e backlog antigo (queued_old={int(queued_old)})", severity="warn", evidence={"sender_idle_minutes": sender_idle_minutes, "sent_recent": int(sent_recent), "queued_old": int(queued_old)}, suggested_actions="Ações sugeridas: validar sender_job, token Telegram e fila notifications."))

    if not has_active_source_queue_partial_index(db):
        out.append(FindingCandidate(kind="scrape_jobs_missing_critical_index", source=None, fingerprint=_sha1("scrape_jobs_missing_critical_index"), title="Índice crítico de dedupe em scrape_jobs ausente", severity="error", evidence={"index_check": "active_source_queue_partial_index", "ok": False}, suggested_actions="Ações sugeridas: aplicar migration/DDL do índice parcial para evitar duplicação e lock contention."))
    return out


def build_candidates(db: Session, now: Optional[datetime] = None) -> List[FindingCandidate]:
    now = now or _utcnow()
    cands: List[FindingCandidate] = []
    cands.extend(_candidate_blocked_spike(db, now))
    cands.extend(_candidate_error_burst(db, now))
    cands.extend(_candidate_found_drop(db, now))
    cands.extend(_candidate_system_log_errors(db, now))
    cands.extend(_candidate_operational(db, now))
    return cands


def upsert_findings(db: Session, candidates: List[FindingCandidate], now: Optional[datetime] = None) -> List[AutopilotFinding]:
    now = now or _utcnow()
    touched: List[AutopilotFinding] = []

    for c in candidates:
        row = db.query(AutopilotFinding).filter(AutopilotFinding.fingerprint == c.fingerprint).first()
        if not row:
            row = AutopilotFinding(
                status="open",
                kind=c.kind,
                source=c.source,
                fingerprint=c.fingerprint,
                title=c.title,
                severity=c.severity,
                first_seen_at=now,
                last_seen_at=now,
                hit_count=1,
                evidence=c.evidence,
                suggested_actions=c.suggested_actions,
            )
            db.add(row)
            db.flush()
        else:
            if row.status != "open":
                # Não reabre automaticamente: mantém histórico. Se quiser reabrir, admin fecha/abre manual.
                pass
            row.last_seen_at = now
            row.hit_count = int(row.hit_count or 0) + 1
            row.title = c.title
            row.severity = c.severity
            row.evidence = c.evidence
            row.suggested_actions = c.suggested_actions
            db.add(row)

        touched.append(row)

    return touched


def should_alert(row: AutopilotFinding, now: Optional[datetime] = None) -> bool:
    now = now or _utcnow()
    throttle_s = int(getattr(settings, "autopilot_alert_throttle_seconds", 1800) or 1800)
    throttle_s = max(60, min(throttle_s, 24 * 3600))

    if not row.last_alert_at:
        return True

    return (now - row.last_alert_at).total_seconds() >= throttle_s


def mark_alerted(db: Session, row: AutopilotFinding, now: Optional[datetime] = None) -> None:
    now = now or _utcnow()
    row.last_alert_at = now
    db.add(row)


def format_alert(row: AutopilotFinding) -> str:
    src = (row.source or "-")
    sev_icon = "🟡" if row.severity == "warn" else ("🔴" if row.severity == "error" else "🔵")
    lines = [f"{sev_icon} Autopilot — {row.kind}", f"fonte: {src}", f"título: {row.title}"]

    ev = row.evidence or {}
    if row.kind in ("blocked_spike", "error_burst", "found_drop"):
        w = ev.get("window") or {}
        if w.get("start") and w.get("end"):
            lines.append(f"janela: {w.get('start')} → {w.get('end')}")
    # sample urls
    sample_urls = ev.get("sample_urls") or []
    if isinstance(sample_urls, list) and sample_urls:
        lines.append("exemplos:")
        for u in sample_urls[:3]:
            if u:
                lines.append(f"- {u}")
    if row.suggested_actions:
        lines.append("")
        lines.append(row.suggested_actions)

    return "\n".join(lines)


def format_daily_digest(rows: List[AutopilotFinding]) -> str:
    if not rows:
        return "✅ Autopilot operacional — sem novos problemas relevantes"

    lines = ["🧠 Autopilot — digest (últimas 24h)"]
    grouped: dict[tuple[str, str], list[AutopilotFinding]] = {}
    for r in rows:
        grouped.setdefault((r.severity or "warn", r.kind or "unknown"), []).append(r)
    for sev in ("error", "warn", "info"):
        sev_groups = [(k, v) for k, v in grouped.items() if k[0] == sev]
        if not sev_groups:
            continue
        lines.append(f"{'🔴' if sev=='error' else ('🟡' if sev=='warn' else '🔵')} severity={sev}")
        for (_sev, kind), items in sorted(sev_groups, key=lambda x: (-len(x[1]), x[0][1])):
            total_hits = sum(int(i.hit_count or 0) for i in items)
            first = sorted(items, key=lambda x: int(x.hit_count or 0), reverse=True)[0]
            lines.append(f"- {kind}: casos={len(items)} hits={total_hits} | ação: {first.suggested_actions or '-'}")
    return "\n".join(lines)
