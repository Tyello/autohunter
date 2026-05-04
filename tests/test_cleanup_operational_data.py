import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _load():
    p = Path('scripts/cleanup_operational_data.py')
    spec = importlib.util.spec_from_file_location('cleanup_operational_data', p)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_cleanup_has_safe_default_apply_flag():
    mod = _load()
    assert mod.BATCH_SIZE > 0


def test_dry_run_does_not_execute_delete_and_counts_total():
    mod = _load()

    class DB:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            q = str(sql)
            self.calls.append(q)
            class R:
                def scalar_one(self):
                    return 42
            return R()

    db = DB()
    count = mod._count_candidates(db, 'SELECT count(*) FROM notifications WHERE created_at < :cut', {'cut': datetime.now(timezone.utc)})
    assert count == 42
    assert all('DELETE' not in q.upper() for q in db.calls)


def _seed_sqlite(session):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=100)
    recent = now - timedelta(days=1)
    session.execute(text('CREATE TABLE notifications (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)'))
    session.execute(text('CREATE TABLE scrape_jobs (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT)'))
    for i, status in enumerate(['queued', 'processing', 'sent', 'failed', 'suppressed', 'discarded'], start=1):
        dt = old if status in {'sent', 'failed', 'suppressed', 'discarded'} else recent
        session.execute(text('INSERT INTO notifications (id,status,created_at) VALUES (:id,:status,:created_at)'), {'id': i, 'status': status, 'created_at': dt.isoformat()})
    for i, status in enumerate(['queued', 'running', 'processing', 'done', 'failed'], start=1):
        dt = old if status in {'done', 'failed'} else recent
        session.execute(text('INSERT INTO scrape_jobs (id,status,created_at) VALUES (:id,:status,:created_at)'), {'id': i, 'status': status, 'created_at': dt.isoformat()})
    session.commit()


def test_apply_delete_only_old_terminal_statuses():
    mod = _load()
    eng = create_engine('sqlite+pysqlite:///:memory:', future=True)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as db:
        _seed_sqlite(db)
        c = mod._delete_candidates_in_batches(db, "DELETE FROM notifications WHERE status IN ('sent','failed','suppressed','discarded')", {})
        assert c == 4
        left = [r[0] for r in db.execute(text('SELECT status FROM notifications ORDER BY id')).fetchall()]
        assert left == ['queued', 'processing']


def test_sqlite_apply_blocked(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod.settings, 'database_url', 'sqlite+pysqlite:///:memory:')
    monkeypatch.setattr('sys.argv', ['cleanup_operational_data.py', '--apply'])
    with pytest.raises(SystemExit):
        mod.main()
