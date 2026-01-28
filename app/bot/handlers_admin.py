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
from app.models.user import User
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.system_log import SystemLog
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

def _short(s: Optional[str], n: int = 140) -> str:
    s = (s or "").strip()
    if not s:
        return "-"
    s = " ".join(s.split())
    return s if len(s) <= n else s[: max(0, n - 3)] + "..."


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
    if any(k in e_l for k in ("cloudflare", "captcha", "attention required")):
        return ("BLOCKED", "Cloudflare/captcha", "browser warmup + cookies; marcar como blocked no pipeline")

    # NET: rede/timeout/DNS/SSL
    if any(k in e_l for k in ("timed out", "timeout", "connection", "dns", "name or service not known", "temporary failure", "ssl", "tls")):
        return ("NET", "rede/timeout/dns/ssl", "verificar conectividade/proxy/DNS; aumentar timeout e retries")

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
        await update.message.reply_text("Use: /admin sources | /admin health | /admin users | /admin errors")
        return

    action = args[0].lower()
    if action == "sources":
        verbose = any(a.lower() in ("v", "-v", "verbose", "full", "details") for a in args[1:])
        await _admin_sources(update, verbose=verbose)
        return
    if action == "health":
        await _admin_health(update)
        return
    if action == "users":
        await _admin_users(update, args[1:])
        return
    if action == "errors":
        await _admin_errors(update, args[1:])
        return

    await update.message.reply_text("Ação inválida. Use: /admin sources | /admin health | /admin users | /admin errors")


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

    lines: List[str] = []
    lines.append("🧰 Admin — Sources")
    lines.append(f"Agora (UTC): {_fmt_dt(now)}")
    lines.append(f"Janela: 24h desde {_fmt_dt(since)}")
    lines.append("")

    for i, p in enumerate(plugins, start=1):
        enabled = _get_bool_setting(p.enabled_setting, True)
        sched_m = _get_int_setting(p.sched_minutes_setting)
        cooldown_m = _get_int_setting(p.cooldown_minutes_setting, 0) or 0
        implemented = p.scrape is not None

        st = states.get(p.name)
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

        flags: list[str] = []
        flags.append("impl✅" if implemented else "impl❌")
        if sched_m is not None:
            flags.append(f"sched={sched_m}m")
        if cooldown_m:
            flags.append(f"cool={cooldown_m}m")

        # causa (usa last_effective se last=skipped)
        lr_cause = lr
        if lr and lr.status == "skipped" and le:
            lr_cause = le

        kind = "OK"
        why = "-"
        action = "—"
        emoji = "✅"

        if not enabled:
            kind = "DISABLED"
            emoji = "🚫"
            why = "setting disabled"
            action = "habilitar a fonte nas settings"
        else:
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
                    why = f"HTTP {lr_cause.http_status or 403}"
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

        ok_pct = int(round((a.success / a.total) * 100)) if a.total else 0
        snap = f"24h ok={a.success}/{a.total} ({ok_pct}%) err={a.error} blk={a.blocked} skip={a.skipped}"
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

        lines.append(f"[{i}] {p.name} — {state} | {emoji} {kind} | " + " ".join(flags))
        if st:
            if st.consecutive_blocks:
                lines.append(f"   blocks seguidos: {st.consecutive_blocks}")
            if st.consecutive_failures:
                lines.append(f"   erros seguidos: {st.consecutive_failures}")

        lines.append(f"   {last_line}")
        lines.append(f"   {snap}")

        backoff_active = bool(enabled and st and st.next_allowed_at and st.next_allowed_at > now)
        if kind != "OK" or backoff_active:
            lines.append(f"   causa: {why}")
            lines.append(f"   ação: {action}")

        if verbose and lr and lr.error:
            lines.append(f"   err_full: {_short(lr.error, 420)}")

        lines.append("")

    text = sanitize_for_telegram("\n".join(lines))
    if len(text) > 3800:
        text = text[:3797] + "..."
    await update.message.reply_text(text)


async def _admin_health(update: Update):
    now = datetime.now(timezone.utc)
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
