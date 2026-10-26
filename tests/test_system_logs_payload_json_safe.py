import json
import uuid
from datetime import datetime, timezone

from app.core.settings import settings
from app.services import system_logs_service


class _FakeDb:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)


def test_log_payload_with_uuid_is_json_serializable(monkeypatch):
    monkeypatch.setattr(settings, "log_stdout", False)
    job_id = uuid.uuid4()
    db = _FakeDb()

    system_logs_service.log(
        db,
        "error",
        "browser_queue_worker",
        "job_hard_timeout",
        {"job_id": job_id, "source": "facebook_marketplace", "dur_ms": 780000},
    )

    payload = db.rows[0].payload
    json.dumps(payload)  # o driver faz json.dumps puro no JSONB; nao pode levantar
    assert payload["job_id"] == str(job_id)
    assert payload["dur_ms"] == 780000


def test_log_payload_sanitizes_nested_non_json_types(monkeypatch):
    monkeypatch.setattr(settings, "log_stdout", False)
    uid = uuid.uuid4()
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    db = _FakeDb()

    system_logs_service.log(db, "warn", "comp", "msg", {"a": [uid, {"b": now}], "c": None, "d": 1.5})

    payload = db.rows[0].payload
    json.dumps(payload)
    assert payload["a"][0] == str(uid)
    assert payload["a"][1]["b"] == str(now)
    assert payload["c"] is None and payload["d"] == 1.5


def test_log_payload_none_stays_none(monkeypatch):
    monkeypatch.setattr(settings, "log_stdout", False)
    db = _FakeDb()

    system_logs_service.log(db, "info", "comp", "msg")

    assert db.rows[0].payload is None
