from __future__ import annotations

from app.services.source_execution_helpers import build_run_payload, compute_field_coverage


def test_compute_field_coverage_counts_present_fields_per_listing():
    listings = [
        {"year": 2020, "mileage_km": 50000, "price": 80000},
        {"year": None, "mileage_km": 60000, "price": 90000},
        {"year": None, "mileage_km": None, "price": 70000},
    ]
    coverage = compute_field_coverage(listings)

    assert coverage["year"] == {"present": 1, "rate": 1 / 3}
    assert coverage["mileage_km"] == {"present": 2, "rate": 2 / 3}
    assert coverage["price"] == {"present": 3, "rate": 1.0}


def test_compute_field_coverage_empty_listings_returns_zero_rates():
    coverage = compute_field_coverage([])
    assert coverage["year"] == {"present": 0, "rate": 0.0}


def test_build_run_payload_includes_field_coverage_when_provided():
    payload = build_run_payload(
        run_summary={},
        run_reason="scheduler",
        hybrid_browser_used=False,
        hybrid_blocked=False,
        hybrid_blocked_status=None,
        field_coverage={"year": {"present": 1, "rate": 0.5}},
    )
    assert payload["field_coverage"] == {"year": {"present": 1, "rate": 0.5}}


def test_build_run_payload_omits_field_coverage_when_not_provided():
    payload = build_run_payload(
        run_summary={},
        run_reason="scheduler",
        hybrid_browser_used=False,
        hybrid_blocked=False,
        hybrid_blocked_status=None,
    )
    assert "field_coverage" not in payload
