from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from types import SimpleNamespace
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_, cast, Text, case
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.admin import is_admin
from app.bot.admin_helpers import (
    AUCTION_SETTINGS_LIMITS as _AUCTION_SETTINGS_LIMITS,
    as_utc as _as_utc,
    fmt_dt as _fmt_dt,
    parse_admin_bool as _parse_admin_bool,
    render_rejection_reason_label as _render_rejection_reason_label,
    sample_to_match_like as _sample_to_match_like,
    short as _short,
)
from app.bot.text_sanitize import sanitize_for_telegram
from app.bot.admin_dedupe_diagnostics import (
    DEFAULT_COLLISIONS_LIMIT,
    render_cross_source_dedupe_collisions,
    parse_dedupe_collisions_limit,
)
from app.bot.admin_tracking_diagnostics import render_tracking_diagnostics, parse_tracking_window_hours
from app.bot.renderers import render_admin_auctions_summary, render_admin_auction_lot, render_admin_auction_quality_report, render_admin_auction_source_history, _fmt_money_br, render_auction_alert_preview, render_auction_alert, build_auction_alert_keyboard, _friendly_wishlist_filters
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.models.source_config import SourceConfig
from app.models.user import User
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.system_log import SystemLog
from app.models.wishlist import Wishlist
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.scrape_job import ScrapeJob
from app.models.fb_session import FBSession
from app.models.auction_lot import AuctionLot
from app.sources.registry import list_sources
from app.services.source_staleness_service import evaluate_source_staleness, heartbeat_is_stale
from app.services.plan_capabilities import normalize_plan_code
from app.services.operational_alerts_service import collect_operational_alerts
from app.services.source_operational_policy import (
    classify_source_operational_role,
    should_include_in_critical_stale,
    source_operational_hint,
    source_operational_severity,
)
from app.services.source_configs_service import ensure_source_configs, get_source_config, set_source_field, reset_source_config, invalidate_source_config_cache
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.wishlist_tokens_service import reindex_active_wishlists
from app.services.wishlist_tokens_service import extract_tokens
from app.health.explain import explain_queued_zero, top_buckets
from app.services.admin_deploy_service import AdminDeployService, DeployActor
from app.bot.admin_handlers_sources import (
    admin_sources_dispatch as _admin_sources_dispatch_impl,
    admin_sources_show as _admin_sources_show_impl,
    admin_sources_set_simple as _admin_sources_set_simple_impl,
    admin_sources_reset as _admin_sources_reset_impl,
)
from app.bot.admin_handlers_deploy import admin_deploy as _admin_deploy_impl
from app.services.premium_subscription_service import activate_manual_premium
from app.services.wishlists_service import get_user_plan_snapshot, get_wishlist_summaries, get_wishlist_summaries_cache_stats
from app.services.auction_ingestion_service import inspect_auction_source, run_auction_ingestion
from app.services.auction_matching_service import (
    debug_auction_lot_candidates_for_wishlist,
    match_auction_lots_for_all_wishlists,
    match_auction_lots_for_wishlist,
)
from app.services.auction_quality_service import build_auction_quality_report
from app.services.auction_mega_hygiene_service import run_mega_hygiene
from app.services.auction_source_history_service import build_auction_source_history
from app.services.auction_notification_service import (
    build_auction_notifications_for_wishlist,
    send_auction_notifications_for_wishlist,
    MAX_NOTIFY_LIMIT,
)
from app.services.auction_notification_job_service import run_auction_notification_job
from app.services.auction_notification_status_service import build_auction_notification_status
from app.services.auction_notification_samples_service import build_auction_notification_samples
from app.services.auction_dry_run_digest_service import build_auction_dry_run_digest
from app.services.auction_notification_readiness_service import build_auction_notification_readiness
from app.services.auction_pilot_status_service import build_auction_pilot_status
from app.services.auction_notification_settings_service import (
    get_auction_notification_runtime_settings,
    set_runtime_setting,
    reset_runtime_setting,
    reset_all_runtime_settings,
)
from app.services.app_kv_service import get_kv
from app.services.auction_preview_service import (
    build_auction_alert_previews_for_enabled_wishlists,
    build_auction_alert_previews_for_wishlist,
)
from app.sources.auctions.registry import (
    list_auction_sources,
    render_supported_auction_sources_hint,
    resolve_auction_source_alias,
    get_auction_source_definition,
)
from app.services.auction_source_config_service import (
    ensure_auction_source_configs,
    is_auction_source_enabled,
    is_auction_source_user_eligible,
    list_user_eligible_auction_sources,
)
from app.services.auction_source_categories_service import get_auction_allowed_item_types, normalize_item_type
from app.services.system_logs_service import log
from app.scrapers.webmotors_ops import extract_webmotors_diag_from_payload
from app.services.browser_warmup_service import warmup_source
from app.services.tracking_diagnostics_service import build_tracking_diagnostics
from app.services.cross_source_dedupe_service import find_cross_source_fingerprint_collisions
from app.services.weekly_digest_service import build_weekly_digest_candidates, build_weekly_digest_for_user
from app.bot.weekly_digest_renderer import render_weekly_digest, render_weekly_digest_candidates
from app.scheduler.weekly_digest_job import run_weekly_digest_once
from app.services.weekly_digest_preferences_service import (
    get_or_create_digest_preference,
    get_digest_preference,
    mark_digest_previewed,
    set_weekly_digest_enabled,
    update_weekly_digest_preferences,
)


@dataclass
class _Agg24h:
    total: int = 0
    success: int = 0
    blocked: int = 0
    error: int = 0
    skipped: int = 0
    avg_duration_ms: Optional[int] = None
    avg_found: Optional[int] = None


def _get_bool_setting(attr: Optional[str], default: bool = True) -> bool:
    if not attr:
        return default
    return bool(getattr(settings, attr, default))


