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


def _is_named_call(call, name):
    return isinstance(call.func, ast.Name) and call.func.id == name


def _stmt_call(stmt):
    """Call de um statement `Expr(Call)`; None para qualquer outro statement."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        return stmt.value
    return None


def _emit_event_type(call):
    if not _is_named_call(call, "emit_event"):
        return None
    for kw in call.keywords:
        if kw.arg == "event_type" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


def _statement_lists(tree):
    """Todas as listas de statements (corpo de if/try/for/with/def...) do modulo."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
                yield stmts


def test_every_pipeline_summary_log_call_has_paired_emit_event_in_same_block():
    # REQ-007 (metade positiva): persist=False tira so o system_logs; a telemetria estruturada
    # (emit_event) tem de continuar no MESMO bloco. Parear por funcao nao basta: o caminho
    # incremental (skip) e o principal vivem na mesma funcao e um emit cobriria o outro.
    tree = ast.parse(JOBS_PATH.read_text(encoding="utf-8"))

    checked = 0
    for stmts in _statement_lists(tree):
        for stmt in stmts:
            call = _stmt_call(stmt)
            if call is None or not _is_named_call(call, "log") or len(call.args) < 4:
                continue
            msg = call.args[3]
            if not (isinstance(msg, ast.Constant) and msg.value in PIPELINE_MESSAGES):
                continue
            checked += 1
            paired = any(
                _emit_event_type(c) == msg.value
                for c in (_stmt_call(other) for other in stmts)
                if c is not None
            )
            assert paired, (
                f"log pipeline_summary (mensagem {msg.value!r}) na linha {call.lineno} sem "
                f"emit_event(event_type={msg.value!r}) no mesmo bloco"
            )

    assert checked == 4, f"esperava 4 chamadas log pipeline_summary[_many] em jobs.py, achei {checked}"
