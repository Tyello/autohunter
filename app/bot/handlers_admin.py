from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_, cast, Text, case
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.admin import is_admin
from app.bot.text_sanitize import sanitize_for_telegram
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
from app.sources.registry import list_sources
from app.services.source_configs_service import ensure_source_configs, get_source_config, set_source_field, reset_source_config
from app.services.source_execution_service import run_source_for_all_wishlists


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


def _fmt_queue_buckets(*, matched: int, queued: int, qd: Optional[dict] = None) -> str:
    """Formata motivos de queue em buckets para /admin.

    Esperado em qd:
      - already_notified
      - cap_skipped
      - invalid_listing
      - buckets (dict)
    """
    if matched <= 0:
        return ""

    an = 0
    cs = 0
    inv = 0
    other = 0

    if isinstance(qd, dict):
        b = qd.get("buckets")
        if isinstance(b, dict):
            try:
                an = int(b.get("already_notified") or 0)
            except Exception:
                an = 0
            try:
                cs = int(b.get("cap_skipped") or 0)
            except Exception:
                cs = 0
            try:
                inv = int(b.get("invalid_listing") or 0)
            except Exception:
                inv = 0
        else:
            try:
                an = int(qd.get("already_notified") or 0)
            except Exception:
                an = 0
            try:
                cs = int(qd.get("cap_skipped") or 0)
            except Exception:
                cs = 0
            try:
                inv = int(qd.get("invalid_listing") or 0)
            except Exception:
                inv = 0

    # "other" = matches que não viraram queued nem caíram nos buckets explícitos
    try:
        other = max(0, int(matched) - int(queued) - int(an) - int(cs) - int(inv))
    except Exception:
        other = 0

    bits: list[str] = []
    if an:
        bits.append(f"already_notified={an}")
    if cs:
        bits.append(f"cap_skipped={cs}")
    if inv:
        bits.append(f"invalid_listing={inv}")
    if other:
        bits.append(f"other={other}")

    # só mostra quando tem algo útil
    if not bits:
        # se matched>0 e queued==0 e não temos bucket, deixa explícito
        if matched > 0 and queued == 0:
            return "queue_reason=unknown"
        return ""

    return " ".join(bits)


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
        await update.message.reply_text("Use: /admin sources | /admin runall | /admin matchdebug | /admin requeue | /admin health | /admin users | /admin errors")
        return

    action = args[0].lower()
    if action == "sources":
        await _admin_sources_dispatch(update, args[1:])
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
    if action == "runall":
        await _admin_runall(update, args[1:])
        return

    if action == "matchdebug":
        await _admin_matchdebug(update, args[1:])
        return

    if action == "requeue":
        await _admin_requeue(update, args[1:])
        return

    await update.message.reply_text("Ação inválida. Use: /admin sources | /admin runall | /admin matchdebug | /admin requeue | /admin health | /admin users | /admin errors")

async def _admin_sources_dispatch(update: Update, raw_args: List[str]):
    """Subcomandos para operar SourceConfig (DB)."""
    args = [a.strip() for a in (raw_args or []) if a.strip()]

    if not args:
        await _admin_sources(update, verbose=False)
        return

    # allow /admin sources verbose
    if any(a.lower() in ("v", "-v", "verbose", "full", "details") for a in args):
        await _admin_sources(update, verbose=True)
        return

    cmd = args[0].lower()

    if cmd in ("list",):
        await _admin_sources(update, verbose=False)
        return

    if cmd in ("show", "get") and len(args) >= 2:
        await _admin_sources_show(update, args[1])
        return

    if cmd in ("enable", "on") and len(args) >= 2:
        await _admin_sources_set_simple(update, args[1], "is_enabled", "true")
        return

    if cmd in ("disable", "off") and len(args) >= 2:
        await _admin_sources_set_simple(update, args[1], "is_enabled", "false")
        return

    if cmd in ("sched", "schedule") and len(args) >= 3:
        await _admin_sources_set_simple(update, args[1], "sched_minutes", args[2])
        return

    if cmd in ("cool", "cooldown") and len(args) >= 3:
        await _admin_sources_set_simple(update, args[1], "cooldown_minutes", args[2])
        return

    if cmd in ("rate", "ratelimit", "rate_limit") and len(args) >= 3:
        await _admin_sources_set_simple(update, args[1], "rate_limit_seconds", args[2])
        return

    if cmd == "proxy" and len(args) >= 3:
        v = " ".join(args[2:])
        if v.strip().lower() in ("off", "none", "null", "-"):
            v = ""
        await _admin_sources_set_simple(update, args[1], "proxy_server", v)
        return

    if cmd in ("fallback", "browser_fallback") and len(args) >= 3:
        await _admin_sources_set_simple(update, args[1], "browser_fallback_enabled", args[2])
        return

    if cmd in ("force", "force_browser") and len(args) >= 3:
        await _admin_sources_set_simple(update, args[1], "force_browser", args[2])
        return

    if cmd == "set" and len(args) >= 4:
        source = args[1]
        field = args[2]
        value = " ".join(args[3:])
        await _admin_sources_set_simple(update, source, field, value)
        return

    if cmd == "reset" and len(args) >= 2:
        await _admin_sources_reset(update, args[1])
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
        "/admin sources force <source> on|off\n"
        "/admin sources set <source> <field> <value>\n"
        "/admin sources reset <source>"
    )


