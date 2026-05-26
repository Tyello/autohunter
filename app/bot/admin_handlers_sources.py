from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.bot.text_sanitize import sanitize_for_telegram
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.services.source_configs_service import ensure_source_configs, get_source_config, set_source_field, reset_source_config
from app.sources.flags import read_source_impl_flags

_SENSITIVE_EXTRA_KEY_PARTS = ("token", "secret", "password", "key", "cookie", "session")
_MERCADOLIVRE = "mercadolivre"
_CANARY_RUNTIME_IMPL = "v2_canary"


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
            f"impl={impl_flags.impl}",
            f"mercadolivre_v2_canary_enabled={bool(impl_flags.canary_v2_enabled)}",
            f"canary_effective={bool(canary_effective)}",
            f"extra={_sanitize_source_extra(cfg.extra)}",
        ]
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
            recent = _build_canary_recent_runs_summary(db, cfg.source, window_hours=24)
            recommendation = _build_canary_recommendation(canary_effective, recent)
            lines = [
                "Mercado Livre — V2 Canary",
                f"source={cfg.source}",
                f"impl={impl_flags.impl}",
                f"mercadolivre_v2_canary_enabled={bool(impl_flags.canary_v2_enabled)}",
                f"playwright_enabled={bool(playwright_enabled)}",
                f"browser_fallback_enabled={bool(cfg.browser_fallback_enabled)}",
                f"canary_effective={bool(canary_effective)}",
            ]
            if not canary_effective:
                lines.append(f"reason={canary_reason}")
            lines.extend(
                [
                    "",
                    "Canary recent runs:",
                    f"window={recent['window_hours']}h",
                    f"v2_canary_success={recent['success']}",
                    f"v2_canary_blocked={recent['blocked']}",
                    f"v2_canary_error={recent['error']}",
                    f"last_runtime_impl={recent['last_runtime_impl']}",
                    f"last_success_at={recent['last_success_at']}",
                    f"last_success_found={recent['last_success_found']}",
                    f"last_success_inserted={recent['last_success_inserted']}",
                    f"last_success_matched={recent['last_success_matched']}",
                    f"last_success_queued={recent['last_success_queued']}",
                    f"last_success_duration_ms={recent['last_success_duration_ms']}",
                    f"last_blocked_at={recent['last_blocked_at']}",
                    f"last_error_at={recent['last_error_at']}",
                    f"recommendation={recommendation}",
                ]
            )
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


def _extract_runtime_impl(run: SourceRun) -> str:
    if getattr(run, "payload", None) and isinstance(run.payload, dict):
        payload = run.payload
        if isinstance(payload.get("runtime_impl"), str):
            return str(payload.get("runtime_impl") or "")
        run_summary = payload.get("run_summary")
        if isinstance(run_summary, dict) and isinstance(run_summary.get("runtime_impl"), str):
            return str(run_summary.get("runtime_impl") or "")
    impl = getattr(run, "runtime_impl", None)
    return str(impl or "")


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _fmt_dt(value) -> str:
    if not value:
        return "-"
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _build_canary_recent_runs_summary(db, source: str, *, window_hours: int = 24) -> dict[str, object]:
    window_start = datetime.utcnow() - timedelta(hours=window_hours)
    runs = (
        db.query(SourceRun)
        .filter(SourceRun.source == source, SourceRun.created_at >= window_start)
        .order_by(SourceRun.created_at.desc())
        .all()
    )
    canary_runs: list[SourceRun] = [r for r in runs if _extract_runtime_impl(r) == _CANARY_RUNTIME_IMPL]
    success_statuses = {"success", "ok"}
    blocked_statuses = {"blocked", "skipped"}
    error_statuses = {"error", "failed"}
    success_runs = [r for r in canary_runs if str(r.status or "").strip().lower() in success_statuses]
    blocked_runs = [r for r in canary_runs if str(r.status or "").strip().lower() in blocked_statuses]
    error_runs = [r for r in canary_runs if str(r.status or "").strip().lower() in error_statuses]
    last_run = canary_runs[0] if canary_runs else None
    last_success = success_runs[0] if success_runs else None
    return {
        "window_hours": window_hours,
        "success": len(success_runs),
        "blocked": len(blocked_runs),
        "error": len(error_runs),
        "last_runtime_impl": _extract_runtime_impl(last_run) if last_run else "-",
        "last_success_at": _fmt_dt(getattr(last_success, "created_at", None)),
        "last_success_found": _safe_int(getattr(last_success, "items_found", 0)) if last_success else 0,
        "last_success_inserted": _safe_int(getattr(last_success, "items_ingested", 0)) if last_success else 0,
        "last_success_matched": _safe_int(getattr(last_success, "items_matched", 0)) if last_success else 0,
        "last_success_queued": _safe_int(getattr(last_success, "notifications_queued", 0)) if last_success else 0,
        "last_success_duration_ms": _safe_int(getattr(last_success, "duration_ms", 0)) if last_success else 0,
        "last_blocked_at": _fmt_dt(getattr(blocked_runs[0], "created_at", None)) if blocked_runs else "-",
        "last_error_at": _fmt_dt(getattr(error_runs[0], "created_at", None)) if error_runs else "-",
        "has_canary_runs": bool(canary_runs),
    }


def _build_canary_recommendation(canary_effective: bool, recent: dict[str, object]) -> str:
    if not canary_effective:
        return "canary_not_effective"
    if not bool(recent.get("has_canary_runs")):
        return "run_manual_validation"
    blocked = int(recent.get("blocked") or 0)
    errors = int(recent.get("error") or 0)
    success = int(recent.get("success") or 0)
    if blocked > 0 or errors > 0:
        return "keep_canary_or_rollback_review"
    if success >= 3:
        return "continue_soak_candidate"
    if success >= 1:
        return "continue_soak"
    return "run_manual_validation"


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
