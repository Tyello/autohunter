from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any

from sqlalchemy import func
from telegram import Update

from app.bot.admin import is_admin
from app.bot.admin_helpers import as_utc as _as_utc, fmt_dt as _fmt_dt, short as _short
from app.bot.text_sanitize import sanitize_for_telegram
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.notification import Notification
from app.models.scrape_job import ScrapeJob
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.models.system_log import SystemLog
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.operational_alerts_service import collect_operational_alerts
from app.services.source_operational_policy import (
    classify_source_operational_role,
    should_include_in_critical_stale,
    source_operational_hint,
)
from app.services.source_staleness_service import evaluate_source_staleness, heartbeat_is_stale
from app.services.wishlists_service import get_wishlist_summaries_cache_stats
from app.sources.registry import list_sources


def _mins_left(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if not dt:
        return None
    return int(max(0, (dt - now).total_seconds()) // 60)


async def _reply_chunked(update: Update, text: str, max_len: int = 3600):
    msg = update.effective_message
    parts = [text[i:i+max_len] for i in range(0, len(text), max_len)]
    for p in parts or [text]:
        await msg.reply_text(p)


async def admin_health(update: Update, raw_args: Optional[List[str]] = None):
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


async def admin_errors(update: Update, raw_args: List[str]):
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

async def admin_audit(update: Update, raw_args: Optional[List[str]] = None):
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
