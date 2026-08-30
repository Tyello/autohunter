from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from telegram import Update

from app.bot.admin.helpers import (
    chunk_lines as _chunk_lines,
    fmt_dt as _fmt_dt,
    reply_chunked as _reply_chunked,
    short as _short,
)
from app.bot.text_sanitize import sanitize_for_telegram
from app.core.settings import settings
from app.db.session import SessionLocal
from app.health.explain import explain_queued_zero, top_buckets
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.models.system_log import SystemLog
from app.scrapers.webmotors_ops import extract_webmotors_diag_from_payload
from app.services.auction_source_config_service import ensure_auction_source_configs
from app.services.scrape_jobs_service import scrape_jobs_runtime_snapshot
from app.services.source_configs_service import ensure_source_configs, get_source_config, set_source_field, reset_source_config
from app.services.source_impl_alignment import evaluate_source_impl_alignment
from app.services.source_operational_policy import classify_source_operational_role, source_operational_severity
from app.services.source_staleness_service import evaluate_source_staleness, heartbeat_is_stale
from app.services.source_v2_readiness import build_source_v2_readiness_report, render_source_v2_readiness_telegram
from app.sources.auctions.registry import resolve_auction_source_alias
from app.sources.flags import read_source_impl_flags
from app.sources.registry import list_sources


_SENSITIVE_EXTRA_KEY_PARTS = ("token", "secret", "password", "key", "cookie", "session")
_MERCADOLIVRE = "mercadolivre"


def _extract_runtime_impl(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    runtime_impl = payload.get("runtime_impl")
    if runtime_impl:
        return str(runtime_impl)
    run_summary = payload.get("run_summary")
    if isinstance(run_summary, dict) and run_summary.get("runtime_impl"):
        return str(run_summary.get("runtime_impl"))
    return None


def _build_canary_recent_runs_report(db, source: str, *, window_hours: int = 24) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=max(1, int(window_hours or 24)))
    rows = (
        db.query(SourceRun)
        .filter(SourceRun.source == source)
        .filter(SourceRun.created_at >= since)
        .order_by(SourceRun.created_at.desc())
        .all()
    )

    canary_runs: list[tuple[object, str]] = []
    for row in rows:
        runtime_impl = _extract_runtime_impl(getattr(row, "payload", None))
        if runtime_impl == "v2_canary":
            canary_runs.append((row, runtime_impl))

    success = 0
    blocked = 0
    error = 0
    found_positive_success = False
    max_success_found = 0
    last_runtime_impl = "v2_canary" if canary_runs else "-"
    last_success_at = "-"
    last_success_found = 0
    last_success_inserted = 0
    last_success_matched = 0
    last_success_queued = 0
    last_success_duration_ms = 0
    last_blocked_at = "-"
    last_error_at = "-"

    for row, _runtime_impl in canary_runs:
        status = str(getattr(row, "status", "") or "").strip().lower()
        created_at = getattr(row, "created_at", None)
        created_iso = created_at.isoformat() if created_at else "-"
        if status == "success":
            success += 1
            row_found = int(getattr(row, "items_found", 0) or 0)
            max_success_found = max(max_success_found, row_found)
            if row_found > 0:
                found_positive_success = True
            if last_success_at == "-":
                last_success_at = created_iso
                last_success_found = row_found
                last_success_inserted = int(getattr(row, "items_ingested", 0) or 0)
                last_success_matched = int(getattr(row, "items_matched", 0) or 0)
                last_success_queued = int(getattr(row, "notifications_queued", 0) or 0)
                last_success_duration_ms = int(getattr(row, "duration_ms", 0) or 0)
        elif status in ("blocked", "skipped"):
            blocked += 1
            if last_blocked_at == "-":
                last_blocked_at = created_iso
        elif status == "error":
            error += 1
            if last_error_at == "-":
                last_error_at = created_iso

    return {
        "window": f"{int(window_hours)}h",
        "v2_canary_success": success,
        "v2_canary_blocked": blocked,
        "v2_canary_error": error,
        "v2_canary_found_positive_success": found_positive_success,
        "v2_canary_max_success_found": max_success_found,
        "last_runtime_impl": last_runtime_impl,
        "last_success_at": last_success_at,
        "last_success_found": last_success_found,
        "last_success_inserted": last_success_inserted,
        "last_success_matched": last_success_matched,
        "last_success_queued": last_success_queued,
        "last_success_duration_ms": last_success_duration_ms,
        "last_blocked_at": last_blocked_at,
        "last_error_at": last_error_at,
    }


def _canary_effective_for_cfg(cfg) -> tuple[bool, str | None, bool]:
    impl_flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)
    playwright_enabled = bool(getattr(settings, "enable_playwright", False))
    if impl_flags.impl == "v2":
        return False, "not_needed_configured_impl_v2", playwright_enabled
    if not bool(impl_flags.canary_v2_enabled):
        return False, "canary_flag_disabled", playwright_enabled
    if not playwright_enabled:
        return False, "playwright_disabled", playwright_enabled
    if not bool(cfg.browser_fallback_enabled):
        return False, "browser_fallback_disabled", playwright_enabled
    return True, None, playwright_enabled


def _sanitize_source_extra(extra: dict | None) -> str:
    if not isinstance(extra, dict):
        return "-"
    out: dict[str, object] = {}
    for k in sorted(extra.keys(), key=lambda x: str(x)):
        key = str(k)
        v = extra.get(k)
        low = key.lower()
        if any(part in low for part in _SENSITIVE_EXTRA_KEY_PARTS):
            out[key] = "***"
        else:
            out[key] = v
    rendered = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    return rendered if len(rendered) <= 320 else rendered[:317] + "..."


