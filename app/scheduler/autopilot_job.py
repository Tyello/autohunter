from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.core.settings import settings
from app.models.autopilot_finding import AutopilotFinding
from app.services.autopilot_service import build_candidates, upsert_findings, should_alert, mark_alerted, format_alert, format_daily_digest
from app.services.admin_alerts_service import send_admin_text


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def job_autopilot_scan() -> None:
    if not getattr(settings, "autopilot_enabled", True):
        return

    now = _utcnow()
    with SessionLocal() as db:
        cands = build_candidates(db, now)
        touched = upsert_findings(db, cands, now)

        # alert new / throttled findings
        sent = 0
        for row in touched:
            if row.status != "open":
                continue
            if not should_alert(row, now):
                continue
            send_admin_text(format_alert(row))
            mark_alerted(db, row, now)
            sent += 1
            # hard cap per scan (avoid spam)
            if sent >= 4:
                break

        db.commit()


def job_autopilot_daily_digest() -> None:
    if not getattr(settings, "autopilot_enabled", True):
        return
    if not getattr(settings, "autopilot_daily_digest_enabled", True):
        return

    now = _utcnow()
    since = now - timedelta(hours=24)

    with SessionLocal() as db:
        rows = (
            db.query(AutopilotFinding)
            .filter(AutopilotFinding.last_seen_at >= since)
            .filter(AutopilotFinding.status == "open")
            .order_by(AutopilotFinding.last_seen_at.desc())
            .limit(50)
            .all()
        )
        send_admin_text(format_daily_digest(rows))
        db.commit()
