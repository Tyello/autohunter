from __future__ import annotations

from app.services.source_audit_report_service import build_matrix, write_reports


def test_build_matrix_and_reports(tmp_path):
    samples = [
        {
            "source": "olx",
            "field": "price",
            "present_in_listing": True,
            "captured_before_merge": True,
            "present_after_merge": True,
            "persisted": True,
            "used_in_message": True,
        },
        {
            "source": "olx",
            "field": "year",
            "present_in_listing": False,
            "present_in_detail": True,
            "captured_before_merge": True,
            "present_after_merge": False,
            "persisted": False,
            "quality_flag_false_positive": True,
        },
    ]
    matrix = build_matrix(samples)
    assert matrix["olx"]["price"].status() == "ok"
    assert matrix["olx"]["year"].quality_flag_false_positive is True

    out = write_reports(samples, tmp_path)
    assert out["json"].exists()
    assert out["md"].exists()
    assert out["csv"].exists()