async def admin_sources_dispatch(update, raw_args, *, admin_sources_fn, admin_sources_show_fn, admin_sources_set_simple_fn, admin_sources_reset_fn):
    args = [a.strip() for a in (raw_args or []) if a.strip()]

    if not args:
        await admin_sources_fn(update, verbose=False)
        return

    if any(a.lower() in ("v", "-v", "verbose", "full", "details") for a in args):
        await admin_sources_fn(update, verbose=True)
        return

    cmd = args[0].lower()

    if cmd in ("list",):
        await admin_sources_fn(update, verbose=False)
        return
    if cmd in ("migration",):
        await admin_sources_v2_readiness(update)
        return
    if cmd == "v2":
        if len(args) == 1 or (len(args) >= 2 and args[1].lower() in ("readiness", "migration", "report")):
            await admin_sources_v2_readiness(update)
            return
    if cmd in ("show", "get") and len(args) >= 2:
        await admin_sources_show_fn(update, args[1])
        return
    if cmd in ("enable", "on") and len(args) >= 2:
        await admin_sources_set_simple_fn(update, args[1], "is_enabled", "true")
        return
    if cmd in ("disable", "off") and len(args) >= 2:
        await admin_sources_set_simple_fn(update, args[1], "is_enabled", "false")
        return
    if cmd in ("sched", "schedule") and len(args) >= 3:
        await admin_sources_set_simple_fn(update, args[1], "sched_minutes", args[2])
        return
    if cmd in ("cool", "cooldown") and len(args) >= 3:
        await admin_sources_set_simple_fn(update, args[1], "cooldown_minutes", args[2])
        return
    if cmd in ("rate", "ratelimit", "rate_limit") and len(args) >= 3:
        await admin_sources_set_simple_fn(update, args[1], "rate_limit_seconds", args[2])
        return
    if cmd == "proxy" and len(args) >= 3:
        v = " ".join(args[2:])
        if v.strip().lower() in ("off", "none", "null", "-"):
            v = ""
        await admin_sources_set_simple_fn(update, args[1], "proxy_server", v)
        return
    if cmd in ("fallback", "browser_fallback") and len(args) >= 3:
        await admin_sources_set_simple_fn(update, args[1], "browser_fallback_enabled", args[2])
        return
    if cmd == "canary" and len(args) >= 3:
        action = args[2].lower() if len(args) >= 3 else "status"
        if action in ("show",):
            action = "status"
        if action in ("enable",):
            action = "on"
        if action in ("disable",):
            action = "off"
        await admin_sources_canary(update, args[1], action)
        return
    if cmd in ("promote", "promotion") and len(args) >= 2:
        target_impl = args[2].lower() if len(args) >= 3 else "v2"
        await admin_sources_promote(update, args[1], target_impl)
        return
    if cmd in ("rollback", "demote") and len(args) >= 2:
        target_impl = args[2].lower() if len(args) >= 3 else "v1"
        await admin_sources_rollback(update, args[1], target_impl)
        return
    if cmd in ("force", "force_browser") and len(args) >= 3:
        await admin_sources_set_simple_fn(update, args[1], "force_browser", args[2])
        return
    if cmd == "set" and len(args) >= 4:
        await admin_sources_set_simple_fn(update, args[1], args[2], " ".join(args[3:]))
        return
    if cmd == "reset" and len(args) >= 2:
        await admin_sources_reset_fn(update, args[1])
        return

    await update.message.reply_text(
        "Uso:\n"
        "/admin sources\n"
        "/admin sources verbose\n"
        "/admin sources show <source>\n"
        "/admin sources enable <source>\n"
        "/admin sources disable <source>\n"
        "/admin sources sched <source> <minutes>\n"
        "/admin sources cool <source> <minutes>\n"
        "/admin sources rate <source> <seconds>\n"
        "/admin sources proxy <source> <url|off>\n"
        "/admin sources fallback <source> on|off\n"
        "/admin sources v2 readiness\n"
        "/admin sources canary mercadolivre status|report|on|off\n"
        "/admin sources promote mercadolivre [v2]\n"
        "/admin sources rollback mercadolivre v1\n"
        "/admin sources force <source> on|off\n"
        "/admin sources set <source> <field> <value>\n"
        "/admin sources reset <source>"
    )


async def admin_sources_v2_readiness(update):
    """Render a read-only V1→V2 migration readiness report for all sources."""
    with SessionLocal() as db:
        ensure_source_configs(db)
        rows = build_source_v2_readiness_report(db)

    await update.message.reply_text(sanitize_for_telegram(render_source_v2_readiness_telegram(rows)))


async def admin_sources_show(update, source: str):
    with SessionLocal() as db:
        ensure_source_configs(db)
        cfg = get_source_config(db, source)
        if not cfg:
            await update.message.reply_text("Source não encontrada.")
            return
        st = db.query(SourceState).filter(SourceState.source == cfg.source).one_or_none()
        impl_flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)
        canary_effective, canary_reason, _ = _canary_effective_for_cfg(cfg)
        lines = [
            f"🧰 Admin — Source: {cfg.source}",
            f"enabled={bool(cfg.is_enabled)}",
            f"sched_minutes={int(cfg.sched_minutes or 0)}",
            f"cooldown_minutes={int(cfg.cooldown_minutes or 0)}",
            f"rate_limit_seconds={int(cfg.rate_limit_seconds or 0)}",
            f"proxy_server={cfg.proxy_server or '-'}",
            f"browser_fallback_enabled={bool(cfg.browser_fallback_enabled)}",
            f"force_browser={bool(cfg.force_browser)}",
            f"configured_impl={impl_flags.impl}",
            f"mercadolivre_v2_canary_enabled={bool(impl_flags.canary_v2_enabled)}",
            f"canary_effective={bool(canary_effective)}",
            f"extra={_sanitize_source_extra(cfg.extra)}",
        ]
        last_runtime_impl = None
        if st is not None and isinstance(st.last_payload, dict):
            run_summary = st.last_payload.get("run_summary")
            if isinstance(run_summary, dict):
                last_runtime_impl = run_summary.get("runtime_impl")
            if not last_runtime_impl:
                last_runtime_impl = st.last_payload.get("runtime_impl")
        alignment = evaluate_source_impl_alignment(
            source=cfg.source,
            configured_impl=impl_flags.impl,
            last_runtime_impl=str(last_runtime_impl) if last_runtime_impl else None,
            canary_enabled=bool(impl_flags.canary_v2_enabled),
            canary_effective=bool(canary_effective),
        )
        lines.extend([
            f"last_runtime_impl={alignment['last_runtime_impl']}",
            f"expected_runtime_impl={alignment['expected_runtime_impl']}",
            f"impl_alignment={alignment['impl_alignment']}",
            f"impl_alignment_reason={alignment['impl_alignment_reason']}",
        ])
        if not canary_effective:
            lines.append(f"canary_reason={canary_reason}")
        role = None
        if isinstance(cfg.extra, dict):
            role = str(cfg.extra.get("operational_role") or "").strip().lower()
        blocked_provider = None
        if st is not None and isinstance(st.last_payload, dict):
            blocked_provider = str(st.last_payload.get("blocked_provider") or st.last_payload.get("provider") or "").strip().lower()
        if role == "deprioritized" and str(getattr(st, "last_status", "") or "").lower() == "blocked":
            if blocked_provider == "perimeterx":
                lines.append("leitura=source despriorizada por bloqueio PerimeterX/fingerprint; execução manual disponível, sem falha crítica global.")
            else:
                lines.append("leitura=source despriorizada; último status blocked; execução manual disponível, sem falha crítica global.")
        await update.message.reply_text(sanitize_for_telegram("\n".join(lines)))