def _get_int_setting(attr: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if not attr:
        return default
    v = getattr(settings, attr, default)
    try:
        return int(v) if v is not None else None
    except Exception:
        return default


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



_ADMIN_AUCTION_RUN_LOCK = asyncio.Lock()
_ADMIN_AUCTION_NOTIFY_LOCK = asyncio.Lock()
_AUCTION_NON_ELIGIBLE_WARNING = "Fonte experimental/não elegível para usuário final."


def _render_user_eligible_auction_sources_hint(db) -> str:
    keys = list_user_eligible_auction_sources(db)
    aliases = []
    for key in sorted(keys):
        definition = get_auction_source_definition(key)
        if definition:
            aliases.append(definition.aliases[0])
    return f"Sources elegíveis: {'|'.join(aliases)}" if aliases else "Sources elegíveis: -"


def _admin_user_by_chat(db, chat_id: int | None) -> User | None:
    if chat_id is None:
        return None
    return db.query(User).filter(User.telegram_chat_id == int(chat_id)).first()


def _resolve_admin_wishlist_id_or_index(db, *, chat_id: int | None, raw_target: str) -> tuple[Wishlist | None, str | None]:
    target = str(raw_target or "").strip()
    try:
        wishlist_uuid = uuid.UUID(target)
    except Exception:
        wishlist_uuid = None
    if wishlist_uuid:
        wishlist = db.query(Wishlist).filter(Wishlist.id == wishlist_uuid).first()
        return wishlist, None if wishlist else "Wishlist não encontrada."

    if target.isdigit():
        user = _admin_user_by_chat(db, chat_id)
        if not user:
            return None, "Busca não encontrada para este índice. Use /admin auctions wishlists para ver IDs e índices."
        summaries = get_wishlist_summaries(db, user.id)
        idx = int(target)
        if idx < 1 or idx > len(summaries):
            return None, "Busca não encontrada para este índice. Use /admin auctions wishlists para ver IDs e índices."
        wishlist_id = summaries[idx - 1]["wishlist_id"]
        wishlist = db.query(Wishlist).filter(Wishlist.id == wishlist_id).first()
        if not wishlist:
            return None, "Wishlist não encontrada."
        return wishlist, None

    return None, "Wishlist não encontrada."


def _parse_auction_run_args(args: list[str]) -> tuple[str | None, int | None, bool, str | None]:
    if len(args) < 2:
        return None, None, False, "Use: /admin auctions run <source> [--limit N] [--enrich]"
    source = resolve_auction_source_alias(args[1])
    if not source:
        return None, None, False, f"Source de leilão não suportada. {render_supported_auction_sources_hint()}"
    limit = 10
    enrich = False
    idx = 2
    while idx < len(args):
        token = args[idx].lower()
        if token == "--enrich":
            enrich = True
            idx += 1
            continue
        if token == "--limit":
            if idx + 1 >= len(args):
                return None, None, False, "Limite inválido. Use: --limit <1-30>."
            try:
                limit = int(args[idx + 1])
            except ValueError:
                return None, None, False, "Limite inválido. Use: --limit <1-30>."
            idx += 2
            continue
        return None, None, False, f"Argumento inválido: {args[idx]}"
    if limit < 1 or limit > 30:
        return None, None, False, "Limite inválido. Use: --limit <1-30>."
    return source, limit, enrich, None


def _parse_auction_inspect_args(args: list[str]) -> tuple[str | None, int | None, str | None, str | None]:
    if len(args) < 2:
        return None, None, None, "Use: /admin auctions inspect <source> [--limit N] [--url DETAIL_URL]"
    source = resolve_auction_source_alias(args[1])
    if not source:
        return None, None, None, f"Source de leilão não suportada. {render_supported_auction_sources_hint()}"
    limit = 5
    detail_url = None
    idx = 2
    while idx < len(args):
        token = args[idx].lower()
        if token == "--url":
            if idx + 1 >= len(args):
                return None, None, None, "URL inválida. Use: --url <detail_url>."
            detail_url = args[idx + 1].strip()
            idx += 2
            continue
        if token == "--limit":
            if idx + 1 >= len(args):
                return None, None, None, "Limite inválido. Use: --limit <1-10>."
            try:
                limit = int(args[idx + 1])
            except ValueError:
                return None, None, None, "Limite inválido. Use: --limit <1-10>."
            idx += 2
            continue
        return None, None, None, f"Argumento inválido: {args[idx]}"
    if limit < 1 or limit > 10:
        return None, None, None, "Limite inválido. Use: --limit <1-10>."
    return source, limit, detail_url, None


def _truncate_admin_message(text: str, max_chars: int = 3500) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    suffix = "\n\nDiagnóstico reduzido para caber no Telegram."
    allowed = max(0, max_chars - len(suffix))
    return text[:allowed].rstrip() + suffix, True

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

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dispatcher.

    Usage:
      /admin sources
      /admin health
    """
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    args = [a.strip() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /admin sources | /admin auctions | /admin runall | /admin matchdebug | /admin requeue | /admin reindex_wishlists | /admin tokens | /admin health | /admin audit | /admin users | /admin errors | /admin deploy | /admin premium | /admin dedupe | /admin tracking | /admin digest")
        return

    action = args[0].lower()
    if action == "sources":
        await _admin_sources_dispatch(update, args[1:])
        return
    if action == "source":
        await _admin_source_unified(update, args[1:])
        return
    if action == "health":
        await _admin_health(update, args[1:])
        return
    if action == "audit":
        await _admin_audit(update, args[1:])
        return
    if action == "users":
        await _admin_users(update, args[1:])
        return
    if action == "errors":
        await _admin_errors(update, args[1:])
        return
    if action == "deploy":
        await _admin_deploy(update, context, args[1:])
        return
    if action == "fb_sessions":
        await _admin_fb_sessions(update)
        return
    if action == "runall":
        await _admin_runall(update, args[1:])
        return
    if action == "warmup":
        await _admin_warmup(update, args[1:])
        return
    if action == "premium":
        await _admin_premium(update, context, args[1:])
        return
    if action == "auctions":
        await _admin_auctions(update, args[1:])
        return
    if action == "dedupe":
        await _admin_dedupe(update, args[1:])
        return
    if action == "tracking":
        await _admin_tracking(update, args[1:])
        return
    if action == "digest":
        await _admin_digest(update, args[1:])
        return

    if action == "matchdebug":
        await _admin_matchdebug(update, args[1:])
        return

    if action == "requeue":
        await _admin_requeue(update, args[1:])
        return

    if action == "reindex_wishlists":
        await _admin_reindex_wishlists(update, args[1:])
        return

    if action == "tokens":
        from app.bot.admin_tokens import admin_tokens_dispatch
        await admin_tokens_dispatch(update, args[1:])
        return

    await update.message.reply_text("Ação inválida. Use: /admin sources | /admin warmup | /admin auctions | /admin runall | /admin matchdebug | /admin requeue | /admin reindex_wishlists | /admin tokens | /admin health | /admin audit | /admin users | /admin errors | /admin deploy | /admin fb_sessions | /admin premium | /admin dedupe | /admin tracking | /admin digest")





async def _admin_digest(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /admin digest user <telegram_chat_id> [1-30] | /admin digest candidates [1-30] [1-50] | /admin digest prefs <chat_id> | /admin digest enable <chat_id> | /admin digest disable <chat_id> | /admin digest config <chat_id> days|limit <valor> | /admin digest run [dry|live]")
        return
    sub = args[0].lower()
    if sub == "run":
        mode = (args[1].lower() if len(args) >= 2 else "dry")
        if mode not in {"dry", "live"}:
            await update.message.reply_text("Use: /admin digest run [dry|live]")
            return
        if mode == "live" and not bool(getattr(settings, "weekly_digest_job_enabled", False)):
            await update.message.reply_text("Live bloqueado: weekly_digest_job_enabled=false.")
            return
        stats = run_weekly_digest_once(dry_run=(mode != "live"))
        await update.message.reply_text(
            "Digest run summary\n"
            f"mode={mode}\n"
            f"checked={stats.get('checked', 0)}\n"
            f"eligible={stats.get('eligible', 0)}\n"
            f"sent={stats.get('sent', 0)}\n"
            f"skipped_recent={stats.get('skipped_recent', 0)}\n"
            f"skipped_empty={stats.get('skipped_empty', 0)}\n"
            f"failed={stats.get('failed', 0)}"
        )
        return

    if sub == "candidates":
        days = 7
        limit = 20
        if len(args) >= 2:
            try:
                days = int(args[1])
            except Exception:
                await update.message.reply_text("Janela inválida, usando padrão de 7 dias.")
                days = 7
        if len(args) >= 3:
            try:
                limit = int(args[2])
            except Exception:
                await update.message.reply_text("Limite inválido, usando padrão de 20.")
                limit = 20
        days = max(1, min(30, days))
        limit = max(1, min(50, limit))
        with SessionLocal() as db:
            candidates = build_weekly_digest_candidates(db, days=days, limit=limit)
        await update.message.reply_text(render_weekly_digest_candidates(candidates, days=days))
        return


    if sub in {"prefs", "enable", "disable", "config"}:
        if len(args) < 2:
            await update.message.reply_text("Informe o telegram_chat_id.")
            return
        try:
            chat_id = int(args[1])
        except Exception:
            await update.message.reply_text("telegram_chat_id inválido.")
            return
        with SessionLocal() as db:
            user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
            if not user:
                await update.message.reply_text("Usuário não encontrado para este telegram_chat_id.")
                return
            if sub == "prefs":
                pref = get_or_create_digest_preference(db, user.id)
            elif sub == "enable":
                pref = set_weekly_digest_enabled(db, user.id, True)
            elif sub == "disable":
                pref = set_weekly_digest_enabled(db, user.id, False)
            else:
                if len(args) < 4 or args[2].lower() not in {"days", "limit"}:
                    await update.message.reply_text("Use: /admin digest config <chat_id> days <1-30> | /admin digest config <chat_id> limit <1-20>")
                    return
                key = args[2].lower()
                try:
                    value = int(args[3])
                except Exception:
                    await update.message.reply_text("Valor inválido.")
                    return
                try:
                    pref = update_weekly_digest_preferences(db, user.id, **{key: value})
                except ValueError as exc:
                    await update.message.reply_text(str(exc))
                    return
            await update.message.reply_text(
                "Digest prefs\n"
                f"chat_id={chat_id}\n"
                f"enabled={'true' if pref.weekly_digest_enabled else 'false'}\n"
                f"days={pref.digest_days}\n"
                f"limit={pref.digest_limit}\n"
                f"last_sent_at={pref.last_digest_sent_at or '-'}\n"
                f"last_previewed_at={pref.last_digest_previewed_at or '-'}"
            )
        return
    if len(args) < 2 or sub != "user":
        await update.message.reply_text("Use: /admin digest user <telegram_chat_id> [1-30] | /admin digest candidates [1-30] [1-50] | /admin digest prefs <chat_id> | /admin digest enable <chat_id> | /admin digest disable <chat_id> | /admin digest config <chat_id> days|limit <valor> | /admin digest run [dry|live]")
        return

    try:
        chat_id = int(args[1])
    except Exception:
        await update.message.reply_text("telegram_chat_id inválido.")
        return

    days = 7
    if len(args) >= 3:
        try:
            days = int(args[2])
        except Exception:
            await update.message.reply_text("Janela inválida, usando padrão de 7 dias.")
            days = 7
    days = max(1, min(30, days))

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not user:
            await update.message.reply_text("Usuário não encontrado para este telegram_chat_id.")
            return
        payload = build_weekly_digest_for_user(db, user_id=user.id, days=days, limit=10)
        mark_digest_previewed(db, user.id, create_if_missing=True)

    await update.message.reply_text(render_weekly_digest(payload))
async def _admin_tracking(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if args and args[0].lower() not in {"status", "price_drop"}:
        await update.message.reply_text("Use: /admin tracking | /admin tracking status [horas] | /admin tracking price_drop [horas]")
        return

    window_hours = parse_tracking_window_hours(args[1:] if args else [])
    with SessionLocal() as db:
        payload = build_tracking_diagnostics(db, window_hours=window_hours)
    rendered = render_tracking_diagnostics(payload)
    msg, _ = _truncate_admin_message(rendered, max_chars=3500)
    await update.message.reply_text(msg)


async def _admin_dedupe(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if args and args[0].lower() not in {"collisions"}:
        await update.message.reply_text("Use: /admin dedupe | /admin dedupe collisions [N]")
        return

    limit = parse_dedupe_collisions_limit(args)
    with SessionLocal() as db:
        collisions = find_cross_source_fingerprint_collisions(db, limit=limit)

    rendered = render_cross_source_dedupe_collisions(collisions)
    msg, _ = _truncate_admin_message(rendered, max_chars=3500)
    await update.message.reply_text(msg)

def _render_warmup_result(source: str, payload: dict) -> str:
    steps = payload.get("steps_completed") or []
    signals = payload.get("challenge_signals") or []
    lines = [
        f"🧪 Warmup — {source}",
        "",
        f"ok={bool(payload.get('ok'))}",
        f"storage_state_saved={bool(payload.get('storage_state_saved'))}",
        f"still_challenge={bool(payload.get('still_challenge'))}",
        f"provider={payload.get('challenge_provider') or '-'}",
        f"reason={payload.get('challenge_reason') or '-'}",
        f"signals={','.join([str(s) for s in signals]) if signals else '-'}",
        f"title={payload.get('title') or '-'}",
        f"final_url={payload.get('final_url') or '-'}",
        f"duration_ms={int(payload.get('duration_ms') or 0)}",
    ]
    if not bool(payload.get("ok")) and payload.get("error"):
        lines.append(f"error={_short(str(payload.get('error')), 240)}")
    lines.extend(["", "steps:"])
    for s in steps:
        lines.append(f"- {s}")
    lines.extend(["", "leitura:"])
    if payload.get("still_challenge"):
        lines.append("bloqueio anti-bot/fingerprint ainda presente; warmup salvou estado, mas não removeu challenge.")
    else:
        lines.append("warmup não detectou challenge neste momento; rode /admin runall webmotors para validar efeito real.")
    return "\n".join(lines)


async def _admin_warmup(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    source = (args[0].lower() if args else "webmotors")
    with SessionLocal() as db:
        ensure_source_configs(db)
        cfg = get_source_config(db, source)
        extra = (cfg.extra if cfg and isinstance(cfg.extra, dict) else {}) or {}
        behavior = {}
        for key in (
            "webmotors_warmup_behavior_enabled",
            "webmotors_warmup_scroll_enabled",
            "webmotors_warmup_mouse_enabled",
            "webmotors_warmup_consent_enabled",
            "webmotors_warmup_extra_wait_ms",
        ):
            if key in extra and extra.get(key) is not None:
                behavior[key] = extra.get(key)
        proxy = cfg.proxy_server if cfg else None
    await update.message.reply_text(sanitize_for_telegram(f"🧪 warmup iniciado… source={source}"))
    res = await asyncio.to_thread(warmup_source, source=source, proxy_server=proxy, behavior=behavior)
    payload = dict(res.data or {})
    payload.setdefault("ok", bool(res.ok))
    if not res.ok and res.error:
        payload["error"] = res.error
    await update.message.reply_text(sanitize_for_telegram(_render_warmup_result(source, payload)))


async def _admin_auctions(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    with SessionLocal() as db:
        ensure_auction_source_configs(db)
        if not args:
            total = db.query(func.count(AuctionLot.id)).scalar() or 0
            by_source = dict(db.query(AuctionLot.source, func.count(AuctionLot.id)).group_by(AuctionLot.source).all())
            by_status = dict(db.query(AuctionLot.status, func.count(AuctionLot.id)).group_by(AuctionLot.status).all())
            by_item_type = dict(db.query(AuctionLot.item_type, func.count(AuctionLot.id)).group_by(AuctionLot.item_type).all())
            latest = db.query(AuctionLot).order_by(AuctionLot.updated_at.desc()).limit(5).all()
            text = render_admin_auctions_summary(
                {"total_lots": total, "by_source": by_source, "by_status": by_status, "by_item_type": by_item_type},
                latest,
            )
            await update.message.reply_text(text)
            return

        sub = args[0].lower()
        if sub == "source":
            if len(args) < 2:
                await update.message.reply_text("Use: /admin auctions source <source>")
                return
            source = resolve_auction_source_alias(args[1])
            if not source:
                await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                return
            include_invalid = "--include-invalid" in args[2:]
            base_query = db.query(AuctionLot).filter(AuctionLot.source == source)
            skip_reason = func.coalesce(cast(AuctionLot.extras["skip_reason"], Text), "")
            hidden_invalid_count = 0
            if not include_invalid:
                hidden_invalid_count = (
                    base_query.filter(
                        or_(
                            AuctionLot.status == "invalid",
                            skip_reason == '"generic_page"',
                        )
                    ).count()
                )
                base_query = base_query.filter(
                    AuctionLot.status != "invalid",
                    skip_reason != '"generic_page"',
                )
            lots = base_query.order_by(AuctionLot.updated_at.desc()).limit(10).all()
            if not lots:
                if hidden_invalid_count > 0:
                    await update.message.reply_text(
                        "\n".join(
                            [
                                f"Nenhum lote útil persistido para source={source}.",
                                f"Registros históricos inválidos ocultos: {hidden_invalid_count}",
                                "Use:",
                                f"/admin auctions source {args[1]} --include-invalid",
                            ]
                        )
                    )
                else:
                    await update.message.reply_text(f"Nenhum lote persistido para source={source}.")
                return
            lines = [f"⚠️ Admin Leilões — source {source} (últimos {len(lots)})", ""]
            for lot in lots:
                lines.append(render_admin_auction_lot(lot))
                lines.append("")
            if hidden_invalid_count > 0:
                lines.extend(
                    [
                        f"Registros históricos inválidos ocultos: {hidden_invalid_count}",
                        "Use:",
                        f"/admin auctions source {args[1]} --include-invalid",
                    ]
                )
            await update.message.reply_text("\n".join(lines).strip())
            return

        if sub == "quality":
            source = args[1] if len(args) >= 2 else None
            if source and not resolve_auction_source_alias(source):
                await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                return
            report = build_auction_quality_report(db, source=source)
            await update.message.reply_text(render_admin_auction_quality_report(report))
            return
        if sub == "hygiene":
            if len(args) < 2 or args[1].lower() != "mega":
                await update.message.reply_text("Use: /admin auctions hygiene mega [--dry-run|--apply] [--limit N]")
                return
            apply_mode = "--apply" in args[2:]
            limit = 200
            if "--limit" in args[2:]:
                i = args.index("--limit")
                if i + 1 < len(args):
                    try:
                        limit = max(1, min(2000, int(args[i + 1])))
                    except Exception:
                        pass
            out = run_mega_hygiene(db, apply=apply_mode, limit=limit)
            lines = [
                f"🧹 Admin Leilões — hygiene {out['source']}",
                f"modo: {'apply' if apply_mode else 'dry-run'}",
                f"experimental: {'sim' if out.get('is_experimental') else 'não'}",
                f"analisados: {out.get('analyzed', 0)}",
                f"atualizados: {out.get('updated', 0)}",
            ]
            if out.get("blocked"):
                lines.extend([
                    "bloqueado: sim (source_not_experimental)",
                    "nenhuma alteração aplicada: source não experimental",
                ])
            lines.extend([
                "",
                "issues:",
            ])
            counts = out.get("issue_counts") or {}
            for k in ("generic_page", "item_type_mismatch", "motorcycle_mismatch", "truck_mismatch", "invalid_location", "missing_lot_id"):
                lines.append(f"- {k}: {counts.get(k, 0)}")
            examples = out.get("examples") or []
            if examples:
                lines.extend(["", "exemplos:"])
                for ex in examples[:3]:
                    lines.append(f"- {ex.get('external_id') or '-'} | issues={','.join(ex.get('issues') or [])} | url={ex.get('url') or '-'}")
            await update.message.reply_text("\n".join(lines))
            return
        if sub in {"source-history", "monitor"}:
            if len(args) < 2:
                await update.message.reply_text("Use: /admin auctions source-history <source>")
                return
            source = resolve_auction_source_alias(args[1])
            if not source:
                await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                return
            history = build_auction_source_history(db, source=source, limit=8)
            await update.message.reply_text(render_admin_auction_source_history(history))
            return

        if sub == "upcoming":
            lots = db.query(AuctionLot).order_by(
                case((AuctionLot.auction_end_at.is_(None), 1), else_=0).asc(),
                AuctionLot.auction_end_at.asc(),
                AuctionLot.updated_at.desc(),
            ).limit(10).all()
            with_end = [lot for lot in lots if lot.auction_end_at is not None]
            without_end = [lot for lot in lots if lot.auction_end_at is None]
            if with_end:
                lines = ["⚠️ Admin Leilões — próximos encerramentos", ""]
            else:
                lines = ["⚠️ Admin Leilões — upcoming", "Sem data de encerramento capturada nesta fase.", ""]
            if not lots:
                lines.append("Nenhum lote persistido ainda.")
            else:
                for lot in with_end or lots:
                    lines.append(render_admin_auction_lot(lot))
                    lines.append("")
                if with_end and without_end:
                    lines.append("Sem encerramento capturado:")
                    lines.append("")
                    for lot in without_end[:3]:
                        lines.append(render_admin_auction_lot(lot))
                        lines.append("")
            await update.message.reply_text("\n".join(lines).strip())
            return

        if sub == "run":
            source, limit, enrich_details, err = _parse_auction_run_args(args)
            if err:
                await update.message.reply_text(err)
                return
            if _ADMIN_AUCTION_RUN_LOCK.locked():
                await update.message.reply_text("Já existe uma execução de leilões em andamento. Aguarde finalizar.")
                return

            started_at = datetime.now(timezone.utc)
            await update.message.reply_text(f"⏳ Rodando leilões {source} com limit={limit} enrich={'true' if enrich_details else 'false'}...")
            logger.info(
                "admin_auction_run_started",
                extra={"source": source, "limit": limit, "enrich_details": enrich_details, "chat_id": update.effective_chat.id},
            )
            try:
                async with _ADMIN_AUCTION_RUN_LOCK:
                    summary = await asyncio.to_thread(
                        run_auction_ingestion,
                        source=source,
                        limit=limit,
                        enrich_details=enrich_details,
                    )
            except Exception as exc:
                logger.exception(
                    "admin_auction_run_failed",
                    extra={"source": source, "limit": limit, "enrich_details": enrich_details, "chat_id": update.effective_chat.id},
                )
                msg = str(exc).strip().replace("\n", " ")
                if len(msg) > 180:
                    msg = f"{msg[:177]}..."
                await update.message.reply_text(
                    f"Falha ao rodar ingestão de leilões: {type(exc).__name__} — {msg or 'erro sem mensagem'}"
                )
                return

            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            logger.info(
                "admin_auction_run_finished",
                extra={
                    "source": source,
                    "limit": limit,
                    "enrich_details": enrich_details,
                    "chat_id": update.effective_chat.id,
                    "fetched": summary.get("fetched", 0),
                    "inserted": summary.get("inserted", 0),
                    "updated": summary.get("updated", 0),
                    "errors": summary.get("errors", 0),
                    "duration_ms": duration_ms,
                },
            )
            lines = [
                f"⚠️ Admin Leilões — run {summary.get('source', source)}",
                "",
                f"limit: {limit}",
                f"enrich: {'sim' if enrich_details else 'não'}",
                "",
                "Resultado:",
                f"- encontrados: {summary.get('fetched', 0)}",
                f"- inseridos: {summary.get('inserted', 0)}",
                f"- atualizados: {summary.get('updated', 0)}",
                f"- ignorados: {summary.get('skipped', 0)}",
                f"- erros: {summary.get('errors', 0)}",
                f"- duração_ms: {duration_ms}",
            ]
            if (summary.get("fetched", 0) == 0) and summary.get("reason"):
                lines.extend(["", f"Motivo: {summary.get('reason')}"])
            skipped_reasons = summary.get("skipped_reasons") or {}
            if skipped_reasons:
                lines.extend(["", "Ignorados:"])
                for reason_key, count in sorted(skipped_reasons.items()):
                    lines.append(f"- {reason_key}: {count}")
            ignored_examples = summary.get("ignored_examples") or []
            if ignored_examples:
                lines.extend(["", "ignored_examples:"])
                for item in ignored_examples[:3]:
                    lines.append(
                        f"- reason={item.get('reason')} source={item.get('source')} url={item.get('url') or '-'} "
                        f"title={item.get('title') or '-'} fallback_title={item.get('fallback_title') or '-'} "
                        f"text_preview={item.get('text_preview') or '-'}"
                    )
            lines.extend(["", "Próximo passo:", f"/admin auctions source {source}"])
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "inspect":
            source, limit, detail_url, err = _parse_auction_inspect_args(args)
            if err:
                await update.message.reply_text(err)
                return
            summary = await asyncio.to_thread(
                inspect_auction_source,
                source=source,
                limit=limit,
                enrich_details=True,
                detail_url=detail_url,
            )
            lines = [
                f"🔎 Admin Leilões — inspect {summary.get('source', source)}",
                f"limit: {limit}",
                f"capturados: {summary.get('fetched', 0)}",
                f"enrich_applied: {'sim' if summary.get('enrich_applied') else 'não'}",
            ]
            if detail_url:
                lines.append(f"detail_url: {detail_url}")
            if summary.get("reason"):
                lines.append(f"reason: {summary['reason']}")
            diag = summary.get("diagnostics") or {}
            hints = diag.get("hints") or {}
            endpoints = (hints.get("possible_api_endpoints") or [])[:5]
            detail_candidates = (hints.get("lot_detail_candidates") or [])[:5]
            image_candidates = (hints.get("lot_image_candidates") or [])[:5]
            doc_candidates = (hints.get("lot_document_candidates") or [])[:5]
            detail_diags = ((diag.get("detail_diagnostics") or {}).get("win_detail") or {})
            if diag and summary.get("fetched", 0) == 0:
                lines.extend(["", "Diagnóstico HTTP:", f"- url: {diag.get('url') or '-'}", f"- final_url: {diag.get('final_url') or '-'}", f"- status: {diag.get('status_code') or '-'}", f"- content_type: {diag.get('content_type') or '-'}", f"- tamanho: {diag.get('content_length') or 0} bytes", f"- title: {diag.get('html_title') or '-'}"])
                lines.append(f"- hints: has_script_tags={hints.get('has_script_tags')} possible_js_app={hints.get('possible_js_app')} endpoint_candidates={len(hints.get('possible_api_endpoints') or [])}")
                lines.extend(["", "Preview HTML:", diag.get("html_preview") or "-"])
            if endpoints:
                lines.append("- endpoint_candidates_top:")
                for ep in endpoints:
                    lines.append(f"  - {ep}")
            if detail_candidates:
                lines.append("- lot_detail_candidates_top:")
                for ep in detail_candidates:
                    lines.append(f"  - {ep}")
            if image_candidates:
                lines.append("- lot_image_candidates_top:")
                for ep in image_candidates:
                    lines.append(f"  - {ep}")
            if doc_candidates:
                lines.append("- lot_document_candidates_top:")
                for ep in doc_candidates:
                    lines.append(f"  - {ep}")
            if detail_diags:
                lines.extend(["", "Diagnóstico detalhe Win:"])
                for key in ("status_candidates", "date_candidates", "bid_candidates", "json_like_blocks", "hidden_inputs", "data_attributes"):
                    key_limit = 3 if key in {"status_candidates", "date_candidates", "bid_candidates"} else 1
                    values = (detail_diags.get(key) or [])[:key_limit]
                    lines.append(f"- {key}:")
                    if values:
                        for value in values:
                            snippet = re.sub(r"\s+", " ", str(value or "")).strip()
                            if snippet:
                                lines.append(f"  - {snippet[:120]}")
                    else:
                        lines.append("  - -")
            for c in summary.get("candidates", []):
                lines.extend(
                    [
                        "",
                        f"#{c.get('index')}",
                        f"url: {c.get('url') or '-'}",
                        f"title: {c.get('title') or '-'}",
                        f"title_fallback: {c.get('title_fallback') or '-'}",
                        f"external_id: {c.get('external_id') or '-'}",
                        f"item_type: {c.get('item_type') or '-'}",
                        f"current_bid: {c.get('current_bid') or '-'}",
                        f"initial_bid: {c.get('initial_bid') or '-'}",
                        f"year: {c.get('year') or '-'}",
                        f"status: {c.get('status') or '-'}",
                        f"skip_reason: {c.get('skip_reason') or '-'}",
                        f"text_preview: {c.get('text_preview') or '-'}",
                    ]
                )
            msg, _ = _truncate_admin_message("\n".join(lines), max_chars=3500)
            await update.message.reply_text(msg)
            return

        if sub == "sources":
            changed = ensure_auction_source_configs(db)
            if changed:
                db.commit()
            lines = ["⚙️ Admin Leilões — sources", ""]
            for item in sorted([d.key for d in list_auction_sources()]):
                cfg = get_source_config(db, item)
                label = get_auction_source_definition(item).label if get_auction_source_definition(item) else item
                lines.extend([
                    label,
                    f"source: {item}",
                    f"enabled: {'sim' if bool(getattr(cfg, 'is_enabled', False)) else 'não'}",
                    f"user_eligible: {'sim' if bool(getattr(cfg, 'user_eligible', False)) else 'não'}",
                    f"status: {getattr(cfg, 'status', '-') or '-'}",
                    f"categorias: {', '.join(sorted(get_auction_allowed_item_types(db, item))) if bool(getattr(cfg, 'user_eligible', False)) else '-'}",
                    "",
                ])
            await update.message.reply_text("\n".join(lines).strip())
            return

        if sub == "source-config":
            if len(args) < 3:
                await update.message.reply_text("Use: /admin auctions source-config <source> <enable|disable|user-enable|user-disable>")
                return
            source = resolve_auction_source_alias(args[1])
            if not source:
                await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                return
            ensure_auction_source_configs(db)
            cfg = get_source_config(db, source)
            action = args[2].lower()
            if action == "enable":
                cfg.is_enabled = True
            elif action == "disable":
                cfg.is_enabled = False
                cfg.user_eligible = False
            elif action == "user-enable":
                if not bool(cfg.is_enabled):
                    await update.message.reply_text("Não é possível user-enable com source disabled.")
                    return
                cfg.user_eligible = True
            elif action == "user-disable":
                cfg.user_eligible = False
            elif action == "categories":
                extra = dict(cfg.extra or {})
                if len(args) == 3:
                    allowed = sorted(get_auction_allowed_item_types(db, source))
                    await update.message.reply_text(f"source={source} categorias={','.join(allowed)}")
                    return
                if len(args) < 5:
                    await update.message.reply_text("Use: /admin auctions source-config <source> categories <set|add|remove> <tipos>")
                    return
                sub_action = args[3].lower()
                tokens = [normalize_item_type(x.strip()) for x in args[4].split(",")]
                normalized = [t for t in tokens if t]
                cur = set(get_auction_allowed_item_types(db, source))
                if sub_action == "set":
                    cur = set(normalized) or {"car"}
                elif sub_action == "add":
                    cur |= set(normalized)
                elif sub_action == "remove":
                    cur -= set(normalized)
                    if not cur:
                        cur = {"car"}
                else:
                    await update.message.reply_text("Ação inválida para categories.")
                    return
                extra["allowed_item_types"] = sorted(cur)
                cfg.extra = extra
                invalidate_source_config_cache(source)
            else:
                await update.message.reply_text("Ação inválida.")
                return
            db.add(cfg); db.commit()
            await update.message.reply_text(f"✅ source={source} enabled={'sim' if cfg.is_enabled else 'não'} user_eligible={'sim' if cfg.user_eligible else 'não'}")
            return

        if sub == "motos":
            lots = db.query(AuctionLot).filter(AuctionLot.item_type == "motorcycle").order_by(AuctionLot.updated_at.desc()).limit(10).all()
            if not lots:
                await update.message.reply_text("Não há lotes de motos persistidos ainda.")
                return
            lines = [f"⚠️ Admin Leilões — motos (últimos {len(lots)})", ""]
            for lot in lots:
                lines.append(render_admin_auction_lot(lot))
                lines.append("")
            await update.message.reply_text("\n".join(lines).strip())
            return

        if sub == "wishlists":
            chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
            user = _admin_user_by_chat(db, chat_id)
            if not user:
                await update.message.reply_text("Nenhum usuário associado ao chat atual para listar buscas.")
                return
            query = " ".join(args[1:]).strip().lower() if len(args) > 1 else ""
            summaries = get_wishlist_summaries(db, user.id)
            if query:
                summaries = [s for s in summaries if query in str(s.get("query") or "").lower()]
            if not summaries:
                await update.message.reply_text("Nenhuma busca encontrada para este filtro.")
                return
            max_items = 10
            lines = ["⚠️ Admin Leilões — buscas", ""]
            for item in summaries[:max_items]:
                labels = _friendly_wishlist_filters(item.get("filters", []))
                lines.extend([
                    f"{item['index']}. {item['query']}",
                    f"ID: {item['wishlist_id']}",
                    f"Leilões: {'ativado' if item.get('include_auctions', False) else 'desativado'}",
                    f"Status: {'ativa' if item.get('is_active', True) else 'pausada'}",
                    f"Filtros: {labels[0] if labels else 'Nenhum filtro'}",
                    "",
                ])
            if len(summaries) > max_items:
                lines.append(f"Mostrando {max_items} de {len(summaries)} buscas. Use /admin auctions wishlists <texto> para filtrar.")
            await update.message.reply_text("\n".join(lines).strip())
            return

        if sub == "notify-run":
            if _ADMIN_AUCTION_NOTIFY_LOCK.locked():
                await update.message.reply_text("Já existe uma execução de notify-run de leilões em andamento. Aguarde finalizar.")
                return
            real_mode = any(a.strip().lower() in {"--real", "--confirm"} for a in args[1:])
            has_dry_run = any(a.strip().lower() == "--dry-run" for a in args[1:])
            if real_mode and has_dry_run:
                await update.message.reply_text("Use apenas um modo: --real (envio real manual) ou --dry-run (simulação).")
                return
            dry_run = not real_mode
            source = None
            cfg = get_auction_notification_runtime_settings(db)
            limit_wishlists = cfg["max_wishlists_per_run"]
            limit_per_wishlist = cfg["max_per_wishlist"]
            extra = args[1:]
            i = 0
            while i < len(extra):
                token = extra[i].strip().lower()
                if token == "--source" and i + 1 < len(extra):
                    source = resolve_auction_source_alias(extra[i + 1])
                    if not source:
                        await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                        return
                    i += 2
                    continue
                if token == "--limit-wishlists" and i + 1 < len(extra):
                    try:
                        limit_wishlists = int(extra[i + 1])
                    except Exception:
                        await update.message.reply_text("Limite de buscas inválido. Use inteiro positivo.")
                        return
                    i += 2
                    continue
                if token == "--limit-per-wishlist" and i + 1 < len(extra):
                    try:
                        limit_per_wishlist = int(extra[i + 1])
                    except Exception:
                        await update.message.reply_text("Limite por busca inválido. Use inteiro positivo.")
                        return
                    i += 2
                    continue
                i += 1
            if limit_wishlists < 1 or limit_per_wishlist < 1:
                await update.message.reply_text("Limites inválidos. Use inteiros positivos.")
                return
            if source and not is_auction_source_user_eligible(db, source):
                await update.message.reply_text("Source não elegível para envio ao usuário.")
                return
            if real_mode:
                if not source:
                    await update.message.reply_text("Envio real manual exige source explícita: --source vip.")
                    return
                if source != "vip_auctions":
                    await update.message.reply_text("Envio real manual disponível apenas para vip_auctions neste piloto.")
                    return
                readiness = build_auction_notification_readiness(db)
                reason = None
                summary = readiness.get("summary") if isinstance(readiness, dict) else None
                ready_sources = set((summary or {}).get("car_pilot_ready_sources") or [])
                if not ready_sources and isinstance(readiness, dict):
                    # defensive fallback for legacy/mock payloads
                    ready_sources = set(readiness.get("car_pilot_ready_sources") or [])
                if source not in ready_sources:
                    reason = "readiness_sem_source_pronta"
                elif not is_auction_source_enabled(db, source):
                    reason = "source_disabled"
                elif not is_auction_source_user_eligible(db, source):
                    reason = "source_not_user_eligible"
                elif "car" not in set(get_auction_allowed_item_types(db, source)):
                    reason = "source_without_car_allowed"
                elif not (update.get_bot() if hasattr(update, "get_bot") else None):
                    reason = "bot_unavailable"
                elif int(cfg.get("max_per_user_per_day", 0) or 0) <= 0:
                    reason = "max_per_user_per_day_invalid"
                elif int(limit_per_wishlist or 0) <= 0:
                    reason = "max_per_wishlist_invalid"
                elif int(limit_wishlists or 0) <= 0:
                    reason = "max_wishlists_invalid"
                else:
                    wl_count = (
                        db.query(Wishlist)
                        .filter(Wishlist.is_active.is_(True), Wishlist.include_auctions.is_(True))
                        .count()
                    )
                    if wl_count <= 0:
                        reason = "no_active_wishlist_include_auctions"
                if reason:
                    payload = {
                        "source": source,
                        "limit_wishlists": limit_wishlists,
                        "max_per_wishlist": limit_per_wishlist,
                        "reason": reason,
                        "admin_chat_id": getattr(getattr(update, "effective_chat", None), "id", None),
                    }
                    log(db, "error", "bot.admin", "auction_notification_manual_real_run_failed", payload=payload)
                    db.commit()
                    await update.message.reply_text(f"Falha operacional no envio real manual: {reason}. Nenhum alerta foi enviado.")
                    return
            async with _ADMIN_AUCTION_NOTIFY_LOCK:
                result = await run_auction_notification_job(
                    db,
                    bot=None if dry_run else (update.get_bot() if hasattr(update, "get_bot") else None),
                    dry_run=dry_run,
                    max_wishlists=limit_wishlists,
                    max_per_wishlist=limit_per_wishlist,
                    max_per_user_per_day=cfg["max_per_user_per_day"],
                    source=source,
                )
            if real_mode:
                log(
                    db,
                    "info",
                    "bot.admin",
                    "auction_notification_manual_real_run_finished",
                    payload={
                        "source": source,
                        "limit_wishlists": limit_wishlists,
                        "wishlists_scanned": result.get("wishlists_scanned", 0),
                        "wishlists_with_matches": result.get("wishlists_with_matches", 0),
                        "sent": result.get("sent", 0),
                        "skipped_duplicate": result.get("skipped_duplicate", 0),
                        "skipped_score_below_min": result.get("skipped_score_below_min", 0),
                        "skipped_item_type_not_allowed": result.get("skipped_item_type_not_allowed", 0),
                        "skipped_daily_limit": result.get("skipped_daily_limit", 0),
                        "errors": result.get("errors", 0),
                        "admin_chat_id": getattr(getattr(update, "effective_chat", None), "id", None),
                    },
                )
                db.commit()
            lines = [
                "🚨 Admin Leilões — notify-run REAL" if real_mode else "⚠️ Admin Leilões — notify-run",
                f"Source: {source or '-'}",
                f"Modo: {'envio real manual' if real_mode else 'dry-run'}",
                "Scheduler automático real: não alterado" if real_mode else "Nenhum alerta foi enviado.",
            ]
            if real_mode:
                lines.append("")
                lines.append(f"Enviados: {result.get('sent', 0)}")
            elif not dry_run:
                lines.append(f"Alertas enviados: {result.get('sent', 0)}")
            lines.extend([
                "",
                f"Buscas avaliadas: {result.get('wishlists_scanned', 0)}",
                f"Buscas com match: {result.get('wishlists_with_matches', 0)}",
                f"Prévias: {result.get('previews', 0)}",
                f"Score baixo: {result.get('skipped_score_below_min', 0)}",
                f"Lote antigo: {result.get('skipped_stale_lot', 0)}",
                f"Sem data de atualização: {result.get('skipped_missing_lot_updated_at', 0)}",
                f"Tipo bloqueado: {result.get('skipped_item_type_not_allowed', 0)}",
                f"Sem tipo: {result.get('skipped_missing_item_type', 0)}",
                f"Duplicados ignorados: {result.get('skipped_duplicate', 0)}",
                f"Sem match: {result.get('skipped_no_match', 0)}",
                f"Sem chat id: {result.get('skipped_missing_chat_id', 0)}",
                f"Limite diário: {result.get('skipped_daily_limit', 0)}",
                f"Erros: {result.get('errors', 0)}",
            ])
            if (
                int(result.get("sent", 0) or 0) == 0
                and int(result.get("previews", 0) or 0) == 0
                and int(result.get("skipped_duplicate", 0) or 0) > 0
            ):
                lines.extend(["", "Leitura: nenhum novo alerta enviado porque os matches elegíveis já foram notificados."])
            if int(result.get("skipped_item_type_not_allowed", 0) or 0) > 0:
                lines.extend(["", "Leitura: lotes fora da categoria permitida foram bloqueados antes do score."])
            rejections = list(result.get("rejections") or [])[:5]
            if rejections:
                lines.extend(["", "Rejeições principais:"])
                for rej in rejections:
                    reason = str(rej.get("reason") or "-")
                    title = str(rej.get("title") or "Sem título")
                    detail = str(rej.get("detail") or "-")
                    lines.append(f"- {reason}: {title} — {detail}")
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "settings":
            cfg = get_auction_notification_runtime_settings(db)
            extra = args[1:]
            actor = str(getattr(getattr(update, "effective_chat", None), "id", "-"))
            if extra and extra[0].lower() == "set":
                if len(extra) < 3:
                    await update.message.reply_text("Use: /admin auctions settings set <key> <value>")
                    return
                key = extra[1].strip().lower()
                raw_value = extra[2].strip()
                if key in {"enabled", "dry_run"}:
                    parsed = _parse_admin_bool(raw_value)
                    if parsed is None:
                        await update.message.reply_text("Valor inválido. Use true|false.")
                        return
                    if key == "dry_run" and parsed is False:
                        await update.message.reply_text("Envio real automático ainda não é permitido por este comando.")
                        return
                    set_runtime_setting(db, key, parsed, updated_by=actor)
                elif key in _AUCTION_SETTINGS_LIMITS:
                    try:
                        parsed_int = int(raw_value)
                    except Exception:
                        await update.message.reply_text("Valor inválido. Use inteiro.")
                        return
                    low, high = _AUCTION_SETTINGS_LIMITS[key]
                    if parsed_int < low or parsed_int > high:
                        await update.message.reply_text(f"Valor fora da faixa para {key}: {low}..{high}.")
                        return
                    set_runtime_setting(db, key, parsed_int, updated_by=actor)
                else:
                    await update.message.reply_text("Chave inválida.")
                    return
                cfg = get_auction_notification_runtime_settings(db)
            elif extra and extra[0].lower() == "reset":
                if len(extra) < 2:
                    await update.message.reply_text("Use: /admin auctions settings reset <key>")
                    return
                key = extra[1].strip().lower()
                if key not in {"enabled", "dry_run", *list(_AUCTION_SETTINGS_LIMITS.keys())}:
                    await update.message.reply_text("Chave inválida para reset.")
                    return
                reset_runtime_setting(db, key, updated_by=actor)
                cfg = get_auction_notification_runtime_settings(db)
            elif extra and extra[0].lower() == "reset-all":
                reset_all_runtime_settings(db)
                cfg = get_auction_notification_runtime_settings(db)

            lines = [
                "⚙️ Admin Leilões — settings",
                "",
                "Efetivo:",
                f"- enabled: {'sim' if cfg['enabled'] else 'não'}",
                f"- dry_run: {'sim' if cfg['dry_run'] else 'não'}",
                f"- scheduler: {cfg['scheduler_minutes']} min",
                f"- max buscas/run: {cfg['max_wishlists_per_run']}",
                f"- max por busca: {cfg['max_per_wishlist']}",
                f"- max usuário/dia: {cfg['max_per_user_per_day']}",
                f"- score mínimo: {cfg['min_score']}",
                f"- idade máxima lote: {cfg['max_lot_age_hours']}h",
                "",
                "Origem:",
            ]
            for key in ["enabled", "dry_run", "scheduler_minutes", "max_wishlists_per_run", "max_per_wishlist", "max_per_user_per_day", "min_score", "max_lot_age_hours"]:
                lines.append(f"- {key}: {cfg.get('source', {}).get(key, '-')}")
            if cfg.get("kill_switch"):
                lines.extend(["", "⚠️ kill_switch ativo via env (enabled efetivo forçado para não)."])
            lines.extend([
                "",
                "Comandos:",
                "/admin auctions settings set enabled true|false",
                "/admin auctions settings set dry_run true|false",
                "/admin auctions settings set scheduler_minutes 60",
                "/admin auctions settings set min_score 60",
                "/admin auctions settings set max_lot_age_hours 48",
                "/admin auctions settings set max_wishlists_per_run 20",
                "/admin auctions settings set max_per_wishlist 1",
                "/admin auctions settings set max_per_user_per_day 3",
                "/admin auctions settings reset <key>",
                "/admin auctions settings reset-all",
            ])
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "readiness":
            data = build_auction_notification_readiness(db)
            icon = "✅" if data.get("status") == "ok" else ("⚠️" if data.get("status") == "warn" else "❌")
            status_text = {
                "ok": "pronto para dry-run automático",
                "warn": "pronto com ressalvas para dry-run automático",
                "fail": "não ativar scheduler de leilões ainda",
            }.get(data.get("status"), "indeterminado")
            summary = data.get("summary") or {}
            lines = [
                f"{icon} Admin Leilões — readiness",
                "",
                f"Status: {icon} {status_text}",
                "",
                "Config:",
                f"- enabled: {'sim' if data.get('enabled') else 'não'}",
                f"- dry_run: {'sim' if data.get('dry_run') else 'não'}",
                f"- min_score: {summary.get('min_score', '-')}",
                f"- max idade lote: {summary.get('max_lot_age_hours', '-')}h",
                f"- max usuário/dia: {summary.get('max_per_user_per_day', '-')}",
                "",
                "Resumo:",
                f"- sources elegíveis: {summary.get('eligible_sources_count', 0)}",
                f"- buscas com leilões: {summary.get('wishlists_opt_in', 0)}",
                f"- lotes car elegíveis recentes com lance: {summary.get('recent_eligible_lots_with_bid', 0)}",
                f"- sources prontas piloto car: {', '.join(summary.get('car_pilot_ready_sources') or []) or '-'}",
                f"- última execução scheduler: {summary.get('scheduler_last_run_at', '-')}",
                f"- últimas amostras: {summary.get('dry_run_samples', 0)}",
                "",
                "Sources/piloto car:",
            ]
            for src, src_summary in sorted((summary.get("source_car_pilot") or {}).items()):
                ready = "sim" if src_summary.get("source_ready_for_user_car_pilot") else "não"
                data_quality = "sim" if src_summary.get("data_quality_ready_car") else "não"
                lines.append(
                    f"- {src}: car_lots={src_summary.get('car_lots', 0)}, "
                    f"user_allowed_lots={src_summary.get('user_allowed_lots', 0)}, "
                    f"dados_car={data_quality}, "
                    f"status/live={'sim' if int(src_summary.get('open_or_live_count', 0) or 0) > 0 else 'não'}, "
                    f"início={'sim' if int(src_summary.get('with_auction_start_at_count', 0) or 0) > 0 else 'não'}, "
                    f"encerramento={'sim' if int(src_summary.get('with_auction_end_at_count', 0) or 0) > 0 else 'não'}, "
                    f"user_facing={ready}, "
                    f"motivo={src_summary.get('user_facing_ready_reason', '-')}"
                )
            lines.extend([
                "",
                "Checks:",
            ])
            for check in data.get("checks", []):
                c_icon = "✅" if check.get("status") == "ok" else ("⚠️" if check.get("status") == "warn" else "❌")
                lines.append(f"{c_icon} {check.get('label')}: {check.get('detail')}")
            lines.extend([
                "",
                "🚫 Envio real automático não recomendado nesta fase.",
                "",
                "Próximo passo:",
                "Para validar volume sem envio real:",
                "1. Configure AUCTION_NOTIFICATIONS_ENABLED=true",
                "2. Mantenha AUCTION_NOTIFICATIONS_DRY_RUN=true",
                "3. Reinicie o scheduler",
                "4. Acompanhe:",
                "/admin auctions notify-status",
                "/admin auctions notify-samples",
            ])
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "pilot":
            data = build_auction_pilot_status(db)
            await update.message.reply_text(render_admin_auction_pilot_status(data))
            return

        if sub == "notify-status":
            status = build_auction_notification_status(db)
            if status.get("kill_switch"):
                health_line = "kill_switch ativo via env. Envio real bloqueado."
            elif not status["enabled"]:
                health_line = "Envio automático desligado. Seguro para produção."
            elif status["dry_run"]:
                health_line = "Scheduler automático em simulação. Nenhum alerta real é enviado automaticamente."
            else:
                health_line = "🚨 Envio automático real ativo"
            lines = [
                "⚠️ Admin Leilões — notificações",
                "",
                health_line,
                "",
                "Config:",
                f"- enabled: {'sim' if status['enabled'] else 'não'}",
                f"- dry_run: {'sim' if status['dry_run'] else 'não'}",
                f"- scheduler: {status['scheduler_minutes']} min",
                f"- max buscas/run: {status['max_wishlists']}",
                f"- max por busca: {status['max_per_wishlist']}",
                f"- max usuário/dia: {status['max_per_user_per_day']}",
                f"- score mínimo: {status.get('min_score', '-') }",
                f"- idade máxima do lote (h): {status.get('max_lot_age_hours', '-')}",
                "",
                "Sources elegíveis:",
            ]
            sources = status.get("eligible_sources") or []
            if sources:
                for source_key in sources:
                    lines.append(f"- {source_key}")
            else:
                lines.append("- -")
            lines.extend([
                "",
                "Última execução:",
                f"- quando: {status['last_run_at']}",
                f"- status: {status['last_status']}",
                f"- motivo: {status['last_reason']}",
                f"- enviados: {status['last_sent']}",
                f"- prévias: {status['last_previews']}",
                f"- sem match: {status['last_skipped_no_match']}",
                f"- duplicados: {status['last_skipped_duplicate']}",
                f"- score baixo: {status.get('last_skipped_score_below_min', 0)}",
                f"- lote antigo: {status.get('last_skipped_stale_lot', 0)}",
                f"- sem data atualização: {status.get('last_skipped_missing_lot_updated_at', 0)}",
                f"- limite diário: {status['last_skipped_daily_limit']}",
                f"- erros: {status['last_errors']}",
                "",
                "Último envio real manual:",
                f"- quando: {status.get('last_manual_real_run_at', '-')}",
                f"- enviados reais: {status.get('last_manual_real_sent', 0)}",
                f"- duplicados: {status.get('last_manual_real_duplicates', 0)}",
                f"- erros: {status.get('last_manual_real_errors', 0)}",
                "",
                f"Scheduler automático real: {'ativo' if (status['enabled'] and not status['dry_run']) else 'não (dry_run=true ou disabled)'}",
                "",
                "Modo operacional:",
            ])
            readiness = build_auction_notification_readiness(db)
            readiness_summary = readiness.get("summary") if isinstance(readiness, dict) else {}
            ready_sources = set((readiness_summary or {}).get("car_pilot_ready_sources") or [])
            vip_allowed_types = set(get_auction_allowed_item_types(db, "vip_auctions"))
            vip_manual_available = (
                is_auction_source_user_eligible(db, "vip_auctions")
                and "car" in vip_allowed_types
                and "vip_auctions" in ready_sources
            )
            if not status["enabled"]:
                scheduler_mode = "desligado"
            elif status["dry_run"]:
                scheduler_mode = "dry-run"
            else:
                scheduler_mode = "envio real automático"
            lines.extend([
                f"- scheduler automático: {scheduler_mode}",
                f"- envio real manual: {'disponível para VIP' if vip_manual_available else 'indisponível (validar readiness/source)'}",
                "- preview admin: disponível via /admin auctions preview-send",
                "",
                "Próximo passo:",
                "Para validar volume sem envio real, use:",
                "/admin auctions notify-run --source vip --limit-wishlists 5",
                "",
                "Para ver amostras do último dry-run:",
                "/admin auctions notify-samples",
            ])
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "notify-samples":
            data = build_auction_notification_samples(db, limit=10)
            samples = data.get("samples") or []
            rejections = data.get("rejections") or []
            summary = data.get("summary") or {}
            if not samples:
                if (
                    summary.get("previews", 0) == 0
                    and summary.get("errors", 0) == 0
                    and summary.get("wishlists_scanned", 0) > 0
                    and summary.get("skipped_no_match", 0) > 0
                ):
                    lines = [
                        "⚠️ Admin Leilões — últimas amostras dry-run",
                        "",
                        "Último dry-run executado, mas não houve alerta elegível.",
                        "",
                        "Resumo:",
                        f"- buscas avaliadas: {summary.get('wishlists_scanned', 0)}",
                        f"- buscas com match: {summary.get('wishlists_with_matches', 0)}",
                        f"- sem match: {summary.get('skipped_no_match', 0)}",
                        f"- score baixo: {summary.get('skipped_score_below_min', 0)}",
                        f"- lote antigo: {summary.get('skipped_stale_lot', 0)}",
                        f"- tipo bloqueado: {summary.get('skipped_item_type_not_allowed', 0)}",
                        f"- duplicados: {summary.get('skipped_duplicate', 0)}",
                        f"- erros: {summary.get('errors', 0)}",
                        "",
                        "Interpretação:",
                        "- A source está operacional.",
                        "- Nenhuma wishlist atual bateu com os lotes recentes.",
                        "",
                        "Próximo passo:",
                        "- rode /admin auctions source vip",
                        "- rode /admin auctions match wishlist <id|index> --debug",
                        "- ou crie uma busca temporária com um modelo presente nos lotes recentes.",
                    ]
                    await update.message.reply_text("\n".join(lines))
                    return
                if rejections:
                    reasons = {str((r or {}).get("reason") or "").strip().lower() for r in rejections}
                    lines = [
                        "⚠️ Admin Leilões — últimas amostras dry-run",
                        "",
                        "Nenhum novo alerta elegível nesta última execução.",
                    ]
                    if "duplicate" in reasons:
                        lines.extend(["", "Há alertas compatíveis que não foram exibidos porque já foram notificados anteriormente."])
                    if "item_type_not_allowed" in reasons:
                        lines.extend(["", "Alguns lotes foram bloqueados por categoria, conforme configuração da source."])
                    previewable = get_kv(db, "auction_last_previewable_auction_sample") or {}
                    if isinstance(previewable, dict) and isinstance(previewable.get("sample"), dict):
                        lines.extend([
                            "",
                            "Há uma amostra anterior disponível para preview visual:",
                            "use /admin auctions preview-send",
                        ])
                    lines.extend([
                        "",
                        "",
                        "Rejeições recentes:",
                    ])
                    for idx, rej in enumerate(rejections[:5], start=1):
                        lines.extend([
                            f"{idx}. {rej.get('wishlist_query') or '-'} / {str(rej.get('source') or '-').replace('_auctions', '').upper()}",
                            f"Título: {rej.get('title') or '-'}",
                            f"Motivo: {_render_rejection_reason_label(rej.get('reason'))}",
                            f"Atualizado em: {rej.get('updated_at') or '-'}",
                            f"Score: {rej.get('score') if rej.get('score') is not None else '-'}",
                            f"Lance atual: {_fmt_money_br(rej.get('current_bid')) if rej.get('current_bid') is not None else '-'}",
                            "",
                        ])
                    lines.extend(["Próximo passo:", "- rode /admin auctions match wishlist <id|index> --debug", "- ou revise filtros/query da busca"])
                    await update.message.reply_text("\n".join(lines).strip())
                    return
                await update.message.reply_text(
                    "⚠️ Admin Leilões — últimas amostras dry-run\n\n"
                    "Ainda não há amostras de dry-run.\n"
                    "Rode:\n/admin auctions notify-run --source vip --limit-wishlists 5"
                )
                return
            lines = [
                "⚠️ Admin Leilões — últimas amostras dry-run",
                "",
                f"Gerado em: {data.get('created_at', '-')}",
                "",
                "Resumo:",
                f"- buscas avaliadas: {summary.get('wishlists_scanned', 0)}",
                f"- buscas com match: {summary.get('wishlists_with_matches', 0)}",
                f"- prévias: {summary.get('previews', 0)}",
                f"- score baixo: {summary.get('skipped_score_below_min', 0)}",
                f"- lote antigo: {summary.get('skipped_stale_lot', 0)}",
                f"- sem data atualização: {summary.get('skipped_missing_lot_updated_at', 0)}",
                f"- duplicados: {summary.get('skipped_duplicate', 0)}",
                f"- sem match: {summary.get('skipped_no_match', 0)}",
                f"- limite diário: {summary.get('skipped_daily_limit', 0)}",
                f"- erros: {summary.get('errors', 0)}",
                "",
                "Amostras user-facing simuladas:",
            ]
            for idx, sample in enumerate(samples[:10], start=1):
                match_like = _sample_to_match_like(sample)
                lines.extend([
                    "",
                    f"{idx}. Wishlist: {sample.get('wishlist_query') or '-'}",
                    f"Score: {sample.get('score') if sample.get('score') is not None else '-'}",
                    "",
                    render_auction_alert_preview(match_like),
                ])
                if sample.get("url"):
                    lines.extend([
                        "",
                        "Botão:",
                        str(sample.get("button_label") or "🔗 Ver leilão"),
                        str(sample.get("url")),
                    ])
            if rejections:
                lines.extend(["", "Rejeições recentes:"])
                for idx, rej in enumerate(rejections[:5], start=1):
                    lines.extend([
                        f"{idx}. {rej.get('wishlist_query') or '-'} / {str(rej.get('source') or '-').replace('_auctions', '').upper()}",
                        f"Título: {rej.get('title') or '-'}",
                        f"Motivo: {_render_rejection_reason_label(rej.get('reason'))}",
                        f"Atualizado em: {rej.get('updated_at') or '-'}",
                        f"Score: {rej.get('score') if rej.get('score') is not None else '-'}",
                        f"Lance atual: {_fmt_money_br(rej.get('current_bid')) if rej.get('current_bid') is not None else '-'}",
                        "",
                    ])
            await update.message.reply_text("\n".join(lines))
            return

        if sub in {"preview-send", "notify-preview-send"}:
            data = build_auction_notification_samples(db, limit=1)
            sample = (data.get("samples") or [None])[0]
            using_fallback = False
            if not sample:
                previewable = get_kv(db, "auction_last_previewable_auction_sample") or {}
                if isinstance(previewable, dict) and isinstance(previewable.get("sample"), dict):
                    sample = previewable.get("sample")
                    using_fallback = True
            if not sample:
                await update.message.reply_text(
                    "Não há amostra disponível. Rode /admin auctions notify-run --source vip --limit-wishlists 5 primeiro."
                )
                return
            match_like = _sample_to_match_like(sample)
            preview_text = (
                ("🧪 Preview admin — usando última amostra elegível conhecida\n\n" if using_fallback else "🧪 Preview admin — não enviado ao usuário\n\n")
                + render_auction_alert(match_like)
            )
            admin_chat_id = getattr(getattr(update, "effective_chat", None), "id", None)
            bot = update.get_bot() if hasattr(update, "get_bot") else None
            if not bot or admin_chat_id is None:
                await update.message.reply_text("Bot indisponível para preview.")
                return
            await bot.send_message(
                chat_id=admin_chat_id,
                text=preview_text,
                reply_markup=build_auction_alert_keyboard(sample.get("url")),
                disable_web_page_preview=True,
            )
            if using_fallback:
                await update.message.reply_text("🧪 Preview admin — usando última amostra elegível conhecida")
            await update.message.reply_text("✅ Preview enviado para este chat admin.")
            return

        if sub == "digest":
            hours = 24
            if "--hours" in args:
                i = args.index("--hours")
                if i + 1 >= len(args):
                    await update.message.reply_text("Use: /admin auctions digest [--hours 24]")
                    return
                try:
                    hours = int(args[i + 1])
                except Exception:
                    await update.message.reply_text("hours inválido. Use inteiro entre 1 e 168.")
                    return
            if hours < 1 or hours > 168:
                await update.message.reply_text("hours inválido. Use inteiro entre 1 e 168.")
                return
            data = build_auction_dry_run_digest(db, hours=hours)
            since = str(data.get("since") or "-").replace("T", " ").replace("+00:00", " UTC")
            last_run = str(data.get("last_run_at") or "-").replace("T", " ").replace("+00:00", " UTC")
            lines = [
                f"⚠️ Admin Leilões — digest dry-run {hours}h",
                "",
                "Janela:",
                f"- desde: {since}",
                f"- última execução: {last_run}",
                f"- status: {data.get('last_status', 'unknown')}",
                "",
                "Resumo:",
                f"- runs: {data.get('runs', 0)}",
                f"- buscas avaliadas: {data.get('wishlists_scanned', 0)}",
                f"- buscas com match: {data.get('wishlists_with_matches', 0)}",
                f"- prévias: {data.get('previews', 0)}",
                f"- enviados reais: {data.get('sent', 0)}",
                f"- erros: {data.get('errors', 0)}",
                "",
                "Bloqueios:",
                f"- lote antigo: {data.get('skips', {}).get('stale_lot', 0)}",
                f"- sem match textual: {data.get('skips', {}).get('no_match', 0)}",
                f"- score abaixo do mínimo: {data.get('skips', {}).get('score_below_min', 0)}",
                f"- tipo bloqueado: {data.get('skips', {}).get('item_type_not_allowed', 0)}",
                f"- duplicados: {data.get('skips', {}).get('duplicate', 0)}",
                f"- limite diário: {data.get('skips', {}).get('daily_limit', 0)}",
                "",
                "Sources:",
            ]
            source_summary = data.get("source_summary") or {}
            if source_summary:
                for src, info in source_summary.items():
                    lines.append(f"- {src}: previews={info.get('previews', 0)} erros={info.get('errors', 0)}")
            else:
                lines.append("- -")
            samples = data.get("latest_samples") or []
            rejections = data.get("latest_rejections") or []
            if samples:
                lines.extend(["", "Últimas amostras:"])
                for idx, sample in enumerate(samples[:3], start=1):
                    lines.append(
                        f"{idx}. {sample.get('wishlist_query') or '-'} — {sample.get('title') or '-'} — "
                        f"{sample.get('source_label') or sample.get('source') or '-'} — score {sample.get('score') if sample.get('score') is not None else '-'} "
                        f"— lance {_fmt_money_br(sample.get('current_bid')) if sample.get('current_bid') is not None else '-'}"
                    )
            if rejections:
                lines.extend(["", "Últimas rejeições:"])
                for idx, rej in enumerate(rejections[:3], start=1):
                    lines.append(
                        f"{idx}. {rej.get('wishlist_query') or '-'} — {rej.get('title') or '-'} — "
                        f"{_render_rejection_reason_label(rej.get('reason'))} — score {rej.get('score') if rej.get('score') is not None else '-'}"
                    )
            if data.get("history_note"):
                lines.extend(["", "Observação:", f"- {data.get('history_note')}"])
            rec = data.get("recommendation") or {}
            icon = "✅" if rec.get("status") in {"keep_dry_run", "ready_for_manual_pilot"} else ("⚠️" if rec.get("status") == "needs_attention" else "ℹ️")
            lines.extend(["", "Recomendação:", f"{icon} {rec.get('message') or '-'}"])
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "notify":
            if len(args) < 3 or args[1].lower() != "wishlist":
                await update.message.reply_text("Use: /admin auctions notify wishlist <wishlist_id|index> [--source <alias>] [--limit N] [--force] [--allow-no-bid] [--allow-experimental] [--confirm|--dry-run]")
                return
            if _ADMIN_AUCTION_NOTIFY_LOCK.locked():
                await update.message.reply_text("Já existe um envio de alerta de leilão em andamento. Aguarde finalizar.")
                return
            resolved_wishlist, err = _resolve_admin_wishlist_id_or_index(
                db,
                chat_id=getattr(getattr(update, "effective_chat", None), "id", None),
                raw_target=args[2].strip(),
            )
            if not resolved_wishlist:
                await update.message.reply_text(err or "Wishlist não encontrada.")
                return
            target_id = str(resolved_wishlist.id)
            force = any(a.strip().lower() == "--force" for a in args[3:])
            confirm = any(a.strip().lower() == "--confirm" for a in args[3:])
            source = None
            limit = 1
            allow_experimental = any(a.strip().lower() == "--allow-experimental" for a in args[3:])
            allow_no_bid = any(a.strip().lower() == "--allow-no-bid" for a in args[3:])
            extra = args[3:]
            if extra and not extra[0].startswith("--"):
                source = resolve_auction_source_alias(extra[0])
                if not source:
                    await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                    return
            i = 0
            while i < len(extra):
                token = extra[i].lower().strip()
                if token == "--source" and i + 1 < len(extra):
                    source = resolve_auction_source_alias(extra[i + 1])
                    if not source:
                        await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                        return
                    i += 2
                    continue
                if token == "--limit" and i + 1 < len(extra):
                    try:
                        limit = int(extra[i + 1])
                    except Exception:
                        await update.message.reply_text("Limite inválido. Use inteiro entre 1 e 3.")
                        return
                    i += 2
                    continue
                i += 1
            if limit < 1 or limit > MAX_NOTIFY_LIMIT:
                await update.message.reply_text("Limite inválido. Use inteiro entre 1 e 3.")
                return
            if allow_experimental and source is None:
                await update.message.reply_text(
                    "Use --source <alias> junto com --allow-experimental para evitar envio amplo por fontes experimentais."
                )
                return
            if source and not is_auction_source_user_eligible(db, source) and not allow_experimental:
                await update.message.reply_text(
                    "Source não elegível para envio ao usuário. Use --allow-experimental para diagnóstico controlado."
                )
                return
            if any(a.strip().lower() == "--dry-run" for a in args[3:]) and confirm:
                await update.message.reply_text("Use apenas um modo: --confirm (envio real) ou --dry-run (simulação).")
                return
            dry_run = not confirm
            async with _ADMIN_AUCTION_NOTIFY_LOCK:
                if dry_run:
                    await update.message.reply_text("Dry-run: nenhum alerta foi enviado.")
                    result = build_auction_notifications_for_wishlist(
                        db,
                        target_id,
                        source=source,
                        limit=limit,
                        force=force,
                        eligible_sources=None if allow_experimental else list_user_eligible_auction_sources(db),
                        allow_no_bid=allow_no_bid,
                    )
                    previews = result.get("items", [])[:MAX_NOTIFY_LIMIT]
                    for item in previews:
                        await update.message.reply_text(
                            "🧪 Dry-run — alerta de leilão\n\n" + item["text"],
                            disable_web_page_preview=True
                        )
                    lines = [
                        "Dry-run: nenhum alerta foi enviado. Para enviar de verdade, rode com --confirm.",
                        f"Prévias: {len(previews)}",
                        f"Elegíveis: {result.get('sent', 0)}",
                        f"Duplicados ignorados: {result.get('skipped_duplicate', 0)}",
                        f"Sem match elegível: {result.get('skipped_no_match', 0)}",
                        f"Sem chat id: {result.get('skipped_missing_chat_id', 0)}",
                        f"Erros: {result.get('errors', 0)}",
                    ]
                else:
                    await update.message.reply_text(f"Enviando até {limit} alerta(s) reais de leilão para a busca {target_id}...")
                    result = await send_auction_notifications_for_wishlist(
                        db,
                        update.get_bot(),
                        target_id,
                        source=source,
                        limit=limit,
                        force=force,
                        eligible_sources=None if allow_experimental else list_user_eligible_auction_sources(db),
                        allow_no_bid=allow_no_bid,
                    )
                    lines = [
                        f"✅ Alertas enviados: {result.get('sent', 0)}",
                        f"Duplicados ignorados: {result.get('skipped_duplicate', 0)}",
                        f"Sem match elegível: {result.get('skipped_no_match', 0)}",
                        f"Sem chat id: {result.get('skipped_missing_chat_id', 0)}",
                        f"Erros: {result.get('errors', 0)}",
                    ]
            if result.get("messages"):
                lines.append(f"Detalhe: {result['messages'][0]}")
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "preview":
            if len(args) >= 3 and args[1].lower() == "wishlist":
                force = any(a.strip().lower() == "--force" for a in args[3:])
                all_sources = any(a.strip().lower() == "--all-sources" for a in args[3:])
                resolved_wishlist, err = _resolve_admin_wishlist_id_or_index(
                    db,
                    chat_id=getattr(getattr(update, "effective_chat", None), "id", None),
                    raw_target=args[2],
                )
                if not resolved_wishlist:
                    await update.message.reply_text(err or "Wishlist não encontrada.")
                    return
                result = build_auction_alert_previews_for_wishlist(
                    db, str(resolved_wishlist.id), force=force, limit=5, eligible_sources=None if all_sources else list_user_eligible_auction_sources(db)
                )
                if result.warning:
                    await update.message.reply_text(result.warning)
                    return
                matches = result.matches
            elif len(args) >= 2:
                source = resolve_auction_source_alias(args[1])
                if not source:
                    await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                    return
                matches = build_auction_alert_previews_for_enabled_wishlists(db, source=source, limit=5)
                if not is_auction_source_user_eligible(db, source):
                    await update.message.reply_text(_AUCTION_NON_ELIGIBLE_WARNING)
            else:
                matches = build_auction_alert_previews_for_enabled_wishlists(db, limit=5, eligible_sources=list_user_eligible_auction_sources(db))

            if not matches:
                await update.message.reply_text("Sem previews de leilão no momento.")
                return
            if len(matches) >= 5:
                await update.message.reply_text("Mostrando os 5 primeiros previews.")
            for m in matches[:5]:
                await update.message.reply_text(render_auction_alert_preview(m), disable_web_page_preview=True)
            return

        if sub == "match":
            if len(args) >= 3 and args[1].lower() == "wishlist":
                target_id = args[2].strip()
                force = any(a.strip().lower() == "--force" for a in args[3:])
                debug = any(a.strip().lower() == "--debug" for a in args[3:])
                wishlist, err = _resolve_admin_wishlist_id_or_index(
                    db,
                    chat_id=getattr(getattr(update, "effective_chat", None), "id", None),
                    raw_target=target_id,
                )
                if not wishlist:
                    await update.message.reply_text(err or "Wishlist não encontrada.")
                    return
                if not force and not bool(getattr(wishlist, "include_auctions", False)):
                    await update.message.reply_text(
                        f"Esta busca não está habilitada para leilões. Use /admin auctions wishlist {wishlist.id} enable para habilitar."
                    )
                    return
                all_sources = any(a.strip().lower() == "--all-sources" for a in args[3:])
                eligible_sources = None if all_sources else list_user_eligible_auction_sources(db)
                matches = match_auction_lots_for_wishlist(
                    db, wishlist, limit=10, eligible_sources=eligible_sources
                )
                if debug:
                    candidates = debug_auction_lot_candidates_for_wishlist(
                        db, wishlist, limit=10, eligible_sources=eligible_sources
                    )
                    lines = [
                        "⚠️ Admin Leilões — match debug",
                        f"Wishlist: {wishlist.id}",
                        f"Query: {wishlist.query}",
                        f"include_auctions: {'sim' if wishlist.include_auctions else 'não'}",
                        f"Filtros: {', '.join(_friendly_wishlist_filters(getattr(wishlist, 'filters', []) or [])) or 'nenhum'}",
                        f"Sources elegíveis: {', '.join(sorted(eligible_sources or [])) if eligible_sources is not None else 'todas'}",
                        "",
                        "Candidatos recentes:",
                    ]
                    if not candidates:
                        lines.append("Nenhum lote recente encontrado nas sources elegíveis.")
                    for c in candidates:
                        soft_block = ""
                        if c.get("reject_reason") == "ok" and c.get("passes_filters") and int(c.get("score") or 0) < 60:
                            soft_block = " | aviso=passa matching, mas pode cair no notify por min_score"
                        lines.append(
                            f"- {c.get('title') or '-'} | source={c.get('source') or '-'} | tipo={c.get('item_type_normalized') or c.get('item_type') or '-'} | permitidos={','.join(c.get('allowed_item_types') or []) or '-'} | "
                            f"ano={c.get('year') or '-'} | lance={c.get('current_bid') or '-'} | updated_at={c.get('updated_at') or '-'} | "
                            f"filtros={'ok' if c.get('passes_filters') else 'não'} | score={c.get('score')} | motivo={c.get('reject_reason')}{soft_block}"
                        )
                    await update.message.reply_text("\n".join(lines))
                    return
                if not matches:
                    await update.message.reply_text("Sem leilões compatíveis para esta busca.")
                    return
                await update.message.reply_text("\n".join(_render_admin_auction_matches(wishlist.query, matches)))
                return
            elif len(args) >= 2 and args[1].lower() == "wishlist":
                await update.message.reply_text("Use: /admin auctions match wishlist <wishlist_id|index> [--force] [--debug]")
                return
            elif len(args) >= 2:
                source = resolve_auction_source_alias(args[1])
                if not source:
                    await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                    return
                matches_by = match_auction_lots_for_all_wishlists(db, source=source, limit_per_wishlist=5)
                if not is_auction_source_user_eligible(db, source):
                    await update.message.reply_text(_AUCTION_NON_ELIGIBLE_WARNING)
            else:
                matches_by = match_auction_lots_for_all_wishlists(
                    db, limit_per_wishlist=5, eligible_sources=list_user_eligible_auction_sources(db)
                )


            if not matches_by:
                await update.message.reply_text("Sem leilões compatíveis no momento.")
                return
            lines = ["⚠️ Admin Leilões — matching (somente leitura)", ""]
            for _wid, matches in matches_by.items():
                if not matches:
                    continue
                lines.extend(_render_admin_auction_matches(matches[0].wishlist_query, matches))
                lines.append("")
            await update.message.reply_text("\n".join(lines).strip())
            return
        if sub == "wishlist":
            if len(args) < 3:
                await update.message.reply_text("Use: /admin auctions wishlist <wishlist_id|index> <enable|disable> | /admin auctions notify wishlist <wishlist_id|index> [--source <alias>] [--limit N] [--force] [--allow-no-bid] [--allow-experimental] [--confirm|--dry-run]")
                return
            target_id = args[1].strip()
            action = args[2].strip().lower()
            wishlist, err = _resolve_admin_wishlist_id_or_index(
                db,
                chat_id=getattr(getattr(update, "effective_chat", None), "id", None),
                raw_target=target_id,
            )
            if not wishlist:
                await update.message.reply_text(err or "Wishlist não encontrada.")
                return
            if action == "enable":
                wishlist.include_auctions = True
                db.add(wishlist)
                db.commit()
                await update.message.reply_text("✅ Leilões ativados para esta busca.")
                return
            if action == "disable":
                wishlist.include_auctions = False
                db.add(wishlist)
                db.commit()
                await update.message.reply_text("✅ Leilões desativados para esta busca.")
                return
            await update.message.reply_text("Use: /admin auctions wishlist <wishlist_id|index> <enable|disable> | /admin auctions notify wishlist <wishlist_id|index> [--source <alias>] [--limit N] [--force] [--allow-no-bid] [--allow-experimental] [--confirm|--dry-run]")
            return

    sources_hint = render_supported_auction_sources_hint().replace("Use: ", "")
    await update.message.reply_text(
        "Use: /admin auctions | /admin auctions source <source> | /admin auctions run <source> [--limit N] [--enrich] "
        "| /admin auctions upcoming | /admin auctions quality [source] | /admin auctions source-history <source> | /admin auctions monitor <source> | /admin auctions motos "
        f"| /admin auctions match [{sources_hint}|wishlist <wishlist_id|index> [--force] [--all-sources]] | /admin auctions preview [{sources_hint}|wishlist <wishlist_id|index> [--force] [--all-sources]] | /admin auctions wishlists [texto] | /admin auctions wishlist <wishlist_id|index> <enable|disable> | /admin auctions notify wishlist <wishlist_id|index> [--source <alias>] [--limit N] [--force] [--allow-no-bid] [--allow-experimental] [--confirm|--dry-run] | /admin auctions settings | /admin auctions readiness | /admin auctions pilot | /admin auctions notify-status | /admin auctions notify-samples | /admin auctions preview-send | /admin auctions digest [--hours 24]\n{_render_user_eligible_auction_sources_hint(db)}"
    )



def render_admin_auction_pilot_status(status: dict) -> str:
    health = (status or {}).get("health") or {}
    icon = "✅" if health.get("status") == "ok" else ("⚠️" if health.get("status") == "warning" else "❌")
    mode = (status or {}).get("mode") or {}
    sources = (status or {}).get("sources") or {}
    wish = (status or {}).get("wishlists") or {}
    notif = (status or {}).get("notifications") or {}
    if not mode.get("scheduler_enabled"):
        scheduler_mode = "desligado"
    elif mode.get("scheduler_dry_run"):
        scheduler_mode = "dry-run"
    else:
        scheduler_mode = "real"
    lines = [
        f"{icon} Admin Leilões — piloto",
        "",
        "Modo:",
        f"- scheduler automático: {scheduler_mode}",
        f"- envio real manual: {'disponível para VIP' if mode.get('manual_real_available') else 'indisponível (validar readiness/source)'}",
        f"- envio real automático: {'sim' if mode.get('automatic_real_active') else 'não'}",
        "",
        "Adoção:",
        f"- buscas ativas: {wish.get('active_total', 0)}",
        f"- buscas com leilões: {wish.get('include_auctions_total', 0)}",
        f"- usuários com leilões: {wish.get('users_with_auction_wishlists', 0)}",
        "",
        "Sources user-facing:",
    ]
    ues = sources.get("user_eligible") or []
    lines.extend([f"- {src}" for src in ues] or ["- -"])
    lines.extend(["", "Sources experimentais/admin:"])
    exp = sources.get("experimental_enabled") or []
    lines.extend([f"- {src}" for src in exp] or ["- -"])
    lines.extend([
        "",
        "Envios reais manuais:",
        f"- último envio: {notif.get('last_manual_real_at') or 'sem envio real manual registrado'}",
        f"- enviados último run: {notif.get('last_manual_real_sent', 0)}",
        f"- duplicados último run: {notif.get('last_manual_real_duplicates', 0)}",
        f"- erros último run: {notif.get('last_manual_real_errors', 0)}",
        f"- enviados 24h: {notif.get('manual_real_sent_24h', 0)}",
        f"- duplicados 24h: {notif.get('duplicates_24h', 0)}",
        "",
        "Dry-run:",
        f"- última execução: {notif.get('last_dry_run_at') or '-'}",
        f"- prévias último run: {notif.get('last_dry_run_previews', 0)}",
        f"- prévias 24h: {notif.get('dry_run_previews_24h', 0)}" + (" (histórico parcial)" if notif.get('dry_run_history_partial') else ""),
        f"- rejeições principais: {', '.join(notif.get('top_rejections') or []) or '-'}",
        "",
        "Checks:",
    ])
    for check in health.get("checks") or []:
        c_icon = "✅" if check.get("status") == "ok" else ("⚠️" if check.get("status") == "warning" else "❌")
        lines.append(f"{c_icon} {check.get('label')}: {check.get('detail')}")
    lines.extend([
        "",
        "Próximos comandos:",
        "- /admin auctions notify-run --source vip --limit-wishlists 5",
        "- /admin auctions preview-send",
        "- /admin auctions notify-run --source vip --limit-wishlists 5 --real",
    ])
    return "\n".join(lines)

def _render_admin_auction_matches(wishlist_query: str, matches: list) -> list[str]:
    lines = [f"🎯 Busca: {wishlist_query}"]
    for m in matches:
        src = "VIP" if m.source == "vip_auctions" else m.source
        lines.extend([
            f"⚠️ Leilão compatível — {src}",
            m.title or "(sem título)",
            f"Lance atual: {_fmt_money_br(m.current_bid)}" if m.current_bid is not None else "Lance atual: -",
            f"Score: {m.score}",
            "Razões:",
        ])
        for r in (m.reasons or []):
            lines.append(f"- {r}")
        lines.append("")
    lines.append("Atenção: leilão exige edital, taxas e vistoria.")
    return lines


async def _admin_premium(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if len(args) < 1:
        await update.message.reply_text("Use: /admin premium activate <chat_id> <monthly|annual|30d|365d> | /admin premium status <chat_id>")
        return
    action = args[0].lower()
    if action == "activate":
        if len(args) != 3:
            await update.message.reply_text("Use: /admin premium activate <chat_id> <monthly|annual|30d|365d>")
            return
        try:
            chat_id = int(args[1])
        except Exception:
            await update.message.reply_text("Use: /admin premium activate <chat_id> <monthly|annual|30d|365d>")
            return
        period = args[2].lower()
        with SessionLocal() as db:
            user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
            if not user:
                await update.message.reply_text("Usuário não encontrado.")
                return
            result = activate_manual_premium(
                db,
                user_id=user.id,
                period=period,
                activated_by=str(update.effective_chat.id),
            )
            if not result.ok:
                await update.message.reply_text(result.error or "Falha ao ativar premium.")
                return
        valid_until = result.current_period_end.astimezone(timezone.utc).strftime("%d/%m/%Y")
        await update.message.reply_text(
            f"✅ Premium ativado. Usuário: {chat_id} Plano: Premium {result.period_label} Válido até: {valid_until}"
        )
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Seu Premium foi ativado. Válido até: {valid_until}. Use /plan para consultar seu plano.",
            )
        except Exception:
            logger.warning("admin_premium_user_notify_failed", extra={"chat_id": chat_id}, exc_info=True)
        return
    if action == "status":
        if len(args) != 2:
            await update.message.reply_text("Use: /admin premium status <chat_id>")
            return
        try:
            chat_id = int(args[1])
        except Exception:
            await update.message.reply_text("Use: /admin premium status <chat_id>")
            return
        with SessionLocal() as db:
            user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
            if not user:
                await update.message.reply_text("Usuário não encontrado.")
                return
            snap = get_user_plan_snapshot(db, user.id)
            end = snap.get("current_period_end")
            status = "vigente" if end and end > datetime.now(timezone.utc) else "sem validade ativa"
            end_txt = end.astimezone(timezone.utc).strftime("%d/%m/%Y") if end else "-"
            await update.message.reply_text(f"Usuário: {chat_id}\nPlano: {snap.get('plan_code')}\nVálido até: {end_txt}\nStatus: {status}")
        return
    await update.message.reply_text("Use: /admin premium activate <chat_id> <monthly|annual|30d|365d> | /admin premium status <chat_id>")

async def _admin_sources_dispatch(update: Update, raw_args: List[str]):
    return await _admin_sources_dispatch_impl(
        update,
        raw_args,
        admin_sources_fn=_admin_sources,
        admin_sources_show_fn=_admin_sources_show,
        admin_sources_set_simple_fn=_admin_sources_set_simple,
        admin_sources_reset_fn=_admin_sources_reset,
    )


async def _admin_sources_show(update: Update, source: str):
    return await _admin_sources_show_impl(update, source)


async def _admin_sources_set_simple(update: Update, source: str, field: str, value: str):
    return await _admin_sources_set_simple_impl(update, source, field, value)


async def _admin_sources_reset(update: Update, source: str):
    return await _admin_sources_reset_impl(update, source)


def _chunk_lines(text: str, max_len: int = 3600) -> List[str]:
    lines = (text or "").splitlines()
    out: List[str] = []
    buf: List[str] = []
    size = 0
    for ln in lines:
        add = len(ln) + 1
        if buf and (size + add > max_len):
            out.append("\n".join(buf))
            buf = []
            size = 0
        buf.append(ln)
        size += add
    if buf:
        out.append("\n".join(buf))
    return out


async def _admin_matchdebug(update: Update, raw_args: List[str]):
    """Debug de matching.

    Uso:
      /admin matchdebug <source> [N]
    """
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /admin matchdebug <source> [N]")
        return

    src = args[0].lower()
    try:
        n = int(args[1]) if len(args) > 1 else 8
        n = max(3, min(n, 20))
    except Exception:
        n = 8

    await update.message.reply_text(f"🔎 matchdebug iniciado… source={src} amostra={n}")

    def _run_sync() -> str:
        from app.services.wishlist_sources_service import allowed_sources_for_wishlists
        from app.services.matching_service import explain_match

        with SessionLocal() as db:
            wls = (
                db.query(Wishlist)
                .options(joinedload(Wishlist.filters))
                .filter(Wishlist.is_active == True)
                .all()
            )
            allowed = allowed_sources_for_wishlists(db, wls)
            eligible = [w for w in wls if src in (allowed.get(w.id) or set())]

            listings = (
                db.query(CarListing)
                .filter(CarListing.source == src)
                .order_by(CarListing.created_at.desc())
                .limit(n)
                .all()
            )

            lines: List[str] = []
            lines.append("🔎 AutoHunter — matchdebug (admin)")
            lines.append(f"UTC: {_fmt_dt(datetime.now(timezone.utc))}")
            lines.append(f"Source: {src}")
            lines.append(f"Wishlists elegíveis (ativas): {len(eligible)}")
            lines.append(f"Amostra de anúncios (DB): {len(listings)}")
            lines.append("")

            # Mostra alguns anúncios para validar se a extração está OK (título/ano/preço acabam impactando matching).
            empty_title = sum(1 for l in listings if not (l.title or '').strip())
            lines.append(f"Empty title na amostra: {empty_title}/{len(listings)}")
            lines.append("Anúncios (amostra):")
            for l in listings[: min(5, len(listings))]:
                t = (l.title or '').strip().replace("\n", " ")
                if len(t) > 110:
                    t = t[:110] + '…'
                loc = (l.location or '-').strip()
                lines.append(f"- {str(l.id)[:8]}: '{t}' | loc={loc}")
            lines.append("")


            if not eligible:
                lines.append("⚠️ Nenhuma wishlist ativa aceita essa source.")
                lines.append("Dica: se você tem filtros 'source eq', inclua também essa source.")
                return "\n".join(lines)

            if not listings:
                lines.append("⚠️ Não há anúncios dessa source no DB ainda.")
                lines.append("Dica: rode /admin runall " + src)
                return "\n".join(lines)

            lines.append("Wishlists (amostra):")
            for w in eligible[:5]:
                flt = [f"{f.field}{f.operator}{f.value}" for f in (getattr(w, "filters", []) or [])]
                lines.append(f"- {str(w.id)[:8]}: '{(w.query or '')}' filters={','.join(flt) if flt else '-'}")
            if len(eligible) > 5:
                lines.append(f"… +{len(eligible)-5} outras")
            lines.append("")

            reason_totals: dict[str,int] = {}
            matched_totals = 0
            for l in listings:
                for w in eligible:
                    r = explain_match(w, l)
                    reason_totals[r] = reason_totals.get(r, 0) + 1
                    if r == "ok":
                        matched_totals += 1

            items = sorted(reason_totals.items(), key=lambda kv: kv[1], reverse=True)
            lines.append(f"Matches na amostra (wishlist x listing): {matched_totals}")
            lines.append("Top motivos:")
            for (r, c) in items[:8]:
                lines.append(f"- {r}: {c}")

            lines.append("")
            lines.append("Leitura rápida:")
            lines.append("- text_terms: query tem termos que não existem no título/location (ex: 'a partir', anos).")
            lines.append("- filter_price_missing: source não traz preço e você tem filtro de preço.")
            lines.append("- filter_year_*: ano não está sendo extraído (título/URL) ou filtro está restrito.")
            return "\n".join(lines)

    try:
        text = await asyncio.to_thread(_run_sync)
    except Exception as e:
        text = f"Erro no matchdebug: {_short(str(e), 240)}"
    await update.message.reply_text(sanitize_for_telegram(text))

async def _admin_requeue(update: Update, raw_args: List[str]):
    """Reprocessa matching em anúncios já existentes e re-enfileira notifications ausentes.

    Uso:
      /admin requeue <source> [hours=24] [limit=200]
    """
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if not args:
        await update.message.reply_text("Use: /admin requeue <source> [hours=24] [limit=200]")
        return

    src = args[0].lower()
    try:
        hours = int(args[1]) if len(args) > 1 else 24
        hours = max(1, min(hours, 168))
    except Exception:
        hours = 24

    try:
        limit = int(args[2]) if len(args) > 2 else 200
        limit = max(20, min(limit, 500))
    except Exception:
        limit = 200

    await update.message.reply_text(f"🧪 requeue iniciado… source={src} hours={hours} limit={limit}")

    def _run_sync() -> str:
        from datetime import timedelta
        from app.services.wishlist_sources_service import allowed_sources_for_wishlists
        from app.services.matching_service import match_listings_for_wishlists
        from app.services.notifications_queue_service import queue_notifications_for_matches

        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

            wls = (
                db.query(Wishlist)
                .options(joinedload(Wishlist.filters))
                .filter(Wishlist.is_active == True)
                .all()
            )
            allowed = allowed_sources_for_wishlists(db, wls)
            eligible = [w for w in wls if src in (allowed.get(w.id) or set())]

            listings = (
                db.query(CarListing)
                .filter(CarListing.source == src)
                .filter(CarListing.created_at >= cutoff)
                .order_by(CarListing.created_at.desc())
                .limit(limit)
                .all()
            )

            lines: List[str] = []
            lines.append("🧪 AutoHunter — requeue (admin)")
            lines.append(f"UTC: {_fmt_dt(datetime.now(timezone.utc))}")
            lines.append(f"Source: {src}")
            lines.append(f"Cutoff: {_fmt_dt(cutoff)} (últimas {hours}h)")
            lines.append(f"Wishlists elegíveis: {len(eligible)}")
            lines.append(f"Listings no DB: {len(listings)}")
            lines.append("")

            if not eligible:
                lines.append("⚠️ Nenhuma wishlist ativa aceita essa source.")
                return "\n".join(lines)
            if not listings:
                lines.append("⚠️ Nenhum listing no DB nessa janela.")
                return "\n".join(lines)

            matches_by = match_listings_for_wishlists(eligible, listings)

            total_matched = 0
            total_queued = 0
            for w in eligible:
                matched_listings = matches_by.get(w.id) or []
                m = len(matched_listings)
                total_matched += m
                if m:
                    total_queued += int(queue_notifications_for_matches(db, w, matched_listings) or 0)

            db.commit()
            lines.append(f"Matched (wishlist x listing): {total_matched}")
            lines.append(f"Queued (novas notifications): {total_queued}")
            lines.append("")
            lines.append("Obs: isso não 'reenvia' duplicado (dedupe por wishlist+listing).")
            lines.append("Se queued > 0 e você não recebe, verifique o sender/scheduler.")
            return "\n".join(lines)

    try:
        text = await asyncio.to_thread(_run_sync)
    except Exception as e:
        text = f"Erro no requeue: {_short(str(e), 240)}"
    await update.message.reply_text(sanitize_for_telegram(text))

async def _admin_runall(update: Update, raw_args: List[str]):
    """Força execução de sources habilitadas (admin-only) e devolve resumo no chat."""
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    wanted = [a.strip().lower() for a in (raw_args or []) if a.strip()]

    await update.message.reply_text("🚀 runall iniciado… (forçando execução)")

    def _run_sync() -> str:
        plugins = list_sources()
        with SessionLocal() as db:
            ensure_source_configs(db)
            cfgs = {c.source: c for c in db.query(SourceConfig).all()}

            lines: List[str] = []
            lines.append("🧯 AutoHunter — runall (admin)")
            lines.append(f"UTC: {_fmt_dt(datetime.now(timezone.utc))}")
            if wanted:
                lines.append("Sources: " + ", ".join(wanted))
            lines.append("")

            ran = 0
            for p in plugins:
                src = p.name
                if wanted and src not in wanted:
                    continue

                cfg = cfgs.get(src)
                if cfg is not None and not bool(cfg.is_enabled):
                    lines.append(f"- {src}: 🚫 disabled")
                    continue

                if p.scrape is None:
                    lines.append(f"- {src}: ⚪ skipped (not_implemented)")
                    continue

                res = run_source_for_all_wishlists(
                    db,
                    src,
                    kind="admin",
                    force=True,
                    ignore_backoff=True,
                )
                ran += 1
                st = res.get("status")

                if st == "success":
                    lines.append(
                        f"- {src}: ✅ success found={res.get('found')} ins={res.get('inserted')} "
                        f"match={res.get('matched')} queued={res.get('queued')} dur={res.get('duration_ms')}ms"
                    )
                    for extra in _render_run_summary_lines(res.get("run_summary")):
                        lines.append(f"  {extra}")
                elif st == "blocked":
                    lines.append(
                        f"- {src}: 🟠 blocked http={res.get('http_status')} backoff={res.get('backoff_minutes')}m dur={res.get('duration_ms')}ms"
                    )
                    for extra in _render_webmotors_blocked_diag_lines(res.get("payload")):
                        lines.append(f"  {extra}")
                elif st == "error":
                    lines.append(
                        f"- {src}: ⚪ error backoff={res.get('backoff_minutes')}m dur={res.get('duration_ms')}ms err={_short(str(res.get('error')), 160)}"
                    )
                elif st == "no_work":
                    lines.append(f"- {src}: ⚪ no_work eligible={res.get('eligible_wishlists')}")
                elif st == "not_due":
                    lines.append(f"- {src}: ⚪ not_due")
                elif st == "backoff":
                    lines.append(f"- {src}: ⏳ backoff until={_fmt_dt(res.get('next_allowed_at'))}")
                elif st == "skipped":
                    lines.append(f"- {src}: ⚪ skipped reason={res.get('reason')}")
                elif st == "disabled":
                    lines.append(f"- {src}: 🚫 disabled")
                else:
                    lines.append(f"- {src}: ⚪ {st}")

            if ran == 0:
                lines.append("(nenhuma fonte executada)")

            return "\n".join(lines)

    text = await asyncio.to_thread(_run_sync)
    safe = sanitize_for_telegram(text)
    for chunk in _chunk_lines(safe, max_len=3600):
        await update.message.reply_text(chunk)


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
    lines.append(f"health status={status} found={found} inserted={inserted} matched={matched} queued={queued}")

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


async def _reply_chunked(update: Update, text: str, max_len: int = 3600):
    # Telegram costuma falhar acima de ~4096; 3600 é safe.
    chunks = _chunk_lines(text, max_len=max_len)
    for ch in chunks:
        await update.message.reply_text(sanitize_for_telegram(ch))



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

                if avg_ms is not None:
                    sum_dur += float(avg_ms) * cnt
                    sum_cnt_dur += cnt
                if avg_f is not None:
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

        st = states.get(p.name)
        op_class = classify_source_operational_role(p, cfg=cfg, state=st)
        lr = last_runs.get(p.name)
        le = last_effective.get(p.name)
        a = aggs.get(p.name, _Agg24h())

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

        ok_pct = int(round((a.success / a.total) * 100)) if a.total else 0
        snap = f"24h ok={a.success}/{a.total} ({ok_pct}%) err={a.error} blk={a.blocked} skip={a.skipped}"
        expected_24h = int((24 * 60) / sched_m) if sched_m and sched_m > 0 else None
        if expected_24h:
            cov_pct = int(round((a.total / expected_24h) * 100)) if expected_24h else 0
            snap += f" runs={a.total}/{expected_24h} ({cov_pct}%)"
        if a.avg_duration_ms is not None:
            snap += f" avg={a.avg_duration_ms}ms"

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
        lines.append(f"   {snap}")

        if verbose and lr_cause is not None and getattr(lr_cause, "payload", None):
            try:
                payload = _payload_as_dict(getattr(lr_cause, "payload", None))
                d = payload.get("diag") if payload else None
                if d:
                    lines.append(f"   diag: {_fmt_diag(d)}")
            except Exception:
                pass

        backoff_active = bool(enabled and st and st.next_allowed_at and st.next_allowed_at > now)
        if kind != "OK" or backoff_active:
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
        return await _admin_sources_set_simple(update, mapped, "is_enabled", "true" if action == "enable" else "false")
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
        return await _admin_auctions(update, ["source-config", mapped, "categories", *args[2:]])
    await update.message.reply_text("Ação inválida para /admin source.")


async def _admin_health(update: Update, raw_args: Optional[List[str]] = None):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return

    now = datetime.now(timezone.utc)
    verbose = any((a or "").strip().lower() in {"-v", "verbose", "--verbose", "full"} for a in (raw_args or []))
    lines: List[str] = []
    lines.append("🧰 Admin — Health")
    lines.append(f"Agora (UTC): {_fmt_dt(now)}")
    lines.append("")

    # Best-effort system info (psutil is optional)
    try:
        import psutil  # type: ignore

        cpu = psutil.cpu_percent(interval=0.2)
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        lines.append(f"CPU: {cpu}%")
        lines.append(
            f"RAM: {int(vm.percent)}% ({int(vm.used/1024/1024)}MB/{int(vm.total/1024/1024)}MB)"
        )
        lines.append(
            f"Disk: {int(disk.percent)}% ({int(disk.used/1024/1024)}MB/{int(disk.total/1024/1024)}MB)"
        )
    except Exception:
        lines.append("CPU/RAM/Disk: psutil not installed")

    lines.append("")
    lines.append(f"Playwright enabled: {settings.enable_playwright}")
    lines.append(f"Playwright headless: {settings.playwright_headless}")
    lines.append(f"Scheduler workers: {settings.scheduler_workers}")

    # Internal pools
    try:
        from app.services.playwright_pool import get_playwright_pool

        pool = get_playwright_pool()
        st = pool.stats()
        lines.append(
            f"Playwright pool: browsers={st.get('browsers')} contexts={st.get('contexts')} "
            f"queue={st.get('queue_size')}/{st.get('queue_max')} pending={st.get('pending_inflight')}"
        )
        lines.append(
            f"PW dedupe/cache: joins={st.get('dedupe_joins')} cache_hits={st.get('cache_hits')} "
            f"queue_full={st.get('queue_full_rejects')}"
        )
        lines.append(
            f"PW perf: avg_exec={st.get('avg_exec_ms')}ms avg_wait={st.get('avg_wait_ms')}ms last={st.get('last_job')}"
        )
    except Exception:
        pass

    try:
        from app.scrapers.base import get_session_stats

        sst = get_session_stats()
        lines.append(f"Requests sessions: {sst.get('sessions')}")
    except Exception:
        pass

    # Runtime + DB snapshots
    with SessionLocal() as db:
        hb = (
            db.query(SystemLog)
            .filter(SystemLog.component == "scheduler")
            .filter(SystemLog.message == "heartbeat")
            .order_by(SystemLog.created_at.desc())
            .first()
        )
        hb_at = _as_utc(getattr(hb, "created_at", None))
        hb_age_min = int((now - hb_at).total_seconds() // 60) if hb_at else None
        hb_stale = heartbeat_is_stale(
            now,
            hb_at,
            stale_after_minutes=int(getattr(settings, "scheduler_heartbeat_stale_minutes", 15) or 15),
        )
        lines.append("")
        lines.append(
            "Scheduler heartbeat: "
            + (f"{_fmt_dt(hb_at)} age={hb_age_min}m" if hb_at else "-")
            + (" ⚠️stale" if hb_stale else "")
        )

        last_global = db.query(SourceRun).order_by(SourceRun.created_at.desc()).first()
        if last_global:
            lg_at = _as_utc(last_global.created_at)
            age_m = int((now - lg_at).total_seconds() // 60) if lg_at else 0
            lines.append(f"Última execução global: {_fmt_dt(lg_at)} age={age_m}m")
        else:
            lines.append("Última execução global: -")

        plugins = {p.name: p for p in list_sources()}
        rows = db.query(SourceState).all()
        paused = [r for r in rows if _as_utc(r.next_allowed_at) and _as_utc(r.next_allowed_at) > now]
        if paused:
            lines.append("")
            lines.append("Sources paused (backoff/throttle):")
            for r in sorted(paused, key=lambda x: x.source):
                extra_hint = ""
                plugin = plugins.get(r.source)
                hint = source_operational_hint(plugin, state=r) if plugin is not None else None
                if hint:
                    extra_hint = f" note={hint}"
                next_allowed = _as_utc(r.next_allowed_at)
                lines.append(
                    f"- {r.source}: until {_fmt_dt(next_allowed)} status={r.last_status or '-'}{extra_hint}"
                )

        # per-source latest run (compact, stale-first)
        all_sources = sorted(plugins.keys())
        cfg_by_source: Dict[str, SourceConfig] = {
            c.source: c for c in db.query(SourceConfig).filter(SourceConfig.source.in_(all_sources)).all()
        }
        state_by_source: Dict[str, SourceState] = {
            s.source: s for s in db.query(SourceState).filter(SourceState.source.in_(all_sources)).all()
        }
        latest_rows = (
            db.query(SourceRun)
            .order_by(SourceRun.source.asc(), SourceRun.created_at.desc())
            .all()
        )
        latest_by_source: Dict[str, SourceRun] = {}
        for r in latest_rows:
            if r.source not in latest_by_source:
                latest_by_source[r.source] = r
            if len(latest_by_source) >= len(all_sources):
                break
        stale_lines: list[str] = []
        ok_lines: list[str] = []
        disabled_lines: list[str] = []
        aux_lines: list[str] = []
        for src in all_sources:
            plugin = plugins.get(src)
            lr = latest_by_source.get(src)
            cfg = cfg_by_source.get(src)
            state = state_by_source.get(src)
            sched_m = int((cfg.sched_minutes if cfg else 0) or 0)
            is_enabled = bool(cfg.is_enabled) if cfg else bool(getattr(plugin, "default_enabled", True))
            supports_wishlist = bool(getattr(plugin, "supports_wishlist_monitoring", True))
            is_implemented = bool(getattr(plugin, "scrape", None))
            op_class = classify_source_operational_role(plugin, cfg=cfg, state=state)
            state_next_allowed = _as_utc(getattr(state, "next_allowed_at", None))
            paused = bool(state and state_next_allowed and state_next_allowed > now)
            paused_mins = _mins_left(state_next_allowed, now)
            lr_at = _as_utc(lr.created_at) if lr else None
            stale_eval = evaluate_source_staleness(
                now=now,
                last_run_at=lr_at,
                sched_minutes=sched_m,
                factor=float(getattr(settings, "source_stale_factor", 2.0) or 2.0),
                min_global_minutes=int(getattr(settings, "source_stale_min_minutes", 180) or 180),
            )
            if not is_enabled:
                if verbose:
                    disabled_lines.append(f"- {src}: disabled")
                continue
            if op_class.role == "auxiliary" or not supports_wishlist:
                if verbose:
                    aux_lines.append(f"- {src}: auxiliary/feed source (sem wishlist monitoring)")
                continue
            if op_class.role == "not_implemented" or not is_implemented:
                if verbose:
                    aux_lines.append(f"- {src}: not_implemented")
                continue
            if not should_include_in_critical_stale(plugin, cfg):
                if verbose:
                    aux_lines.append(f"- {src}: role={op_class.role}")
                continue
            if stale_eval.stale:
                if paused:
                    reason = "blocked/backoff"
                    hint = source_operational_hint(plugin, state=state)
                    if hint:
                        reason = f"{hint}; monitorar ou manter despriorizada"
                    stale_lines.append(
                        f"- {src}: stale age={stale_eval.age_minutes}m thr={stale_eval.threshold_minutes}m "
                        f"(paused {paused_mins}m, {reason})"
                    )
                else:
                    stale_lines.append(f"- {src}: stale age={stale_eval.age_minutes}m thr={stale_eval.threshold_minutes}m")
            elif verbose and lr:
                age = int((now - _as_utc(lr.created_at)).total_seconds() // 60)
                ok_lines.append(f"- {src}: {lr.status} age={age}m")
        if stale_lines:
            lines.append("")
            lines.append("Sources stale:")
            lines.extend(stale_lines[:12])
        elif verbose and ok_lines:
            lines.append("")
            lines.append("Sources recentes:")
            lines.extend(ok_lines[:12])
        if verbose and disabled_lines:
            lines.append("")
            lines.append("Sources disabled:")
            lines.extend(disabled_lines[:20])
        if verbose and aux_lines:
            lines.append("")
            lines.append("Sources auxiliary/not_implemented:")
            lines.extend(aux_lines[:20])

        # Scrape queue and stuck runners
        job_counts = (
            db.query(ScrapeJob.queue, ScrapeJob.status, func.count(ScrapeJob.id))
            .group_by(ScrapeJob.queue, ScrapeJob.status)
            .all()
        )
        if job_counts:
            lines.append("")
            lines.append("scrape_jobs:")
            byq: Dict[str, Dict[str, int]] = {}
            for q, st, c in job_counts:
                byq.setdefault(str(q), {})[str(st)] = int(c or 0)
            for q in sorted(byq.keys()):
                st = byq[q]
                lines.append(f"- {q}: queued={st.get('queued',0)} running={st.get('running',0)} done={st.get('done',0)} failed={st.get('failed',0)}")
        stuck_cut = now - timedelta(minutes=int(getattr(settings, "scrape_job_stuck_minutes", 30) or 30))
        stuck_running = (
            db.query(func.count(ScrapeJob.id))
            .filter(ScrapeJob.status == "running")
            .filter(ScrapeJob.started_at.is_not(None))
            .filter(ScrapeJob.started_at < stuck_cut)
            .scalar()
            or 0
        )
        if stuck_running:
            lines.append(f"⚠️ running travados: {int(stuck_running)} (>30m)")

        # Notifications / sender health
        notif_counts = db.query(Notification.status, func.count(Notification.id)).group_by(Notification.status).all()
        if notif_counts:
            lines.append("")
            lines.append("notifications:")
            lines.append(
                "- "
                + " ".join([f"{str(st)}={int(c)}" for st, c in sorted(notif_counts, key=lambda x: str(x[0]))])
            )
        sender_stall_cut = now - timedelta(minutes=int(getattr(settings, "sender_stall_minutes", 20) or 20))
        queued_old = (
            db.query(func.count(Notification.id))
            .filter(Notification.status == "queued")
            .filter(Notification.created_at < sender_stall_cut)
            .scalar()
            or 0
        )
        if queued_old:
            lines.append(f"⚠️ sender possivelmente parado: queued_old={int(queued_old)} (>20m)")

        cache_stats = get_wishlist_summaries_cache_stats()
        lines.append("")
        if cache_stats.get("cache_enabled"):
            lines.append(
                "Wishlist summaries cache: on "
                f"size={cache_stats.get('size')} hits={cache_stats.get('hits')} misses={cache_stats.get('misses')} "
                f"hit={cache_stats.get('hit_rate_pct')}% invalid={cache_stats.get('invalidations')} "
                f"global_invalid={cache_stats.get('global_invalidations')} prune={cache_stats.get('prunes')} "
                f"evict={cache_stats.get('evictions')} ttl={cache_stats.get('ttl_seconds')}s max={cache_stats.get('max_entries')}"
            )
        else:
            lines.append(f"Wishlist summaries cache: off ttl={cache_stats.get('ttl_seconds')}s")

        # Last failures by source
        fail_rows = (
            db.query(SourceRun.source, SourceRun.status, SourceRun.created_at, SourceRun.error)
            .filter(SourceRun.status.in_(["error", "blocked"]))
            .order_by(SourceRun.created_at.desc())
            .limit(8)
            .all()
        )
        if fail_rows:
            lines.append("")
            lines.append("Últimas falhas:")
            for src, st, dt, err in fail_rows:
                lines.append(f"- {src} {st} at={_fmt_dt(dt)} err={_short(err, 90)}")

    text = "\n".join(lines)
    await _reply_chunked(update, sanitize_for_telegram(text))



async def _admin_users(update: Update, raw_args: List[str]):
    # Lista usuários (paginado) para operação remota via Telegram.
    #
    # Use:
    #   /admin users
    #   /admin users 2
    #   /admin users civic
    #   /admin users 2 civic

    page = 1
    term: Optional[str] = None

    if raw_args:
        if raw_args[0].isdigit():
            page = max(1, int(raw_args[0]))
            term = " ".join(raw_args[1:]).strip() or None
        else:
            term = " ".join(raw_args).strip() or None

    if term:
        term = term.strip()
        if term.startswith("@"):  # permite /admin users @marcelo
            term = term[1:]
        if not term:
            term = None

    per_page = 10
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        q = db.query(User)
        if term:
            like = f"%{term}%"
            q = q.filter(
                or_(
                    User.username.ilike(like),
                    cast(User.telegram_chat_id, Text).ilike(like),
                    cast(User.id, Text).ilike(like),
                )
            )

        total = q.count()
        pages = max(1, (total + per_page - 1) // per_page)
        if page > pages:
            page = pages

        users = (
            q.order_by(User.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # wishlist counts (total/active)
        uids = [u.id for u in users]
        wl_counts: Dict[Any, tuple[int, int]] = {}
        if uids:
            wl_rows = (
                db.query(
                    Wishlist.user_id,
                    func.count(Wishlist.id),
                    func.sum(case((Wishlist.is_active == True, 1), else_=0)),
                )
                .filter(Wishlist.user_id.in_(uids))
                .group_by(Wishlist.user_id)
                .all()
            )
            for uid, wl_total, wl_active in wl_rows:
                wl_counts[uid] = (int(wl_total or 0), int(wl_active or 0))

        # subscription snapshot per account (latest by starts_at)
        acc_ids = [u.account_id for u in users if u.account_id]
        sub_map: Dict[Any, Dict[str, Any]] = {}
        if acc_ids:
            sub_rows = (
                db.query(
                    Subscription.account_id,
                    Subscription.status,
                    Subscription.daily_alert_limit_override,
                    Subscription.starts_at,
                    Subscription.ends_at,
                    Plan.code,
                )
                .join(Plan, Subscription.plan_id == Plan.id)
                .filter(Subscription.account_id.in_(acc_ids))
                .order_by(Subscription.account_id.asc(), Subscription.starts_at.desc())
                .all()
            )
            for aid, status, override, starts_at, ends_at, plan_code in sub_rows:
                if aid not in sub_map:
                    sub_map[aid] = {
                        "status": status,
                        "override": override,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "plan_code": plan_code,
                    }

    out: List[str] = []
    out.append("👥 Admin — Users")

    header = f"total={total} | page={page}/{pages} | per_page={per_page}"
    if term:
        header += f" | filter={term}"
    out.append(header)
    out.append("")

    if not users:
        out.append("Nenhum usuário encontrado.")
    else:
        start_index = (page - 1) * per_page + 1
        for i, u in enumerate(users, start=start_index):
            uname = f"@{u.username}" if u.username else "-"
            active = "✅" if u.is_active else "🚫"

            wl_total, wl_active = wl_counts.get(u.id, (0, 0))

            sub = sub_map.get(u.account_id) if u.account_id else None
            raw_plan = (sub.get("plan_code") if sub else None) or (u.plan or "free")
            plan = normalize_plan_code(raw_plan)

            override = None
            if sub and sub.get("override") is not None:
                override = sub.get("override")
            elif u.daily_limit_override is not None:
                override = u.daily_limit_override

            limit_txt = str(override) if override is not None else "-"
            acc_txt = "acc✅" if u.account_id else "acc—"
            sub_status = (sub.get("status") if sub else None) or "-"

            out.append(
                f"{i}. {active} {uname} | chat={u.telegram_chat_id} | {acc_txt} | wl={wl_active}/{wl_total} | plan={plan} ({sub_status}) | limit={limit_txt}"
            )

    out.append("")
    out.append("Dica: /setplan <free|premium> <chat_id>  |  /setlimit <n|none> <chat_id>")

    msg = sanitize_for_telegram("\n".join(out))
    if len(msg) > 3800:
        msg = msg[:3797] + "..."
    await update.effective_message.reply_text(msg)


async def _admin_errors(update: Update, raw_args: List[str]):
    # Digest de problemas: system_logs + source_runs + notifications failed
    limit = int(getattr(settings, "admin_errors_digest_limit", 10) or 10)
    if raw_args and raw_args[0].isdigit():
        limit = int(raw_args[0])
    limit = max(1, min(30, limit))

    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        logs = (
            db.query(SystemLog)
            .filter(SystemLog.level.in_(["warn", "error"]))
            .order_by(SystemLog.created_at.desc())
            .limit(limit)
            .all()
        )

        runs = (
            db.query(SourceRun)
            .filter(SourceRun.status.in_(["blocked", "error"]))
            .order_by(SourceRun.created_at.desc())
            .limit(limit)
            .all()
        )

        notif_rows = (
            db.query(Notification, User, Wishlist)
            .join(User, Notification.user_id == User.id)
            .outerjoin(Wishlist, Notification.wishlist_id == Wishlist.id)
            .filter(Notification.status == "failed")
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .all()
        )

    # 1) System logs
    out1: List[str] = []
    out1.append("🧯 Admin — Errors")
    out1.append(f"Agora (UTC): {_fmt_dt(now)}")
    out1.append(f"Limite por seção: {limit}")
    out1.append("")
    out1.append("1) System logs (warn/error)")

    if not logs:
        out1.append("- (sem registros)")
    else:
        for row in logs:
            out1.append(
                f"- {_fmt_dt(row.created_at)} [{row.level}] {row.component}: {_short(row.message, 220)}"
            )

    msg1 = sanitize_for_telegram("\n".join(out1))
    if len(msg1) > 3800:
        msg1 = msg1[:3797] + "..."
    await update.effective_message.reply_text(msg1)

    # 2) Source runs
    out2: List[str] = []
    out2.append("2) Source runs (blocked/error)")
    if not runs:
        out2.append("- (sem registros)")
    else:
        for r in runs:
            err = _short(r.error, 220)
            out2.append(
                f"- {_fmt_dt(r.created_at)} {r.source}: {r.status.upper()} http={r.http_status or '-'} dur={r.duration_ms or '-'}ms found={r.items_found or '-'} match={r.items_matched or '-'} | {err}"
            )

    msg2 = sanitize_for_telegram("\n".join(out2))
    if len(msg2) > 3800:
        msg2 = msg2[:3797] + "..."
    await update.effective_message.reply_text(msg2)

    # 3) Notifications failed
    out3: List[str] = []
    out3.append("3) Notifications failed")
    if not notif_rows:
        out3.append("- (sem registros)")
    else:
        for n, u, w in notif_rows:
            uname = f"@{u.username}" if u.username else "-"
            q = (w.query if w else None) or "-"
            reason = n.reason or "-"
            err = _short(n.error_message, 220)
            out3.append(
                f"- {_fmt_dt(n.created_at)} user={uname} chat={u.telegram_chat_id} reason={reason} wl={_short(q, 120)} | {err}"
            )

    msg3 = sanitize_for_telegram("\n".join(out3))
    if len(msg3) > 3800:
        msg3 = msg3[:3797] + "..."
    await update.effective_message.reply_text(msg3)

async def _admin_reindex_wishlists(update: Update, args: List[str]):
    """Rebuild wishlist token index for scalable matching.
    Usage:
      /admin reindex_wishlists
    """
    await update.effective_message.reply_text("🧩 reindex iniciado… (wishlists ativas)")
    with SessionLocal() as db:
        res = reindex_active_wishlists(db)
    await update.effective_message.reply_text(
        sanitize_for_telegram(
            "\n".join(
                [
                    "🧩 AutoHunter — reindex_wishlists (admin)",
                    f"UTC: {_fmt_dt(datetime.now(timezone.utc))}",
                    f"wishlists_processadas={res.wishlists_processed}",
                    f"tokens_inseridos={res.tokens_inserted}",
                ]
            )
        )
    )

async def _admin_fb_sessions(update: Update):
    db = SessionLocal()
    try:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        by_status = db.query(FBSession.status, func.count(FBSession.id)).group_by(FBSession.status).all()
        by_error = (
            db.query(FBSession.last_error_kind, func.count(FBSession.id))
            .filter(FBSession.last_error_kind.is_not(None))
            .group_by(FBSession.last_error_kind)
            .order_by(func.count(FBSession.id).desc())
            .limit(5)
            .all()
        )
        stale_active = (
            db.query(func.count(FBSession.id))
            .filter(FBSession.status == "ACTIVE")
            .filter(FBSession.last_ok_at.is_not(None))
            .filter(FBSession.last_ok_at < stale_cutoff)
            .scalar()
            or 0
        )
        recurring_errors = (
            db.query(FBSession.user_id, func.count(FBSession.id))
            .filter(FBSession.last_error_kind.is_not(None))
            .group_by(FBSession.user_id)
            .order_by(func.count(FBSession.id).desc())
            .limit(5)
            .all()
        )

        status_text = ", ".join([f"{s}:{c}" for s, c in by_status]) if by_status else "-"
        error_text = ", ".join([f"{(e or 'NONE')}:{c}" for e, c in by_error]) if by_error else "-"
        recurring_text = ", ".join([f"{u}:{c}" for u, c in recurring_errors]) if recurring_errors else "-"

        message = (
            "FB sessions\n"
            f"by_status: {status_text}\n"
            f"top_errors: {error_text}\n"
            f"stale_active(>7d): {stale_active}\n"
            f"top_recurring_error_users: {recurring_text}\n"
            "Acao recomendada: pedir /fb connect para EXPIRED/CHALLENGE/BLOCKED."
        )
        await update.message.reply_text(message)
    finally:
        db.close()


async def _admin_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list[str]):
    return await _admin_deploy_impl(update, args, fmt_dt=_fmt_dt)

async def _admin_audit(update: Update, raw_args: Optional[List[str]] = None):
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        await update.message.reply_text("Sem permissão.")
        return
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        hb = db.query(SystemLog).filter(SystemLog.component == "scheduler", SystemLog.message == "heartbeat").order_by(SystemLog.created_at.desc()).first()
        hb_dt = _as_utc(getattr(hb, "created_at", None))
        hb_age = int((now - hb_dt).total_seconds() // 60) if hb_dt else None
        last_run = db.query(SourceRun).order_by(SourceRun.created_at.desc()).first()
        run_dt = _as_utc(getattr(last_run, "created_at", None))
        run_age = int((now - run_dt).total_seconds() // 60) if run_dt else None
        q = {(a, b): c for a, b, c in db.query(ScrapeJob.queue, ScrapeJob.status, func.count(ScrapeJob.id)).group_by(ScrapeJob.queue, ScrapeJob.status).all()}
        n = {a: b for a, b in db.query(Notification.status, func.count(Notification.id)).group_by(Notification.status).all()}
        sent24 = db.query(func.count(Notification.id)).filter(Notification.status == "sent", Notification.sent_at >= now - timedelta(hours=24)).scalar() or 0
        alerts_preview = collect_operational_alerts(db, now=now, consume_cooldown=False)
        source_attention = [a for a in alerts_preview if a.key.startswith(("source_stale:", "source_backoff:", "source_error:"))]
        attention_lines = [f"- {a.key}: {a.message}" for a in source_attention[:5]]
        if not attention_lines:
            attention_lines = ["- Sources com atenção: nenhuma"]

        queued_total = q.get(("http", "queued"), 0) + q.get(("browser", "queued"), 0)
        running_old_total = (
            db.query(func.count(ScrapeJob.id))
            .filter(ScrapeJob.status == "running", ScrapeJob.started_at < now - timedelta(minutes=45))
            .scalar()
            or 0
        )
        notif_old = (
            db.query(func.count(Notification.id))
            .filter(Notification.status.in_(["queued", "processing"]), Notification.created_at < now - timedelta(minutes=45))
            .scalar()
            or 0
        )
        critical = (hb_age is None or hb_age > 180) or (run_age is not None and run_age > 180) or running_old_total > 0
        warning = bool(source_attention) or queued_total > 0 or notif_old > 0
        status_geral = "CRÍTICO" if critical else ("ATENÇÃO" if warning else "OK")

        lines = ["🧭 Admin — Audit", f"UTC: {now.strftime('%Y-%m-%d %H:%M:%SZ')}", f"Status geral: {status_geral}", "", "Scheduler:", f"heartbeat age={hb_age if hb_age is not None else '-'}m", f"última execução global age={run_age if run_age is not None else '-'}m", "", "Filas:", f"http queued={q.get(('http','queued'),0)} running={q.get(('http','running'),0)} failed={q.get(('http','failed'),0)}", f"browser queued={q.get(('browser','queued'),0)} running={q.get(('browser','running'),0)} failed={q.get(('browser','failed'),0)}", "", "Notifications:", f"queued={n.get('queued',0)} processing={n.get('processing',0)} sent_24h={sent24} failed_24h={n.get('failed',0)}", "", "Sources com atenção:"]
        lines.extend(attention_lines)
        lines.extend(["", "Próximo passo:", "Use /admin health para detalhes ou /admin sources para visão por source."])
        await _reply_chunked(update, sanitize_for_telegram("\n".join(lines)[:3800]))
logger = logging.getLogger(__name__)
