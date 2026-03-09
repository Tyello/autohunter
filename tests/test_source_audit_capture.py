from __future__ import annotations

from types import SimpleNamespace

from app.services.source_audit_capture_service import SourceAuditCaptureService


def test_capture_decision_trigger_and_skip(tmp_path):
    svc = SourceAuditCaptureService(root=tmp_path)
    on = svc.decide(found=0, missing_critical=["price"])
    off = svc.decide(found=3, missing_critical=[])
    assert on.should_capture is True
    assert "found_zero_suspect" in on.reasons
    assert off.should_capture is False


def test_capture_persists_payload_and_metadata(tmp_path):
    svc = SourceAuditCaptureService(root=tmp_path)
    p = svc.capture_artifact(
        source="olx",
        kind="listing",
        url="https://example.com/list?token=abc123",
        source_listing_id="123",
        reason="parse_error",
        pipeline_stage="post_scrape",
        payload="<html>contato foo@bar.com +55 11 91234-5678</html>",
    )
    assert p.exists()
    meta = p.with_suffix('.meta.json')
    assert meta.exists()
    txt = p.read_text(encoding="utf-8")
    assert "[redacted-email]" in txt
    assert "[redacted-phone]" in txt


def test_runtime_sample_capture_for_multiple_sources(tmp_path):
    svc = SourceAuditCaptureService(root=tmp_path)
    ctx = SimpleNamespace(extra={})

    svc.register_runtime_fetch_sample(
        ctx=ctx,
        source="olx",
        kind="listing",
        url="https://olx.com",
        payload="<html>olx</html>",
    )
    svc.register_runtime_fetch_sample(
        ctx=ctx,
        source="mobiauto",
        kind="detail",
        url="https://mobiauto.com/item/1",
        payload={"ok": True},
        content_type="application/json",
    )

    out = svc.capture_from_runtime_samples(
        ctx=ctx,
        source="mobiauto",
        reasons=["debug_manual"],
        pipeline_stage="post_ingest",
        source_listing_id="X1",
    )
    assert out
    assert all(p.exists() for p in out)