async def admin_sources_set_simple(update, source: str, field: str, value: str):
    try:
        with SessionLocal() as db:
            ensure_source_configs(db)
            cfg = set_source_field(db, source, field, value)
            snap = {
                "source": cfg.source,
                "enabled": bool(cfg.is_enabled),
                "sched": int(cfg.sched_minutes or 0),
                "cool": int(cfg.cooldown_minutes or 0),
                "rate": int(cfg.rate_limit_seconds or 0),
                "proxy": cfg.proxy_server or "-",
                "fallback": bool(cfg.browser_fallback_enabled),
                "force": bool(cfg.force_browser),
            }
            impl_flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)
            db.commit()

        extra_note = ""
        if str(field).strip().lower() == "extra":
            extra_note = (
                f"\nextra=updated impl={impl_flags.impl} "
                f"mercadolivre_v2_canary_enabled={bool(impl_flags.canary_v2_enabled)}"
            )
        await update.message.reply_text(
            sanitize_for_telegram(
                f"✅ Atualizado {snap['source']}: {field}={value}\n"
                f"enabled={snap['enabled']} sched={snap['sched']}m cool={snap['cool']}m "
                f"rate={snap['rate']}s proxy={snap['proxy']} fallback={snap['fallback']} force={snap['force']}"
                f"{extra_note}"
            )
        )
    except Exception as e:
        await update.message.reply_text(sanitize_for_telegram(f"Erro: {e}"))


async def admin_sources_canary(update, source: str, action: str):
    src = str(source or "").strip().lower()
    if src != _MERCADOLIVRE:
        await update.message.reply_text("Canary V2 manual está disponível apenas para mercadolivre nesta etapa.")
        return
    if action not in ("status", "report", "on", "off"):
        await update.message.reply_text("Use: /admin sources canary mercadolivre status|report|on|off")
        return
    with SessionLocal() as db:
        ensure_source_configs(db)
        cfg = get_source_config(db, src)
        if not cfg:
            await update.message.reply_text("Source não encontrada.")
            return
        if action in ("status", "report"):
            impl_flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)
            canary_effective, canary_reason, playwright_enabled = _canary_effective_for_cfg(cfg)
            report = _build_canary_recent_runs_report(db, src, window_hours=24)
            recommendation = "run_manual_validation"
            if not canary_effective:
                recommendation = "canary_not_effective"
            elif int(report["v2_canary_blocked"]) > 0 or int(report["v2_canary_error"]) > 0:
                recommendation = "keep_canary_or_rollback_review"
            elif int(report["v2_canary_success"]) >= 3:
                recommendation = "continue_soak_candidate"
            elif int(report["v2_canary_success"]) >= 1:
                recommendation = "continue_soak"
            lines = [
                "Mercado Livre — V2 Canary",
                f"source={cfg.source}",
                f"impl={impl_flags.impl}",
                f"mercadolivre_v2_canary_enabled={bool(impl_flags.canary_v2_enabled)}",
                f"playwright_enabled={bool(playwright_enabled)}",
                f"browser_fallback_enabled={bool(cfg.browser_fallback_enabled)}",
                f"canary_effective={bool(canary_effective)}",
                "",
                "Canary recent runs:",
                f"window={report['window']}",
                f"v2_canary_success={report['v2_canary_success']}",
                f"v2_canary_blocked={report['v2_canary_blocked']}",
                f"v2_canary_error={report['v2_canary_error']}",
                f"last_runtime_impl={report['last_runtime_impl']}",
                f"last_success_at={report['last_success_at']}",
                f"last_success_found={report['last_success_found']}",
                f"last_success_inserted={report['last_success_inserted']}",
                f"last_success_matched={report['last_success_matched']}",
                f"last_success_queued={report['last_success_queued']}",
                f"last_success_duration_ms={report['last_success_duration_ms']}",
                f"last_blocked_at={report['last_blocked_at']}",
                f"last_error_at={report['last_error_at']}",
            ]
            if not canary_effective:
                lines.append(f"reason={canary_reason}")
            lines.append(f"recommendation={recommendation}")
            await update.message.reply_text(sanitize_for_telegram("\n".join(lines)))
            return

        patch = {"mercadolivre_v2_canary_enabled": action == "on"}
        if action == "on":
            patch["impl"] = "v1"
        cfg = set_source_field(db, src, "extra", json.dumps(patch, ensure_ascii=False))
        db.commit()
        impl_flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)
        canary_effective, canary_reason, _ = _canary_effective_for_cfg(cfg)
        if action == "off":
            await update.message.reply_text(
                "✅ Mercado Livre V2 canary desativado.\n"
                f"Runtime volta ao impl configurado: impl={impl_flags.impl}."
            )
            return
        lines = [
            "✅ Mercado Livre V2 canary ativado (manual).",
            f"source={cfg.source}",
            f"impl={impl_flags.impl}",
            f"mercadolivre_v2_canary_enabled={bool(impl_flags.canary_v2_enabled)}",
            f"browser_fallback_enabled={bool(cfg.browser_fallback_enabled)}",
            f"canary_effective={bool(canary_effective)}",
        ]
        if not canary_effective and canary_reason == "browser_fallback_disabled":
            lines.extend(
                [
                    "Canary configurado, mas não efetivo porque browser_fallback_enabled=False.",
                    "Ative com:",
                    "/admin sources fallback mercadolivre on",
                ]
            )
        await update.message.reply_text(sanitize_for_telegram("\n".join(lines)))


def _promotion_blocked_message(reason: str) -> str:
    return sanitize_for_telegram(
        "⚠️ Promoção bloqueada.\n"
        f"Motivo: {reason}.\n"
        "Diagnóstico:\n"
        " /admin sources canary mercadolivre report"
    )


def _validate_mercadolivre_v2_promotion(cfg, report: dict[str, object]) -> tuple[bool, str, bool]:
    impl_flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)
    playwright_enabled = bool(getattr(settings, "enable_playwright", False))
    if not playwright_enabled:
        return False, "Playwright desabilitado", playwright_enabled
    if not bool(cfg.browser_fallback_enabled):
        return False, "browser_fallback_enabled=False", playwright_enabled
    if impl_flags.impl != "v2" and not (
        bool(impl_flags.canary_v2_enabled) or report.get("last_runtime_impl") == "v2_canary"
    ):
        return False, "canary V2 não está efetivo nem há runtime_impl=v2_canary recente", playwright_enabled
    if int(report.get("v2_canary_success") or 0) < 3:
        return False, "soak insuficiente: success < 3 nas últimas 24h", playwright_enabled
    if int(report.get("v2_canary_blocked") or 0) > 0:
        return False, "blocked recente no canary", playwright_enabled
    if int(report.get("v2_canary_error") or 0) > 0:
        return False, "error recente no canary", playwright_enabled
    if not bool(report.get("v2_canary_found_positive_success")):
        return False, "canary sem sucesso recente com found > 0", playwright_enabled
    return True, "ok", playwright_enabled


