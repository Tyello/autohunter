"""
Load-test report: leitura pura (nao altera nenhum dado) para acompanhar o
teste de carga pre-beta descrito em docs/OPERATIONS_RUNBOOK.md secao 14.

Roda em paralelo ao scripts/pi_load_probe.sh e mostra:
    - scrape_jobs por queue/status, com idade min/max em fila;
    - notificacao mais antiga em queued/processing;
    - falhas recentes em source_runs (ultimas 2h);
    - processos Playwright/Chromium vivos no host.

Uso:
    python scripts/load_test_report.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.session import SessionLocal


def _fmt_age(ts) -> str:
    if ts is None:
        return "-"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes}min"


def _report_scrape_jobs(db) -> None:
    rows = db.execute(
        text(
            """
            SELECT queue, status, count(*) AS n, min(created_at) AS oldest, max(updated_at) AS newest
            FROM scrape_jobs
            GROUP BY queue, status
            ORDER BY queue, status
            """
        )
    ).all()
    print("\n== scrape_jobs (queue/status) ==")
    if not rows:
        print("  (vazio)")
    for r in rows:
        print(f"  queue={r.queue:<8} status={r.status:<8} n={r.n:<6} oldest_age={_fmt_age(r.oldest)} newest_update_age={_fmt_age(r.newest)}")


def _report_notifications(db) -> None:
    row = db.execute(
        text(
            """
            SELECT status, count(*) AS n, min(created_at) AS oldest
            FROM notifications
            WHERE status IN ('queued', 'processing')
            GROUP BY status
            ORDER BY status
            """
        )
    ).all()
    print("\n== notifications em fila (queued/processing) ==")
    if not row:
        print("  (vazio — sem backlog)")
    for r in row:
        print(f"  status={r.status:<12} n={r.n:<6} oldest_age={_fmt_age(r.oldest)}")


def _report_source_run_failures(db) -> None:
    cut = datetime.now(timezone.utc) - timedelta(hours=2)
    rows = db.execute(
        text(
            """
            SELECT source, count(*) AS n
            FROM source_runs
            WHERE created_at >= :cut AND status = 'error'
            GROUP BY source
            ORDER BY n DESC
            """
        ),
        {"cut": cut},
    ).all()
    print("\n== falhas de source_runs nas ultimas 2h ==")
    if not rows:
        print("  (nenhuma falha)")
    for r in rows:
        print(f"  source={r.source:<20} failures={r.n}")


def _report_playwright_processes() -> None:
    print("\n== processos Playwright/Chromium vivos ==")
    try:
        import psutil

        from app.services.playwright_pool import _is_playwright_process
    except Exception as exc:
        print(f"  (nao foi possivel checar: {exc})")
        return

    count = 0
    for proc in psutil.process_iter(["pid"]):
        try:
            if _is_playwright_process(proc):
                count += 1
        except Exception:
            continue
    print(f"  total={count}")


def main() -> int:
    with SessionLocal() as db:
        _report_scrape_jobs(db)
        _report_notifications(db)
        _report_source_run_failures(db)
    _report_playwright_processes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
