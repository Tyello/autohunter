from __future__ import annotations

import json

from app.scheduler import fipe_update_job


def test_job_crawls_when_no_static_input_path(monkeypatch):
    monkeypatch.setattr(fipe_update_job.settings, "fipe_monthly_update_input_path", None)

    fake_rows = [{"marca": "Toyota", "modelo": "Corolla", "ano": 2020, "combustivel": "Gasolina",
                  "codigo_fipe": "001004-9", "valor": "R$ 90.000,00", "tipo_veiculo": "car"}]
    monkeypatch.setattr(
        fipe_update_job,
        "crawl_latest_fipe_prices",
        lambda *, client_factory, limit_brands=None, concurrency=None, on_progress=None: fake_rows,
    )

    captured = {}

    def fake_run(db, *, input_path=None, **kwargs):
        captured["input_path"] = input_path
        captured["content"] = json.loads(input_path.read_text(encoding="utf-8"))
        return None

    monkeypatch.setattr(fipe_update_job, "run_audited_monthly_fipe_update", fake_run)
    monkeypatch.setattr(fipe_update_job, "SessionLocal", lambda: _FakeSessionCtx())

    fipe_update_job.job_monthly_fipe_update()

    assert captured["content"] == fake_rows
    assert not captured["input_path"].exists()


def test_job_uses_static_input_path_when_configured(monkeypatch):
    monkeypatch.setattr(fipe_update_job.settings, "fipe_monthly_update_input_path", "/tmp/fixed.json")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("crawler should not be called when static input path is configured")

    monkeypatch.setattr(fipe_update_job, "crawl_latest_fipe_prices", fail_if_called)

    captured = {}

    def fake_run(db, **kwargs):
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr(fipe_update_job, "run_audited_monthly_fipe_update", fake_run)
    monkeypatch.setattr(fipe_update_job, "SessionLocal", lambda: _FakeSessionCtx())

    fipe_update_job.job_monthly_fipe_update()

    assert "input_path" not in captured["kwargs"]


def test_job_passes_concurrency_setting_to_crawler(monkeypatch):
    monkeypatch.setattr(fipe_update_job.settings, "fipe_monthly_update_input_path", None)
    monkeypatch.setattr(fipe_update_job.settings, "fipe_crawler_concurrency", 3)

    captured = {}

    def fake_crawl(*, client_factory, limit_brands=None, concurrency=None, on_progress=None):
        captured["concurrency"] = concurrency
        captured["client"] = client_factory()
        return []

    monkeypatch.setattr(fipe_update_job, "crawl_latest_fipe_prices", fake_crawl)

    def fake_run(db, *, input_path=None, **kwargs):
        return None

    monkeypatch.setattr(fipe_update_job, "run_audited_monthly_fipe_update", fake_run)
    monkeypatch.setattr(fipe_update_job, "SessionLocal", lambda: _FakeSessionCtx())

    fipe_update_job.job_monthly_fipe_update()

    assert captured["concurrency"] == 3
    assert isinstance(captured["client"], fipe_update_job.FipeApiClient)


def test_temp_file_cleaned_up_on_success_and_failure(monkeypatch):
    monkeypatch.setattr(fipe_update_job.settings, "fipe_monthly_update_input_path", None)
    monkeypatch.setattr(
        fipe_update_job,
        "crawl_latest_fipe_prices",
        lambda *, client_factory, limit_brands=None, concurrency=None, on_progress=None: [],
    )

    paths_seen = []

    def fake_run_ok(db, *, input_path=None, **kwargs):
        paths_seen.append(input_path)
        return None

    monkeypatch.setattr(fipe_update_job, "run_audited_monthly_fipe_update", fake_run_ok)
    monkeypatch.setattr(fipe_update_job, "SessionLocal", lambda: _FakeSessionCtx())

    fipe_update_job.job_monthly_fipe_update()
    assert not paths_seen[0].exists()

    def fake_run_fail(db, *, input_path=None, **kwargs):
        paths_seen.append(input_path)
        raise RuntimeError("boom")

    monkeypatch.setattr(fipe_update_job, "run_audited_monthly_fipe_update", fake_run_fail)

    fipe_update_job.job_monthly_fipe_update()  # must not raise
    assert not paths_seen[1].exists()


class _FakeSessionCtx:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False
