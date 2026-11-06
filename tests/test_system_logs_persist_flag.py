import ast
from pathlib import Path

from app.core.settings import settings
from app.services import system_logs_service

JOBS_PATH = Path(__file__).resolve().parents[1] / "app" / "scheduler" / "jobs.py"
PIPELINE_MESSAGES = {"pipeline_summary", "pipeline_summary_many"}


class _FakeDb:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)


def test_log_with_persist_false_does_not_add_row_but_mirrors_stdout(monkeypatch, capsys):
    monkeypatch.setattr(settings, "log_stdout", True)
    monkeypatch.setattr(settings, "log_stdout_min_level", "warning")
    monkeypatch.setattr(settings, "log_stdout_always_messages", "pipeline_summary")
    db = _FakeDb()

    system_logs_service.log(
        db,
        "info",
        "scraper_olx",
        "pipeline_summary",
        {"found": 3},
        source="olx",
        event_type="pipeline_summary",
        tags=["ok"],
        persist=False,
    )

    assert db.rows == []
    out = capsys.readouterr().out
    assert "scraper_olx pipeline_summary" in out and '"found": 3' in out


def test_log_with_persist_false_skips_fingerprint_computation(monkeypatch):
    monkeypatch.setattr(settings, "log_stdout", False)

    def _boom(**_kwargs):
        raise AssertionError("compute_fingerprint nao deveria ser chamado com persist=False")

    monkeypatch.setattr(system_logs_service, "compute_fingerprint", _boom)
    db = _FakeDb()

    system_logs_service.log(db, "info", "scheduler", "pipeline_summary", {"x": 1}, event_type="pipeline_summary", persist=False)

    assert db.rows == []


def test_log_default_persist_still_adds_one_row(monkeypatch, capsys):
    monkeypatch.setattr(settings, "log_stdout", False)
    db = _FakeDb()

    system_logs_service.log(db, "info", "scheduler", "heartbeat", {"ok": True})

    assert len(db.rows) == 1
    assert db.rows[0].message == "heartbeat"


def test_all_pipeline_summary_log_calls_in_jobs_pass_persist_false():
    tree = ast.parse(JOBS_PATH.read_text(encoding="utf-8"))

    checked = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "log"):
            continue
        if len(node.args) < 4:
            continue
        msg = node.args[3]
        if not (isinstance(msg, ast.Constant) and msg.value in PIPELINE_MESSAGES):
            continue
        checked.append(node.lineno)
        kw = {k.arg: k.value for k in node.keywords}
        assert "persist" in kw, f"log(...pipeline_summary) sem persist= na linha {node.lineno}"
        assert isinstance(kw["persist"], ast.Constant) and kw["persist"].value is False, (
            f"persist deve ser False na linha {node.lineno}"
        )

    assert len(checked) == 4, f"esperava 4 chamadas pipeline_summary[_many] em jobs.py, achei {len(checked)}"
