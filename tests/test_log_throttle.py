"""Logs de rotina de alta frequencia sao limitados; eventos com trabalho real, nao."""

from unittest.mock import MagicMock

from app.models.system_log import SystemLog
from app.scheduler import heartbeat as hb_mod
from app.scheduler import fipe_lookup_job
from app.services import system_logs_service as sls


def test_should_log_throttled_allows_once_per_interval(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(sls.time, "monotonic", lambda: now[0])
    assert sls.should_log_throttled("k", 60) is True
    now[0] = 130.0
    assert sls.should_log_throttled("k", 60) is False
    assert sls.should_log_throttled("other", 60) is True  # chaves independentes
    now[0] = 161.0
    assert sls.should_log_throttled("k", 60) is True


def test_heartbeat_writes_at_most_once_per_interval(db):
    for _ in range(6):  # job roda a cada 10s
        hb_mod.heartbeat(db)
    db.commit()
    assert db.query(SystemLog).filter(SystemLog.message == "heartbeat").count() == 1


def test_fipe_idle_batches_are_throttled_but_work_is_always_logged(db, monkeypatch):
    results = iter([{"claimed": 0}, {"claimed": 0}, {"claimed": 3}, {"claimed": 0}, {"claimed": 2}])
    monkeypatch.setattr(fipe_lookup_job, "process_pending_fipe_lookups", lambda _db: next(results))
    session_scope = MagicMock()
    session_scope.return_value.__enter__.return_value = db
    monkeypatch.setattr(fipe_lookup_job, "session_scope", session_scope)
    monkeypatch.setattr(fipe_lookup_job, "is_shutdown_requested", lambda: False)
    for _ in range(5):
        fipe_lookup_job.job_process_fipe_lookups()
    db.commit()
    rows = db.query(SystemLog).filter(SystemLog.component == "fipe_lookup").all()
    # 1o ocioso + 2 com trabalho (os ociosos seguintes caem no throttle de 10 min)
    assert sorted(r.payload["claimed"] for r in rows) == [0, 2, 3]
