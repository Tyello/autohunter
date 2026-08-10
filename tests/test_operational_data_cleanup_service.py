from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.operational_data_cleanup_service import (
    run_operational_cleanup,
    unprotected_cleanup_rules,
)


def test_unprotected_rules_never_touch_protected_tables():
    names = [name for name, _, _ in unprotected_cleanup_rules()]
    assert "notifications" not in names
    assert "wishlist_listing_activity" not in names
    assert set(names) == {
        "system_logs",
        "telemetry_events",
        "scrape_jobs_done",
        "scrape_jobs_failed",
        "source_runs",
    }


def _seed_sqlite(session):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=100)).isoformat()
    recent = (now - timedelta(days=1)).isoformat()
    session.execute(text("CREATE TABLE system_logs (id INTEGER PRIMARY KEY, created_at TEXT)"))
    session.execute(text("CREATE TABLE telemetry_events (id INTEGER PRIMARY KEY, created_at TEXT)"))
    session.execute(text("CREATE TABLE scrape_jobs (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)"))
    session.execute(text("CREATE TABLE source_runs (id INTEGER PRIMARY KEY, created_at TEXT)"))
    session.execute(text("INSERT INTO system_logs (id, created_at) VALUES (1, :d)"), {"d": old})
    session.execute(text("INSERT INTO system_logs (id, created_at) VALUES (2, :d)"), {"d": recent})
    session.execute(text("INSERT INTO telemetry_events (id, created_at) VALUES (1, :d)"), {"d": old})
    session.execute(text("INSERT INTO scrape_jobs (id, status, created_at) VALUES (1, 'done', :d)"), {"d": old})
    session.execute(text("INSERT INTO scrape_jobs (id, status, created_at) VALUES (2, 'failed', :d)"), {"d": old})
    session.execute(text("INSERT INTO scrape_jobs (id, status, created_at) VALUES (3, 'queued', :d)"), {"d": recent})
    session.execute(text("INSERT INTO source_runs (id, created_at) VALUES (1, :d)"), {"d": old})
    session.commit()


def test_run_operational_cleanup_deletes_old_rows_only():
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as db:
        _seed_sqlite(db)
        results = run_operational_cleanup(db)
        assert results["system_logs"] == 1
        assert results["telemetry_events"] == 1
        assert results["scrape_jobs_done"] == 1
        assert results["scrape_jobs_failed"] == 1
        assert results["source_runs"] == 1

        remaining_logs = db.execute(text("SELECT id FROM system_logs")).fetchall()
        assert [r[0] for r in remaining_logs] == [2]
        remaining_jobs = [r[0] for r in db.execute(text("SELECT status FROM scrape_jobs")).fetchall()]
        assert remaining_jobs == ["queued"]


def test_run_operational_cleanup_isolates_failure_per_table(monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as db:
        _seed_sqlite(db)

        import app.services.operational_data_cleanup_service as svc

        real_execute = db.execute

        def boom(sql, params=None, *a, **kw):
            if "system_logs" in str(sql):
                raise RuntimeError("boom")
            return real_execute(sql, params or {})

        monkeypatch.setattr(db, "execute", boom)
        results = svc.run_operational_cleanup(db)
        assert str(results["system_logs"]).startswith("error:")
        assert results["source_runs"] == 1