async def admin_sources_promote(update, source: str, target_impl: str = "v2"):
    src = str(source or "").strip().lower()
    impl = str(target_impl or "v2").strip().lower()
    if src != _MERCADOLIVRE:
        await update.message.reply_text("⚠️ Promoção bloqueada. Apenas mercadolivre é suportado nesta etapa.")
        return
    if impl != "v2":
        await update.message.reply_text("Use: /admin sources promote mercadolivre v2")
        return

    with SessionLocal() as db:
        ensure_source_configs(db)
        cfg = get_source_config(db, src)
        if not cfg:
            await update.message.reply_text("Source não encontrada.")
            return
        report = _build_canary_recent_runs_report(db, src, window_hours=24)
        ok, reason, _playwright_enabled = _validate_mercadolivre_v2_promotion(cfg, report)
        if not ok:
            await update.message.reply_text(_promotion_blocked_message(reason))
            return

        patch = {"impl": "v2", "mercadolivre_v2_canary_enabled": False}
        cfg = set_source_field(db, src, "extra", json.dumps(patch, ensure_ascii=False))
        db.commit()
        impl_flags = read_source_impl_flags(cfg.extra if isinstance(cfg.extra, dict) else None)

    lines = [
        "✅ Mercado Livre promovido para V2 configurado.",
        f"configured_impl={impl_flags.impl}",
        f"mercadolivre_v2_canary_enabled={bool(impl_flags.canary_v2_enabled)}",
        f"browser_fallback_enabled={bool(cfg.browser_fallback_enabled)}",
        f"last_runtime_impl={report['last_runtime_impl']}",
        (
            "soak: "
            f"success={report['v2_canary_success']} "
            f"blocked={report['v2_canary_blocked']} "
            f"error={report['v2_canary_error']} "
            f"found_recent={report['v2_canary_max_success_found']}"
        ),
        "",
        "Rollback:",
        " /admin sources rollback mercadolivre v1",
    ]
    await update.message.reply_text(sanitize_for_telegram("\n".join(lines)))


async def admin_sources_rollback(update, source: str, target_impl: str = "v1"):
    src = str(source or "").strip().lower()
    impl = str(target_impl or "v1").strip().lower()
    if src != _MERCADOLIVRE:
        await update.message.reply_text("⚠️ Rollback bloqueado. Apenas mercadolivre é suportado nesta etapa.")
        return
    if impl != "v1":
        await update.message.reply_text("Use: /admin sources rollback mercadolivre v1")
        return

    with SessionLocal() as db:
        ensure_source_configs(db)
        cfg = get_source_config(db, src)
        if not cfg:
            await update.message.reply_text("Source não encontrada.")
            return
        patch = {"impl": "v1", "mercadolivre_v2_canary_enabled": False}
        cfg = set_source_field(db, src, "extra", json.dumps(patch, ensure_ascii=False))
        db.commit()

    await update.message.reply_text(
        sanitize_for_telegram(
            "✅ Mercado Livre rollback para V1 configurado.\n"
            "Próximo passo: /admin sources show mercadolivre"
        )
    )


async def admin_sources_reset(update, source: str):
    try:
        with SessionLocal() as db:
            ensure_source_configs(db)
            cfg = reset_source_config(db, source)
            snap = {
                "source": cfg.source,
                "enabled": bool(cfg.is_enabled),
                "sched": int(cfg.sched_minutes or 0),
                "cool": int(cfg.cooldown_minutes or 0),
                "rate": int(cfg.rate_limit_seconds or 0),
                "proxy": cfg.proxy_server or "-",
                "fallback": bool(cfg.browser_fallback_enabled),
                "force": bool(cfg.force_browser),
            }
            db.commit()

        await update.message.reply_text(
            sanitize_for_telegram(
                f"✅ Resetado {snap['source']} para defaults\n"
                f"enabled={snap['enabled']} sched={snap['sched']}m cool={snap['cool']}m "
                f"rate={snap['rate']}s proxy={snap['proxy']} fallback={snap['fallback']} force={snap['force']}"
            )
        )
    except Exception as e:
        await update.message.reply_text(sanitize_for_telegram(f"Erro: {e}"))


@dataclass
class _Agg24h:
    total: int = 0
    success: int = 0
    blocked: int = 0
    error: int = 0
    skipped: int = 0
    avg_duration_ms: Optional[int] = None
    avg_found: Optional[int] = None

    @property
    def effective_runs(self) -> int:
        return int(self.success or 0) + int(self.error or 0) + int(self.blocked or 0)

def _fmt_diag(diag: Optional[dict]) -> str:
    """Compact diagnostics formatter for /admin sources verbose."""
    if not diag or not isinstance(diag, dict):
        return "-"

    def _i(key: str) -> int:
        try:
            return int(diag.get(key) or 0)
        except Exception:
            return 0

    def _b(key: str) -> bool:
        return bool(diag.get(key) or False)

    http_req = _i("http_req")
    http_err = _i("http_err")
    br_req = _i("br_req")
    br_err = _i("br_err")
    parsed = _i("items_parsed")
    final = _i("items_final")
    dedup = _i("items_deduped")
    drops = _i("items_dropped_non_dict") + _i("items_dropped_no_url") + _i("items_dropped_no_external_id")
    nonveh = _i("items_filtered_non_vehicle")
    noprice = _i("items_missing_price")

    fb = _b("browser_fallback")
    forced = _b("browser_forced")
    used = _b("browser_used")
    blocked = _b("blocked")

    parts: list[str] = []

    if http_req or http_err:
        parts.append(f"http={http_req} err={http_err}")

    hs = diag.get("http_statuses")
    if isinstance(hs, dict) and hs:
        try:
            top = sorted(((str(k), int(v)) for k, v in hs.items()), key=lambda x: x[1], reverse=True)[:3]
            parts.append("http_status=" + ",".join([f"{k}x{v}" for k, v in top]))
        except Exception:
            pass

    if br_req or br_err or used:
        extra = []
        if fb:
            extra.append("fb")
        if forced:
            extra.append("force")
        parts.append(f"br={br_req} err={br_err}" + (" (" + ",".join(extra) + ")" if extra else ""))

    if parsed or final or dedup or drops:
        parts.append(f"items parsed={parsed} final={final} dedup={dedup} drop={drops}")

    if nonveh:
        parts.append(f"nonveh={nonveh}")
    if noprice:
        parts.append(f"noprice={noprice}")
    if blocked:
        parts.append("BLOCKED")

    return " | ".join(parts) if parts else "-"

