from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.bot.text_sanitize import sanitize_for_telegram
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.services.source_configs_service import ensure_source_configs, get_source_config, set_source_field, reset_source_config
from app.sources.flags import read_source_impl_flags

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
            if last_success_at == "-":
                last_success_at = created_iso
                last_success_found = int(getattr(row, "items_found", 0) or 0)
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
        "/admin sources canary mercadolivre status|report|on|off\n"
        "/admin sources force <source> on|off\n"
        "/admin sources set <source> <field> <value>\n"
        "/admin sources reset <source>"
    )


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
        if last_runtime_impl:
            lines.append(f"last_runtime_impl={last_runtime_impl}")
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
