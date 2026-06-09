from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.services.source_configs_service import ensure_source_configs
from app.services.source_v2_readiness import (
    build_source_v2_readiness_report,
    classify_v2_readiness,
    render_source_v2_readiness_telegram,
)


def _row(**overrides):
    base = {
        "source": "olx",
        "enabled": True,
        "operational_role": "primary",
        "has_v1": True,
        "has_v2": True,
        "supports_dual": True,
        "configured_impl": "v1",
        "last_runtime_impl": "v1",
        "expected_runtime_impl": "v1",
        "impl_alignment": "ok",
        "default_enabled": True,
        "configured_enabled": True,
        "fetch_mode": "http",
        "success_count": 24,
        "blocked_count": 0,
        "error_count": 0,
        "skip_count": 0,
        "ok_rate": 100,
        "avg_duration_ms": 1000,
        "last_found": 100,
        "last_matched": 10,
        "has_recent_v2_runtime": False,
    }
    base.update(overrides)
    return base


def test_configured_v2_runtime_v2_alignment_ok_is_done():
    status, recommendation = classify_v2_readiness(
        _row(source="mercadolivre", configured_impl="v2", last_runtime_impl="v2", expected_runtime_impl="v2")
    )

    assert status == "done"
    assert recommendation == "done_monitor_24h"


def test_primary_stable_v1_with_v2_and_dual_is_candidate():
    status, recommendation = classify_v2_readiness(_row(source="olx"))

    assert status == "candidate"
    assert recommendation == "run_dual_report_then_consider_canary"


def test_browser_dual_source_without_recent_v2_runtime_needs_dual_run():
    status, recommendation = classify_v2_readiness(_row(source="chavesnamao", fetch_mode="browser"))

    assert status == "needs_dual_run"
    assert recommendation == "dual_run_first_due_browser_cost"


def test_disabled_source_is_disabled():
    status, recommendation = classify_v2_readiness(_row(source="olx", enabled=False, configured_enabled=False))

    assert status == "disabled"
    assert recommendation == "enable_only_if_product_strategy_requires_then_dual_run"


def test_source_without_v2_is_no_v2():
    status, recommendation = classify_v2_readiness(
        _row(source="facebook_marketplace", has_v2=False, supports_dual=False, fetch_mode="browser")
    )

    assert status == "no_v2"
    assert recommendation == "no_v2_registered_do_not_migrate"


def test_deprioritized_source_is_deprioritized():
    status, recommendation = classify_v2_readiness(
        _row(
            source="webmotors",
            operational_role="deprioritized",
            enabled=False,
            configured_enabled=False,
            fetch_mode="browser",
        )
    )

    assert status == "deprioritized"
    assert recommendation == "keep_disabled_until_strategy_changes"


def test_blocked_or_error_source_is_blocked_or_unstable():
    status, recommendation = classify_v2_readiness(_row(source="olx", success_count=20, blocked_count=1, ok_rate=95))

    assert status == "blocked_or_unstable"
    assert recommendation == "stabilize_source_before_v2_migration"


def test_telegram_renderer_contains_fields_and_order():
    rows = [
        {**_row(source="olx"), "v2_readiness_status": "candidate", "recommendation": "run_dual_report_then_consider_canary"},
        {
            **_row(source="mercadolivre", configured_impl="v2", last_runtime_impl="v2"),
            "v2_readiness_status": "done",
            "recommendation": "done_monitor_24h",
        },
    ]

    out = render_source_v2_readiness_telegram(rows)

    assert "🧭 V1→V2 Readiness" in out
    assert "[1] olx — candidate" in out
    assert "has_v2✅ dual✅ role=primary" in out
    assert "24h ok=24 blk=0 err=0" in out
    assert "ação: run_dual_report_then_consider_canary" in out
    assert out.index("olx — candidate") < out.index("mercadolivre — done")


def test_build_report_covers_all_registered_sources_and_uses_recent_runs(db):
    now = datetime.now(timezone.utc)
    ensure_source_configs(db)
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "mercadolivre").one()
    cfg.extra = {**(cfg.extra or {}), "impl": "v2"}
    db.add(
        SourceRun(
            source="mercadolivre",
            kind="scheduler",
            status="success",
            created_at=now - timedelta(minutes=5),
            duration_ms=700,
            items_found=12,
            items_matched=3,
            payload={"runtime_impl": "v2", "thumb_rate": 1.0},
        )
    )
    db.commit()

    rows = build_source_v2_readiness_report(db, now=now)
    by_source = {row["source"]: row for row in rows}

    assert {"mercadolivre", "olx", "webmotors", "facebook_marketplace"}.issubset(by_source)
    assert by_source["mercadolivre"]["v2_readiness_status"] == "done"
    assert by_source["mercadolivre"]["last_found"] == 12
    assert by_source["mercadolivre"]["last_matched"] == 3


