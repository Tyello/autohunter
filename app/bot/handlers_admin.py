from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import func
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.admin import is_admin
from app.bot.text_sanitize import sanitize_for_telegram
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.sources.registry import list_sources


@dataclass
class _Agg24h:
    total: int = 0
    success: int = 0
    blocked: int = 0
    error: int = 0
    skipped: int = 0
    avg_duration_ms: Optional[int] = None
    avg_found: Optional[int] = None


def _fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "-"
    # keep it explicit and stable
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


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
        await update.message.reply_text("Use: /admin sources | /admin health")
        return

    action = args[0].lower()
    if action == "sources":
        await _admin_sources(update)
        return
    if action == "health":
        await _admin_health(update)
        return

    await update.message.reply_text("Ação inválida. Use: /admin sources | /admin health")


async def _admin_sources(update: Update):
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    plugins = list_sources()
    if not plugins:
        await update.message.reply_text("Nenhuma fonte registrada.")
        return

    with SessionLocal() as db:
        states = {s.source: s for s in db.query(SourceState).all()}

        # last run per source
        last_runs = {}
        for src in {p.name for p in plugins}:
            lr = (
                db.query(SourceRun)
                .filter(SourceRun.source == src)
                .order_by(SourceRun.created_at.desc())
                .first()
            )
            last_runs[src] = lr

        # 24h aggregates per source
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
            avg_dur: Optional[float] = None
            avg_found: Optional[float] = None

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

                # keep the last non-null averages we see (per status), then compute a simple overall
                if avg_ms is not None:
                    avg_dur = float(avg_ms)
                if avg_f is not None:
                    avg_found = float(avg_f)

            a.avg_duration_ms = int(avg_dur) if avg_dur is not None else None
            a.avg_found = int(avg_found) if avg_found is not None else None

            aggs[src] = a

    lines: List[str] = []
    lines.append("🧰 Admin — Sources")
    lines.append(f"Agora (UTC): {_fmt_dt(now)}")
    lines.append(f"Janela: últimas 24h desde {_fmt_dt(since)}")
    lines.append("")

    for i, p in enumerate(plugins, start=1):
        enabled = _get_bool_setting(p.enabled_setting, True)
        sched_m = _get_int_setting(p.sched_minutes_setting)
        cooldown_m = _get_int_setting(p.cooldown_minutes_setting, 0) or 0
        implemented = p.scrape is not None

        st = states.get(p.name)
        lr = last_runs.get(p.name)
        a = aggs.get(p.name, _Agg24h())

        # status evaluation
        if not enabled:
            status = "🚫 disabled"
        else:
            if st and st.next_allowed_at and st.next_allowed_at > now:
                status = f"⏳ backoff até {_fmt_dt(st.next_allowed_at)}"
            else:
                status = "✅ ok"

        flags = []
        flags.append("impl✅" if implemented else "impl❌")
        if sched_m is not None:
            flags.append(f"sched={sched_m}m")
        flags.append(f"cooldown={cooldown_m}m")

        lines.append(f"[{i}] {p.name} — {status} | " + " | ".join(flags))

        if st:
            if st.consecutive_blocks:
                lines.append(f"   blocks seguidos: {st.consecutive_blocks}")
            if st.consecutive_failures:
                lines.append(f"   erros seguidos: {st.consecutive_failures}")

        if lr:
            bits = [f"last={lr.status}", f"at={_fmt_dt(lr.created_at)}"]
            if lr.duration_ms is not None:
                bits.append(f"{lr.duration_ms}ms")
            if lr.items_found is not None:
                bits.append(f"found={lr.items_found}")
            if lr.items_ingested is not None:
                bits.append(f"ing={lr.items_ingested}")
            if lr.items_matched is not None:
                bits.append(f"match={lr.items_matched}")
            if lr.notifications_queued is not None:
                bits.append(f"notif={lr.notifications_queued}")
            if lr.http_status is not None:
                bits.append(f"http={lr.http_status}")
            lines.append("   " + " | ".join(bits))
            if lr.error:
                # keep it short for telegram
                err = lr.error
                if len(err) > 160:
                    err = err[:157] + "..."
                lines.append(f"   err: {err}")
        else:
            lines.append("   last: -")

        # 24h snapshot
        snap = [
            f"24h total={a.total}",
            f"ok={a.success}",
            f"blocked={a.blocked}",
            f"err={a.error}",
            f"skip={a.skipped}",
        ]
        if a.avg_duration_ms is not None:
            snap.append(f"avg={a.avg_duration_ms}ms")
        if a.avg_found is not None:
            snap.append(f"avg_found={a.avg_found}")
        lines.append("   " + " | ".join(snap))
        lines.append("")

    # Telegram hard limit is ~4096 chars; keep safe
    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3797] + "..."
    await update.message.reply_text(text)


async def _admin_health(update: Update):
    now = datetime.now(timezone.utc)
    lines: List[str] = []
    lines.append("\ud83e\ude7a Admin \u2014 Health")
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
        lines.append(f"Playwright pool: browsers={st.get('browsers')} contexts={st.get('contexts')}")
    except Exception:
        pass

    try:
        from app.scrapers.base import get_session_stats

        sst = get_session_stats()
        lines.append(f"Requests sessions: {sst.get('sessions')}")
    except Exception:
        pass

    # Backoff/throttle snapshot
    with SessionLocal() as db:
        rows = db.query(SourceState).all()
        paused = [r for r in rows if r.next_allowed_at and r.next_allowed_at > now]
        if paused:
            lines.append("")
            lines.append("Sources paused (backoff/throttle):")
            for r in sorted(paused, key=lambda x: x.source):
                lines.append(
                    f"- {r.source}: until {_fmt_dt(r.next_allowed_at)} status={r.last_status or '-'}"
                )

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3797] + "..."
    safe = sanitize_for_telegram(text)
    await update.message.reply_text(safe)
