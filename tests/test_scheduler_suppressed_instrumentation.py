from app.scheduler.run import _log_suppressed_exception


def test_scheduler_suppressed_exception_logs_context(monkeypatch):
    captured = {}

    class _DB:
        def commit(self):
            captured["committed"] = True

    class _Ctx:
        def __enter__(self):
            return _DB()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.scheduler.run.SessionLocal", lambda: _Ctx())

    def _fake_log(db, level, component, message, payload):
        captured.update({
            "level": level,
            "component": component,
            "message": message,
            "payload": payload,
        })

    monkeypatch.setattr("app.scheduler.run.log", _fake_log)

    _log_suppressed_exception(
        stage="bootstrap.test",
        exc=RuntimeError("boom"),
        impact="worker_not_registered",
        fallback="scheduler_continues",
        worker="boot",
    )

    assert captured["level"] == "warn"
    assert captured["component"] == "boot"
    assert captured["message"] == "suppressed_exception"
    assert captured["payload"]["stage"] == "bootstrap.test"
    assert captured["payload"]["exc_type"] == "RuntimeError"
    assert captured["payload"]["fallback"] == "scheduler_continues"