def test_v2_zero_result_suspect_is_not_done_and_recommends_rollback_for_mercadolivre():
    status, recommendation = classify_v2_readiness(
        _row(
            source="mercadolivre",
            configured_impl="v2",
            last_runtime_impl="v2",
            expected_runtime_impl="v2",
            suspicious_zero_results=True,
            zero_result_reason="found_zero_with_recent_positive_baseline",
            zero_result_baseline_found=185,
        )
    )

    assert status != "done"
    assert status == "blocked_or_unstable"
    assert recommendation == "rollback_to_canary_then_validate"


def test_v2_without_zero_result_suspect_is_done():
    status, recommendation = classify_v2_readiness(
        _row(
            source="mercadolivre",
            configured_impl="v2",
            last_runtime_impl="v2",
            expected_runtime_impl="v2",
            suspicious_zero_results=False,
        )
    )

    assert status == "done"
    assert recommendation == "done_monitor_24h"


def test_mercadolivre_canary_effective_alignment_is_ok_in_readiness(db, monkeypatch):
    now = datetime.now(timezone.utc)
    ensure_source_configs(db)
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "mercadolivre").one()
    cfg.extra = {**(cfg.extra or {}), "impl": "v1", "mercadolivre_v2_canary_enabled": True}
    cfg.browser_fallback_enabled = True
    monkeypatch.setattr("app.services.source_v2_readiness.settings.enable_playwright", True)
    db.add(
        SourceRun(
            source="mercadolivre",
            kind="scheduler",
            status="success",
            created_at=now - timedelta(minutes=5),
            duration_ms=700,
            items_found=12,
            items_matched=3,
            payload={"runtime_impl": "v2_canary"},
        )
    )
    db.commit()

    rows = build_source_v2_readiness_report(db, now=now)
    mercadolivre = {row["source"]: row for row in rows}["mercadolivre"]

    assert mercadolivre["configured_impl"] == "v1"
    assert mercadolivre["last_runtime_impl"] == "v2_canary"
    assert mercadolivre["expected_runtime_impl"] == "v2_canary"
    assert mercadolivre["impl_alignment"] == "ok"


def test_renderer_shows_zero_result_suspect_baseline_and_reason():
    row = {
        **_row(
            source="mercadolivre",
            configured_impl="v2",
            last_runtime_impl="v2",
            suspicious_zero_results=True,
            zero_result_reason="found_zero_with_recent_positive_baseline",
            zero_result_baseline_found=185,
        ),
        "v2_readiness_status": "blocked_or_unstable",
        "recommendation": "rollback_to_canary_then_validate",
    }

    out = render_source_v2_readiness_telegram([row])

    assert "zero_result⚠️ baseline=185" in out
    assert "zero_result_suspect=True" in out
    assert "zero_result_baseline_found=185" in out
    assert "zero_result_reason=found_zero_with_recent_positive_baseline" in out


def test_non_mercadolivre_zero_result_suspect_uses_investigation_recommendation():
    status, recommendation = classify_v2_readiness(
        _row(
            source="olx",
            configured_impl="v2",
            last_runtime_impl="v2",
            suspicious_zero_results=True,
            zero_result_baseline_found=100,
        )
    )

    assert status == "blocked_or_unstable"
    assert recommendation == "investigate_zero_result_suspect"


def test_build_report_extracts_zero_result_suspect_from_run_summary(db):
    now = datetime.now(timezone.utc)
    ensure_source_configs(db)
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "mercadolivre").one()
    cfg.extra = {**(cfg.extra or {}), "impl": "v2"}
    db.add(
        SourceRun(
            source="mercadolivre",
            kind="scheduler",
            status="success",
            created_at=now - timedelta(minutes=5),
            duration_ms=700,
            items_found=0,
            items_matched=0,
            payload={
                "runtime_impl": "v2",
                "run_summary": {
                    "suspicious_zero_results": True,
                    "zero_result_reason": "found_zero_with_recent_positive_baseline",
                    "zero_result_baseline_found": 185,
                    "zero_result_runtime_impl": "v2",
                },
            },
        )
    )
    db.commit()

    rows = build_source_v2_readiness_report(db, now=now)
    mercadolivre = {row["source"]: row for row in rows}["mercadolivre"]

    assert mercadolivre["suspicious_zero_results"] is True
    assert mercadolivre["zero_result_baseline_found"] == 185
    assert mercadolivre["zero_result_reason"] == "found_zero_with_recent_positive_baseline"
    assert mercadolivre["zero_result_runtime_impl"] == "v2"
    assert mercadolivre["v2_readiness_status"] == "blocked_or_unstable"
    assert mercadolivre["recommendation"] == "rollback_to_canary_then_validate"