def _mins_left(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if not dt:
        return None
    if dt <= now:
        return 0
    return int((dt - now).total_seconds() // 60)

def _classify_error(source: str, err: str | None, http_status: Optional[int]) -> tuple[str, str, str]:
    """
    Retorna (kind, short_reason, action).
    Kinds: BUG | NET | BLOCKED | DATA | ERR
    """
    e = (err or "").strip()
    e_l = e.lower()

    # BUG: concorrência / Playwright / greenlet / asyncio
    if ("cannot switch to a different thread" in e_l) or ("greenlet" in e_l):
        return ("BUG", "thread/greenlet (Playwright Sync)", "usar PlaywrightPool thread-safe / evitar uso cross-thread")
    if "playwright sync api inside the asyncio loop" in e_l:
        return ("BUG", "Playwright Sync dentro do asyncio", "rodar fetch browser em thread (to_thread) ou usar Playwright Async API")

    # BLOCKED: anti-bot
    if http_status in (403, 429):
        return ("BLOCKED", f"HTTP {http_status}", "browser warmup/cookies/fingerprint; ajustar backoff")
    # Algumas fontes retornam challenge/captcha com HTTP 200 (ex.: Webmotors/PerimeterX)
    if http_status == 200 and any(k in e_l for k in ("no_json_capture", "bot_challenge", "perimeterx", "px", "captcha", "cloudflare", "access denied")):
        why = "HTTP 200 (anti-bot/challenge)"
        if "no_json_capture" in e_l:
            why = "HTTP 200 (no_json_capture)"
        if "perimeterx" in e_l or "px" in e_l:
            why = "HTTP 200 (PerimeterX)"
        return ("BLOCKED", why, "browser warmup + cookies; validar captura do XHR; aumentar backoff de blocked; trocar proxy se persistir")
    if any(k in e_l for k in ("cloudflare", "captcha", "attention required")):
        return ("BLOCKED", "Cloudflare/captcha", "browser warmup + cookies; marcar como blocked no pipeline")

    # NET: rede/timeout/DNS/SSL
    if any(k in e_l for k in ("playwright worker timed out", "net::err_timed_out", "timed out", "timeout", "connection", "dns", "name or service not known", "temporary failure", "ssl", "tls")):
        return ("NET", "rede/timeout/dns/ssl", "verificar conectividade/proxy/DNS; aumentar timeout e retries (browser/HTTP)")

    # DATA: endpoint/parser
    if http_status == 404 or ("404" in e_l and "not found" in e_l):
        return ("DATA", "HTTP 404 (rota mudou)", "atualizar URL/endpoint do scraper")
    if any(k in e_l for k in ("selector", "parse", "jsondecode", "__next_data__", "__preloaded_state__")):
        return ("DATA", "HTML/JSON mudou", "ajustar parser/selectors e normalização")

    return ("ERR", _short(e, 160), "abrir stacktrace e classificar (BUG/NET/BLOCKED/DATA)")

def _payload_as_dict(payload: Any) -> Optional[dict]:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        s = payload.strip()
        if not s:
            return None
        try:
            v = json.loads(s)
            return v if isinstance(v, dict) else None
        except Exception:
            return None
    return None

def _render_run_summary_lines(run_summary: Optional[dict]) -> list[str]:
    if not isinstance(run_summary, dict):
        return []

    lines: list[str] = []
    status = run_summary.get("status")
    found = int(run_summary.get("found") or 0)
    inserted = int(run_summary.get("inserted") or 0)
    matched = int(run_summary.get("matched") or 0)
    queued = int(run_summary.get("queued") or 0)
    suffix = " ⚠️ zero_result_suspect" if run_summary.get("suspicious_zero_results") is True else ""
    lines.append(f"health status={status} found={found} inserted={inserted} matched={matched} queued={queued}{suffix}")
    if run_summary.get("suspicious_zero_results") is True:
        baseline = run_summary.get("zero_result_baseline_found")
        reason = run_summary.get("zero_result_reason") or "found_zero_with_recent_positive_baseline"
        lines.append(f"zero_result_suspect: reason={reason} baseline_found={baseline}")

    buckets = run_summary.get("reason_buckets") or {}
    top = top_buckets(buckets, k=3)
    if top:
        lines.append("top: " + " ".join(f"{k}={v}" for k, v in top))

    if matched > 0 and queued == 0:
        lines.append(f"↳ {explain_queued_zero(SimpleNamespace(reason_buckets=buckets))}")

    last_error = run_summary.get("last_error") if isinstance(run_summary.get("last_error"), dict) else None
    if last_error:
        lines.append(
            "last_error: "
            f"category={last_error.get('category')} "
            f"http={last_error.get('http_status')} "
            f"retryable={last_error.get('retryable')}"
        )

    for n in run_summary.get("notes") or []:
        s = str(n or "").strip()
        if s.startswith("wm_diag "):
            lines.append(s)

    return lines

def _render_webmotors_blocked_diag_lines(payload: Any) -> list[str]:
    data = extract_webmotors_diag_from_payload(payload if isinstance(payload, dict) else {})
    if not isinstance(data, dict):
        return []

    lines: list[str] = []
    bucket = str(data.get("bucket") or "-")
    fetch_path = str(data.get("fetch_path") or "-")
    attempt = str(data.get("attempt") or "-")
    lines.append(f"wm_diag: {bucket} / {fetch_path} / attempt={attempt}")

    blocked_reason = str(data.get("blocked_reason") or data.get("reason") or "-")
    evidence = str(data.get("evidence") or "")
    provider = "-"
    for sig in (data.get("detected_signals") or []):
        ss = str(sig or "")
        if ss.startswith("provider="):
            provider = ss.split("=", 1)[1] or "-"
            break
    if provider == "-":
        joined = f"{blocked_reason} {evidence}".lower()
        m = re.search(r"provider=([a-z0-9_-]+)", joined)
        if m:
            provider = m.group(1)
    lines.append(f"reason: {blocked_reason} provider={provider}")

    title = _short(str(data.get("page_title") or ""), 120)
    if title != "-":
        lines.append(f"title: {title}")

    final_url = _short(str(data.get("final_url") or ""), 140)
    if final_url != "-":
        lines.append(f"url: {final_url}")

    signals_blob = " ".join(str(x or "") for x in (data.get("detected_signals") or []))
    reason_blob = f"{blocked_reason} {str(data.get('reason') or '')}"
    low_blob = f"{title.lower()} {signals_blob.lower()} {reason_blob.lower()} {evidence.lower()}"
    if bucket.upper() == "BLOCKED" and ("perimeterx" in low_blob or "bot_challenge_fingerprint" in low_blob) and (
        "access to this page has been denied" in low_blob or "pressione e segure" in low_blob or "bot_challenge_fingerprint" in low_blob
    ):
        lines.append("leitura: bloqueio anti-bot/fingerprint; Webmotors pode exigir sessão assistida/storage state válido ou permanecer despriorizada.")

    return lines

def _extract_runtime_impl_from_payload(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    runtime_impl = payload.get("runtime_impl")
    if runtime_impl:
        return str(runtime_impl)
    run_summary = payload.get("run_summary")
    if isinstance(run_summary, dict) and run_summary.get("runtime_impl"):
        return str(run_summary.get("runtime_impl"))
    return None

def _source_canary_effective(source: str, cfg, impl_flags) -> bool:
    return (
        str(source or "").strip().lower() == "mercadolivre"
        and bool(getattr(impl_flags, "canary_v2_enabled", False))
        and bool(getattr(settings, "enable_playwright", False))
        and bool(getattr(cfg, "browser_fallback_enabled", False))
    )

async def _admin_sources(update: Update, verbose: bool = False):
    """
    Visão compacta + categorizada (BUG/NET/BLOCKED/DATA) para operar rápido.

    Use:
      /admin sources
      /admin sources verbose
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    plugins = list_sources()
    if not plugins:
        await update.message.reply_text("Nenhuma fonte registrada.")
        return

    with SessionLocal() as db:
        ensure_source_configs(db)
        cfgs = {c.source: c for c in db.query(SourceConfig).all()}
        states = {s.source: s for s in db.query(SourceState).all()}

        # last run per source (qualquer status)
        last_runs: dict[str, Optional[SourceRun]] = {}
        # last "effective" run per source (ignora skipped, ajuda a achar a causa real)
        last_effective: dict[str, Optional[SourceRun]] = {}

        for src in {p.name for p in plugins}:
            last_runs[src] = (
                db.query(SourceRun)
                .filter(SourceRun.source == src)
                .order_by(SourceRun.created_at.desc())
                .first()
            )
            last_effective[src] = (
                db.query(SourceRun)
                .filter(SourceRun.source == src)
                .filter(SourceRun.status != "skipped")
                .order_by(SourceRun.created_at.desc())
                .first()
            )

        # 24h aggregates per source (contagem + média ponderada)
        aggs: Dict[str, _Agg24h] = {}
        for src in {p.name for p in plugins}:
            rows = (
                db.query(
                    SourceRun.status,
                    func.count(SourceRun.id),
                    func.avg(SourceRun.duration_ms),
                    func.avg(SourceRun.items_found),
                )
                .filter(SourceRun.source == src)
                .filter(SourceRun.created_at >= since)
                .group_by(SourceRun.status)
                .all()
            )

            a = _Agg24h()
            sum_dur = 0.0
            sum_found = 0.0
            sum_cnt_dur = 0
            sum_cnt_found = 0

            for status, cnt, avg_ms, avg_f in rows:
                cnt = int(cnt or 0)
                a.total += cnt
                if status == "success":
                    a.success += cnt
                elif status == "blocked":
                    a.blocked += cnt
                elif status == "error":
                    a.error += cnt
                elif status == "skipped":
                    a.skipped += cnt

                # Averages are execution-shape signals. Operational skips keep
                # last_run_at observable, but must not dilute effective scrape
                # duration/found metrics.
                if status != "skipped" and avg_ms is not None:
                    sum_dur += float(avg_ms) * cnt
                    sum_cnt_dur += cnt
                if status != "skipped" and avg_f is not None:
                    sum_found += float(avg_f) * cnt
                    sum_cnt_found += cnt

            a.avg_duration_ms = int(sum_dur / sum_cnt_dur) if sum_cnt_dur else None
            a.avg_found = int(sum_found / sum_cnt_found) if sum_cnt_found else None
            aggs[src] = a

        last_scheduler_heartbeat = (
            db.query(SystemLog)
            .filter(SystemLog.component == "scheduler")
            .filter(SystemLog.message == "heartbeat")
            .order_by(SystemLog.created_at.desc())
            .first()
        )
        jobs_snapshot = scrape_jobs_runtime_snapshot(db, now=now)

    lines: List[str] = []
    stale_sources = 0
    critical_enabled_sources = 0
    critical_blocked = 0
    noncritical_blocked = 0
    lines.append("🧰 Admin — Sources")
    lines.append(f"Agora (UTC): {_fmt_dt(now)}")
    lines.append(f"Janela: 24h desde {_fmt_dt(since)}")
    hb_at = getattr(last_scheduler_heartbeat, "created_at", None)
    hb_stale = heartbeat_is_stale(now, hb_at, stale_after_minutes=int(getattr(settings, "scheduler_heartbeat_stale_minutes", 15) or 15))
    lines.append(f"Scheduler heartbeat: {_fmt_dt(hb_at)}")
    if hb_stale:
        lines.append("⚠️ scheduler heartbeat stale (orquestrador pode estar parado)")
    lines.append("")

    for i, p in enumerate(plugins, start=1):
        cfg = cfgs.get(p.name)
        enabled = bool(cfg.is_enabled) if cfg is not None else bool(getattr(p, 'default_enabled', True))
        sched_m = int(cfg.sched_minutes or 0) if cfg is not None else int(getattr(p, 'default_sched_minutes', 0) or 0)
        cooldown_m = int(cfg.cooldown_minutes or 0) if cfg is not None else int(getattr(p, 'default_cooldown_minutes', 0) or 0)
        rate_s = int(cfg.rate_limit_seconds or 0) if cfg is not None else int(getattr(p, 'default_rate_limit_seconds', 0) or 0)
        proxy = (cfg.proxy_server if cfg is not None else getattr(p, 'default_proxy_server', None))
        fb = bool(cfg.browser_fallback_enabled) if cfg is not None else bool(getattr(p, 'default_browser_fallback_enabled', False))
        force_b = bool(cfg.force_browser) if cfg is not None else bool(getattr(p, 'default_force_browser', False))
        implemented = p.scrape is not None
        cfg_extra = cfg.extra if (cfg is not None and isinstance(cfg.extra, dict)) else None
        impl_flags = read_source_impl_flags(cfg_extra)

        st = states.get(p.name)
        op_class = classify_source_operational_role(p, cfg=cfg, state=st)
        lr = last_runs.get(p.name)
        le = last_effective.get(p.name)
        a = aggs.get(p.name, _Agg24h())
        last_runtime_impl = None
        if lr is not None:
            last_runtime_impl = _extract_runtime_impl_from_payload(getattr(lr, "payload", None))
        if not last_runtime_impl and st is not None:
            last_runtime_impl = _extract_runtime_impl_from_payload(getattr(st, "last_payload", None))
        impl_alignment = evaluate_source_impl_alignment(
            source=p.name,
            configured_impl=impl_flags.impl,
            last_runtime_impl=last_runtime_impl,
            canary_enabled=bool(impl_flags.canary_v2_enabled),
            canary_effective=_source_canary_effective(p.name, cfg, impl_flags) if cfg is not None else False,
        )

        # estado de execução (enabled/backoff)
        if not enabled:
            state = "🚫 disabled"
        else:
            if st and st.next_allowed_at and st.next_allowed_at > now:
                mins = _mins_left(st.next_allowed_at, now)
                state = f"⏳ backoff {mins}m" if mins is not None else "⏳ backoff"
            else:
                state = "✅ ok"

        if enabled and implemented and op_class.include_in_critical_stale:
            critical_enabled_sources += 1

        flags: list[str] = []
        flags.append("impl✅" if implemented else "impl❌")
        if enabled and impl_alignment.get("impl_alignment") == "warning":
            flags.append("impl⚠️")
        if sched_m is not None:
            flags.append(f"sched={sched_m}m")
        if cooldown_m:
            flags.append(f"cool={cooldown_m}m")
        if verbose:
            flags.append(f"rate={rate_s}s")
            if proxy:
                flags.append("proxy=on")
            if fb:
                flags.append("fallback=on")
            if force_b:
                flags.append("force=on")
            flags.append(f"impl={impl_flags.impl}")
            if p.name == "mercadolivre":
                flags.append(f"v2_canary={'on' if impl_flags.canary_v2_enabled else 'off'}")

        # causa (usa last_effective se last=skipped)
        lr_cause = lr
        if lr and lr.status == "skipped" and le:
            lr_cause = le

        kind = "OK"
        why = "-"
        action = "—"
        emoji = "✅"
        stale_eval = None

        if not enabled:
            kind = "DISABLED"
            emoji = "🚫"
            why = "disabled via source_configs"
            action = "use: /admin sources enable <source>"
        else:
            last_run_at = None
            if st and st.last_run_at:
                last_run_at = st.last_run_at
            elif lr and lr.created_at:
                last_run_at = lr.created_at
            stale_eval = evaluate_source_staleness(
                now=now,
                last_run_at=last_run_at,
                sched_minutes=sched_m,
                factor=float(getattr(settings, "source_stale_factor", 2.0) or 2.0),
                min_global_minutes=int(getattr(settings, "source_stale_min_minutes", 180) or 180),
            )
            if stale_eval.stale and op_class.include_in_critical_stale:
                stale_sources += 1

            if lr_cause is None:
                kind = "ERR"
                emoji = "❔"
                why = "sem execuções registradas"
                action = "verificar scheduler/job"
            else:
                if lr_cause.status == "success":
                    cause_payload = _payload_as_dict(getattr(lr_cause, "payload", None)) or {}
                    if cause_payload.get("suspicious_zero_results") is True:
                        kind = "OK"
                        emoji = "⚠️"
                        why = "found=0 com baseline recente positivo"
                        if p.name == "mercadolivre":
                            action = "validar /admin sources canary mercadolivre report; se necessário /admin runall mercadolivre"
                        else:
                            action = f"validar /admin runall {p.name}"
                    else:
                        kind = "OK"
                        emoji = "✅"
                elif lr_cause.status == "blocked":
                    kind = "BLOCKED"
                    emoji = "🟠"
                    if source_operational_severity(op_class.role, enabled=enabled) == "critical":
                        critical_blocked += 1
                    else:
                        noncritical_blocked += 1
                    hs = lr_cause.http_status or 403
                    e_l = (lr_cause.error or "").lower()
                    if hs == 200 and ("no_json_capture" in e_l):
                        why = "HTTP 200 (no_json_capture)"
                        action = (
                            "browser warmup/cookies/fingerprint; verificar captura do XHR (/api/search/*); "
                            "aumentar backoff de blocked; trocar proxy se persistir"
                        )
                    elif hs == 200 and ("perimeterx" in e_l or "_px" in e_l or " px" in e_l):
                        why = "HTTP 200 (PerimeterX)"
                        action = (
                            "browser warmup + cookies; reduzir agressividade; proxy residencial/rotativo; "
                            "aumentar backoff de blocked"
                        )
                    elif hs == 200:
                        why = "HTTP 200 (anti-bot/challenge)"
                        action = "browser warmup/cookies/fingerprint; checar challenge; aumentar backoff; avaliar proxy"
                    else:
                        why = f"HTTP {hs}"
                        action = "browser warmup/cookies/fingerprint; ajustar backoff"
                elif lr_cause.status == "skipped":
                    kind = "SKIP"
                    emoji = "⏳"
                    why = "cooldown/backoff ativo"
                    action = "aguardar janela; reduzir duração do job"
                elif lr_cause.status == "error":
                    k, w, a2 = _classify_error(p.name, lr_cause.error, lr_cause.http_status)
                    kind = k
                    why = w
                    action = a2
                    emoji = {"BUG": "🔴", "NET": "🟣", "BLOCKED": "🟠", "DATA": "🟡", "ERR": "⚪"}.get(kind, "⚪")
                else:
                    kind = (lr_cause.status or "ERR").upper()
                    emoji = "⚪"
                    why = _short(lr_cause.error, 120)
                    action = "ver logs"

        if stale_eval is not None and stale_eval.stale:
            kind = "STALE"
            emoji = "🟤"
            state = f"🟤 stale {stale_eval.age_minutes}m" if stale_eval.age_minutes is not None else "🟤 stale"
            if stale_eval.age_minutes is None:
                why = f"sem last_run_at; threshold={stale_eval.threshold_minutes}m"
            else:
                why = (
                    f"sem run recente: age={stale_eval.age_minutes}m "
                    f"threshold={stale_eval.threshold_minutes}m overdue={stale_eval.overdue_minutes}m"
                )
            action = "verificar scheduler/orquestrador e fila global"

        effective_runs = a.effective_runs
        ok_pct = int(round((a.success / effective_runs) * 100)) if effective_runs else 0
        expected_24h = int((24 * 60) / sched_m) if sched_m and sched_m > 0 else None
        expected_part = ""
        if expected_24h:
            cov_pct = int(round((effective_runs / expected_24h) * 100)) if expected_24h else 0
            expected_part = f"/{expected_24h} ({cov_pct}%)"
        snap_lines = [
            f"24h efetivas: ok={a.success} err={a.error} blk={a.blocked} total={effective_runs}{expected_part} ok_rate={ok_pct}%",
            f"24h skips: {a.skipped}",
            f"eventos totais: {a.total}",
        ]
        if a.avg_duration_ms is not None:
            snap_lines[0] += f" avg={a.avg_duration_ms}ms"

        # last run compacto
        last_line = "last: -"
        if lr:
            dur = f"{lr.duration_ms}ms" if lr.duration_ms is not None else "-"
            found = f"{lr.items_found}" if lr.items_found is not None else "-"
            match = f"{lr.items_matched}" if lr.items_matched is not None else "-"
            last_line = f"last {lr.status} at={_fmt_dt(lr.created_at)} dur={dur} found={found} match={match}"
            if lr.http_status is not None:
                last_line += f" http={lr.http_status}"
            payload = lr.payload or {}
            if isinstance(payload, dict):
                runtime_impl = _extract_runtime_impl_from_payload(payload)
                if runtime_impl:
                    last_line += f" runtime_impl={runtime_impl}"
                if payload.get("hybrid_browser_used") is True:
                    last_line += " browser=hybrid"
                if payload.get("hybrid_blocked") is True:
                    hs = payload.get("hybrid_blocked_status")
                    last_line += f" blocked=1" + (f" blocked_http={hs}" if hs is not None else "")
                wm_diag = payload.get("webmotors_diag")
                if isinstance(wm_diag, dict):
                    last_line += (
                        f" wm={wm_diag.get('bucket')}"
                        f" path={wm_diag.get('fetch_path')}"
                        f" at={wm_diag.get('attempt')}"
                    )
                # Thumb telemetry (helps detect regressions in photo sending)
                tr = payload.get("thumb_rate")
                if tr is not None:
                    try:
                        pct = int(round(float(tr) * 100))
                        last_line += f" thumb={pct}%"
                    except Exception:
                        pass
                if payload.get("suspicious_zero_results") is True:
                    last_line += " ⚠️ zero_result_suspect"
                if lr.status == "skipped":
                    skip_reason = payload.get("reason") or payload.get("skip_reason") or payload.get("status_reason")
                    if skip_reason:
                        last_line += f" reason={_short(str(skip_reason), 80)}"
                for extra in _render_run_summary_lines(payload.get("run_summary")):
                    lines.append(f"   {extra}")

        role_note = ""
        if kind == "BLOCKED" and source_operational_severity(op_class.role, enabled=enabled) != "critical":
            role_note = f" | role={op_class.role} não crítico global"
        lines.append(f"[{i}] {p.name} — {state} | {emoji} {kind}{role_note} | " + " ".join(flags))
        if st:
            if st.consecutive_blocks:
                lines.append(f"   blocks seguidos: {st.consecutive_blocks}")
            if st.consecutive_failures:
                lines.append(f"   erros seguidos: {st.consecutive_failures}")

        lines.append(f"   {last_line}")
        if le is not None and lr is not None and getattr(le, "id", None) != getattr(lr, "id", None):
            if le.status == "success":
                lines.append(f"   last success at={_fmt_dt(le.created_at)}")
            else:
                effective_label = str(le.status or "effective")
                lines.append(f"   last effective {effective_label} at={_fmt_dt(le.created_at)}")
        for snap_line in snap_lines:
            lines.append(f"   {snap_line}")

        if verbose and lr_cause is not None and getattr(lr_cause, "payload", None):
            try:
                payload = _payload_as_dict(getattr(lr_cause, "payload", None))
                d = payload.get("diag") if payload else None
                if d:
                    lines.append(f"   diag: {_fmt_diag(d)}")
            except Exception:
                pass

        if enabled and impl_alignment.get("impl_alignment") == "warning":
            lines.append(
                f"   causa: configured_impl={impl_alignment['configured_impl']} mas runtime_impl={impl_alignment['last_runtime_impl']}"
            )
            if p.name == "mercadolivre":
                lines.append(f"   ação: validar /admin sources show {p.name}; se necessário rollback")
            else:
                lines.append(f"   ação: validar /admin sources show {p.name}; revisar configuração V1/V2")

        backoff_active = bool(enabled and st and st.next_allowed_at and st.next_allowed_at > now)
        if kind != "OK" or backoff_active or (why and why != "-"):
            lines.append(f"   causa: {why}")
            lines.append(f"   ação: {action}")
        if stale_eval is not None and stale_eval.stale and not op_class.include_in_critical_stale:
            lines.append(f"   note: role={op_class.role} (stale não crítico em /admin health)")

        if verbose and lr and lr.error:
            lines.append(f"   err_full: {_short(lr.error, 420)}")

        lines.append("")

    if critical_blocked or noncritical_blocked:
        lines.insert(4, f"Blocked 24h: crítico={critical_blocked} não_crítico={noncritical_blocked}")

    stale_ratio = (stale_sources / critical_enabled_sources) if critical_enabled_sources else 0.0
    stale_min_sources = int(getattr(settings, "scheduler_global_stale_min_sources", 3) or 3)
    stale_ratio_cut = float(getattr(settings, "scheduler_global_stale_ratio", 0.6) or 0.6)
    if stale_sources > 0:
        lines.insert(4, f"Sources críticas stale: {stale_sources}/{critical_enabled_sources} ({int(round(stale_ratio * 100))}%)")
    if stale_sources >= stale_min_sources and stale_ratio >= stale_ratio_cut:
        lines.insert(5, "🚨 indício global: várias sources stale simultaneamente (scheduler/orquestrador)")
        queued_jobs = int(jobs_snapshot.get("queued", 0) or 0)
        running_jobs = int(jobs_snapshot.get("running", 0) or 0)
        stale_running_jobs = int(jobs_snapshot.get("running_stale", 0) or 0)
        window_runs = int(sum((aggs.get(p.name, _Agg24h()).total for p in plugins)) or 0)
        if not hb_stale and window_runs == 0:
            lines.insert(6, "🚨 heartbeat recente, mas 0 source runs na janela (24h)")
            lines.insert(7, "🚨 provável falha no enqueue, workers ou persistência de source_runs/source_states")
        lines.insert(8, f"Fila scrape_jobs: queued={queued_jobs} running={running_jobs} stale_running={stale_running_jobs}")
        lines.insert(9, f"Último job criado: {_fmt_dt(jobs_snapshot.get('last_created_at'))}")
        lines.insert(10, f"Último job iniciado: {_fmt_dt(jobs_snapshot.get('last_started_at'))}")
        lines.insert(11, f"Último job finalizado: {_fmt_dt(jobs_snapshot.get('last_finished_at'))}")
        if queued_jobs > 0 and running_jobs == 0:
            lines.insert(12, "⚠️ workers aparentam inativos (há jobs pendentes sem consumo)")
        elif running_jobs > 0:
            lines.insert(12, "✅ workers aparentam ativos (há consumo em andamento)")
        if stale_running_jobs > 0:
            lines.insert(13, "⚠️ jobs running travados/orfãos detectados; aguarde requeue TTL ou rode /admin runall")

    text = "\n".join(lines)
    await _reply_chunked(update, text)

async def _admin_source_unified(update: Update, args: List[str]):
    if len(args) < 2:
        await update.message.reply_text("Use: /admin source <source> <enable|disable|user-enable|user-disable|categories>")
        return
    src = args[0].strip().lower()
    mapped = resolve_auction_source_alias(src) or src
    action = args[1].strip().lower()
    is_auction = bool(resolve_auction_source_alias(src))
    if action in {"enable", "disable"} and is_auction:
        with SessionLocal() as db:
            ensure_auction_source_configs(db)
            cfg = get_source_config(db, mapped)
            if not cfg:
                await update.message.reply_text("Source não encontrada.")
                return
            cfg.is_enabled = action == "enable"
            if action == "disable":
                cfg.user_eligible = False
            snap = {
                "source": cfg.source,
                "enabled": bool(cfg.is_enabled),
                "user_eligible": bool(cfg.user_eligible),
            }
            db.add(cfg)
            db.commit()
        await update.message.reply_text(f"✅ source={snap['source']} enabled={'sim' if snap['enabled'] else 'não'} user_eligible={'sim' if snap['user_eligible'] else 'não'}")
        return
    if action in {"enable", "disable"}:
        return await admin_sources_set_simple(update, mapped, "is_enabled", "true" if action == "enable" else "false")
    if action in {"user-enable", "user-disable"}:
        with SessionLocal() as db:
            if is_auction:
                ensure_auction_source_configs(db)
            else:
                ensure_source_configs(db)
            cfg = get_source_config(db, mapped)
            if not cfg:
                await update.message.reply_text("Source não encontrada.")
                return
            if action == "user-enable" and not bool(cfg.is_enabled):
                await update.message.reply_text("Não é possível user-enable com source disabled.")
                return
            cfg.user_eligible = action == "user-enable"
            snap = {
                "source": cfg.source,
                "enabled": bool(cfg.is_enabled),
                "user_eligible": bool(cfg.user_eligible),
            }
            db.add(cfg)
            db.commit()
        await update.message.reply_text(f"✅ source={snap['source']} enabled={'sim' if snap['enabled'] else 'não'} user_eligible={'sim' if snap['user_eligible'] else 'não'}")
        return
    if action == "categories":
        from app.bot.admin.auctions import _admin_auctions

        return await _admin_auctions(update, ["source-config", mapped, "categories", *args[2:]])
    await update.message.reply_text("Ação inválida para /admin source.")
