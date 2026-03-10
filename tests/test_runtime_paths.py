from __future__ import annotations


from app.services.source_audit_capture_service import SourceAuditCaptureService
from app.services.storage_state_cookies import storage_state_path


def test_storage_state_path_uses_configured_runtime_dir(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "state" / "playwright"
    monkeypatch.setattr(
        "app.services.storage_state_cookies.playwright_storage_dir",
        lambda: runtime_dir,
    )

    out = storage_state_path(source="olx", proxy_server=None)
    assert out.parent == runtime_dir
    assert "/workspace/autohunter" not in str(out)


def test_source_audit_artifacts_outside_repo(tmp_path):
    svc = SourceAuditCaptureService(root=tmp_path / "cache" / "artifacts")
    out = svc.capture_artifact(
        source="olx",
        kind="listing",
        url="https://example.com/car",
        external_id="123",
        reason="debug",
        pipeline_stage="test",
        payload="<html>ok</html>",
    )

    assert out.exists()
    assert out.is_file()
    assert out.as_posix().startswith((tmp_path / "cache" / "artifacts").as_posix())
    assert "/workspace/autohunter" not in out.as_posix()
