from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

HOT_TABLES = ["scrape_jobs", "notifications", "source_runs", "system_logs", "telemetry_events", "wishlist_listing_activity", "car_listings"]


def _scalar(db: Session, sql: str, params: dict | None = None) -> int:
    try:
        return int(db.execute(text(sql), params or {}).scalar() or 0)
    except Exception:
        return 0


def collect_db_io_metrics(db: Session) -> dict[str, Any]:
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    table_rows = {t: _scalar(db, f"select count(*) from {t}") for t in HOT_TABLES}
    recent_rows = {t: _scalar(db, f"select count(*) from {t} where created_at >= :since", {"since": since_24h}) for t in HOT_TABLES if t != "car_listings"}
    scrape_jobs = dict(db.execute(text("select status, count(*) from scrape_jobs group by status")).all() or [])
    notifications = dict(db.execute(text("select status, count(*) from notifications group by status")).all() or [])
    source_runs_24h = dict(db.execute(text("select status, count(*) from source_runs where created_at >= :since group by status"), {"since": since_24h}).all() or [])
    sender_backlog = int(notifications.get("queued", 0) or 0) + int(notifications.get("processing", 0) or 0)
    churn_estimate = sum(int(v or 0) for v in recent_rows.values()) + sender_backlog + sum(int(v or 0) for v in scrape_jobs.values())
    return {"top_tables": sorted(table_rows.items(), key=lambda x: x[1], reverse=True), "recent_24h": sorted(recent_rows.items(), key=lambda x: x[1], reverse=True), "scrape_jobs_by_status": scrape_jobs, "notifications_by_status": notifications, "sender_backlog": sender_backlog, "source_runs_24h": source_runs_24h, "approx_io_churn": churn_estimate}


def render_db_io_metrics(data: dict[str, Any]) -> str:
    def fmt(rows):
        return "\n".join(f"- {k}: {v}" for k, v in rows[:7]) or "- sem dados"
    return "\n".join([
        "🧯 DB IO — Garagem Alvo",
        f"Sender backlog: {data.get('sender_backlog', 0)}",
        f"Uso aproximado de IO/churn: {data.get('approx_io_churn', 0)} eventos/linhas quentes",
        "",
        "Top tabelas (linhas):",
        fmt(data.get("top_tables") or []),
        "",
        "Top churn 24h:",
        fmt(data.get("recent_24h") or []),
        "",
        f"notifications pendentes: {(data.get('notifications_by_status') or {}).get('queued', 0)}",
        f"scrape_jobs por status: {data.get('scrape_jobs_by_status')}",
        f"source_runs últimas 24h: {data.get('source_runs_24h')}",
    ])
