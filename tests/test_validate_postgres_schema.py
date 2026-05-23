from scripts.validate_postgres_schema import (
    CheckResult,
    classify_database_url,
    evaluate_required_columns,
    has_sent_partial_condition,
    run_validation,
    summarize_results,
)


def test_rejects_sqlite_url() -> None:
    level, _ = classify_database_url("sqlite:///tmp/test.db")
    assert level == "FAIL"


def test_accepts_postgres_urls() -> None:
    assert classify_database_url("postgresql://user:pass@localhost/db")[0] == "OK"
    assert classify_database_url("postgresql+psycopg://user:pass@localhost/db")[0] == "OK"


def test_rejects_malformed_database_url() -> None:
    level, message = classify_database_url("not a valid database url")
    assert level == "FAIL"
    assert "inválida ou malformada" in message


def test_detects_valid_partial_index_condition() -> None:
    index_sql = "CREATE INDEX ix_notifications_user_sent_today ON notifications (user_id, sent_at) WHERE status = 'sent'"
    assert has_sent_partial_condition(index_sql)


def test_rejects_index_without_sent_partial_condition() -> None:
    index_sql = "CREATE INDEX ix_notifications_user_sent_today ON notifications (user_id, status, sent_at)"
    assert not has_sent_partial_condition(index_sql)


def test_fails_on_missing_critical_columns() -> None:
    ok, missing = evaluate_required_columns(["id", "doors"])
    assert not ok
    assert missing == ["body_type", "cross_source_fingerprint"]


def test_exit_code_follows_fail_presence() -> None:
    _, ok_exit = summarize_results([CheckResult("OK", "ok"), CheckResult("WARNING", "warn")])
    _, fail_exit = summarize_results([CheckResult("OK", "ok"), CheckResult("FAIL", "fail")])
    assert ok_exit == 0
    assert fail_exit == 1


def test_run_validation_prints_fail_for_sqlite_url(capsys) -> None:
    _, exit_code = run_validation("sqlite:///tmp/test.db")
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in output
    assert "SQLite" in output


def test_run_validation_prints_fail_for_malformed_url(capsys) -> None:
    _, exit_code = run_validation("not a valid database url")
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in output
    assert "inválida ou malformada" in output
