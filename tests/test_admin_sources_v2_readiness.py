from __future__ import annotations

import asyncio

from app.bot import admin_handlers_sources


class _Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text):
        self.sent.append(text)


class _Update:
    def __init__(self):
        self.message = _Message()


def test_admin_sources_v2_readiness_command_renders_ordered_report(monkeypatch):
    rows = [
        {
            "source": "olx",
            "v2_readiness_status": "candidate",
            "enabled": True,
            "has_v1": True,
            "has_v2": True,
            "supports_dual": True,
            "configured_impl": "v1",
            "last_runtime_impl": "v1",
            "expected_runtime_impl": "v1",
            "impl_alignment": "ok",
            "operational_role": "primary",
            "fetch_mode": "http",
            "success_count": 24,
            "blocked_count": 0,
            "error_count": 0,
            "skip_count": 0,
            "ok_rate": 100,
            "avg_duration_ms": 900,
            "last_success_at": None,
            "last_found": 385,
            "last_matched": 40,
            "last_thumb_rate": 1.0,
            "recommendation": "run_dual_report_then_consider_canary",
        },
        {
            "source": "mercadolivre",
            "v2_readiness_status": "done",
            "enabled": True,
            "has_v1": True,
            "has_v2": True,
            "supports_dual": True,
            "configured_impl": "v2",
            "last_runtime_impl": "v2",
            "expected_runtime_impl": "v2",
            "impl_alignment": "ok",
            "operational_role": "primary",
            "fetch_mode": "http",
            "success_count": 24,
            "blocked_count": 0,
            "error_count": 0,
            "skip_count": 0,
            "ok_rate": 100,
            "avg_duration_ms": 800,
            "last_success_at": None,
            "last_found": 100,
            "last_matched": 10,
            "last_thumb_rate": 1.0,
            "recommendation": "done_monitor_24h",
        },
    ]

    monkeypatch.setattr(admin_handlers_sources, "ensure_source_configs", lambda db: 0)
    monkeypatch.setattr(admin_handlers_sources, "build_source_v2_readiness_report", lambda db: rows)

    update = _Update()
    asyncio.run(
        admin_handlers_sources.admin_sources_dispatch(
            update,
            ["v2", "readiness"],
            admin_sources_fn=None,
            admin_sources_show_fn=None,
            admin_sources_set_simple_fn=None,
            admin_sources_reset_fn=None,
        )
    )

    out = "\n".join(update.message.sent)
    assert "🧭 V1→V2 Readiness" in out
    assert "[1] olx — candidate" in out
    assert "[2] mercadolivre — done" in out
    assert "ação: run_dual_report_then_consider_canary" in out
