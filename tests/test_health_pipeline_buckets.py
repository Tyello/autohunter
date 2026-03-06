from app.health.collector import HealthCollector
from app.health.models import RunStatus


def test_health_collector_counts_counters_and_buckets():
    h = HealthCollector(source_name="olx")

    h.inc("found", 10)
    h.inc("inserted", 4)
    h.inc("matched", 6)

    h.inc("queued", 2)
    h.count("queued", 2)

    h.inc("already_notified", 3)
    h.count("already_notified", 3)

    h.inc("filtered_out", 1)
    h.count("filtered_year", 1)

    h.inc("skipped", 2)
    h.count("missing_price", 1)
    h.count("duplicate", 1)

    h.inc("errors", 1)
    h.count("parse_error", 1)

    summary = h.finalize(RunStatus.OK)

    assert summary.found == 10
    assert summary.inserted == 4
    assert summary.matched == 6
    assert summary.queued == 2
    assert summary.already_notified == 3
    assert summary.filtered_out == 1
    assert summary.skipped == 2
    assert summary.errors == 1
    assert summary.reason_buckets["queued"] == 2
    assert summary.reason_buckets["already_notified"] == 3
    assert summary.reason_buckets["filtered_year"] == 1
    assert summary.reason_buckets["missing_price"] == 1
    assert summary.reason_buckets["duplicate"] == 1
    assert summary.reason_buckets["parse_error"] == 1