async def _admin_sources_show(update: Update, source: str):
    with SessionLocal() as db:
        ensure_source_configs(db)
        cfg = get_source_config(db, source)
        if not cfg:
            await update.message.reply_text("Source não encontrada.")
            return
        lines = [
            f"🧰 Admin — Source: {cfg.source}",
            f"enabled={bool(cfg.is_enabled)}",
            f"sched_minutes={int(cfg.sched_minutes or 0)}",
            f"cooldown_minutes={int(cfg.cooldown_minutes or 0)}",
            f"rate_limit_seconds={int(cfg.rate_limit_seconds or 0)}",
            f"proxy_server={cfg.proxy_server or '-'}",
            f"browser_fallback_enabled={bool(cfg.browser_fallback_enabled)}",
            f"force_browser={bool(cfg.force_browser)}",
        ]
        await update.message.reply_text(sanitize_for_telegram("\n".join(lines)))


async def _admin_sources_set_simple(update: Update, source: str, field: str, value: str):
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

            db.commit()

        await update.message.reply_text(
            sanitize_for_telegram(
                f"✅ Atualizado {snap['source']}: {field}={value}\n"
                f"enabled={snap['enabled']} sched={snap['sched']}m cool={snap['cool']}m "
                f"rate={snap['rate']}s proxy={snap['proxy']} fallback={snap['fallback']} force={snap['force']}"
            )
        )
    except Exception as e:
        await update.message.reply_text(sanitize_for_telegram(f"Erro: {e}"))


async def _admin_sources_reset(update: Update, source: str):
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
                    m = int(res.get("matched") or 0)
                    q = int(res.get("queued") or 0)
                    qd = {
                        "already_notified": res.get("already_notified"),
                        "cap_skipped": res.get("cap_skipped"),
                        "invalid_listing": res.get("invalid_listing"),
                        "buckets": res.get("queue_buckets"),
                    }
                    extra_s = _fmt_queue_buckets(matched=m, queued=q, qd=qd)
                    extra_s = (" " + extra_s) if extra_s else ""
                    lines.append(
                        f"- {src}: ✅ success found={res.get('found')} ins={res.get('inserted')} "
                        f"match={res.get('matched')} queued={res.get('queued')}{extra_s} dur={res.get('duration_ms')}ms"
                    )
                elif st == "blocked":
                    lines.append(
                        f"- {src}: 🟠 blocked http={res.get('http_status')} backoff={res.get('backoff_minutes')}m dur={res.get('duration_ms')}ms"
                    )
                elif st == "error":
                    lines.append(
                        f"- {src}: ⚪ error backoff={res.get('backoff_minutes')}m err={_short(str(res.get('error')), 160)}"
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

    lines: List[str] = []
    lines.append("🧰 Admin — Sources")
    lines.append(f"Agora (UTC): {_fmt_dt(now)}")
    lines.append(f"Janela: 24h desde {_fmt_dt(since)}")
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

        if not enabled:
            kind = "DISABLED"
            emoji = "🚫"
            why = "disabled via source_configs"
            action = "use: /admin sources enable <source>"
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
            queued = f"{lr.notifications_queued}" if lr.notifications_queued is not None else "-"
            last_line = f"last {lr.status} at={_fmt_dt(lr.created_at)} dur={dur} found={found} match={match} queued={queued}"
            if lr.http_status is not None:
                last_line += f" http={lr.http_status}"
            payload = lr.payload or {}
            if isinstance(payload, dict):
                if payload.get("hybrid_browser_used") is True:
                    last_line += " browser=hybrid"
                if payload.get("hybrid_blocked") is True:
                    hs = payload.get("hybrid_blocked_status")
                    last_line += f" blocked=1" + (f" blocked_http={hs}" if hs is not None else "")

                # queue diagnostics (buckets)
                qd = payload.get("queue_diag") if payload else None
                try:
                    mi = int(lr.items_matched or 0)
                    qi = int(lr.notifications_queued or 0)
                except Exception:
                    mi = 0
                    qi = 0

                if mi > 0:
                    extra = _fmt_queue_buckets(matched=mi, queued=qi, qd=qd if isinstance(qd, dict) else None)
                    if extra:
                        last_line += " " + extra

        lines.append(f"[{i}] {p.name} — {state} | {emoji} {kind} | " + " ".join(flags))
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

        if verbose and lr and lr.error:
            lines.append(f"   err_full: {_short(lr.error, 420)}")

        lines.append("")

    text = "\n".join(lines)
    await _reply_chunked(update, text)


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
            plan = (sub.get("plan_code") if sub else None) or (u.plan or "free")
            plan = (plan or "free").lower()

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
    out.append("Dica: /setplan <free|pro|ultra> <chat_id>  |  /setlimit <n|none> <chat_id>")

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
