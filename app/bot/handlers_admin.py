from __future__ import annotations

import asyncio
import json
import logging
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
from app.bot.text_sanitize import sanitize_for_telegram
from app.bot.renderers import render_admin_auctions_summary, render_admin_auction_lot, _fmt_money_br
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
)
from app.services.source_configs_service import ensure_source_configs, get_source_config, set_source_field, reset_source_config
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
from app.services.wishlists_service import get_user_plan_snapshot
from app.services.auction_ingestion_service import run_auction_ingestion
from app.services.auction_matching_service import match_auction_lots_for_all_wishlists, match_auction_lots_for_wishlist
from app.sources.auctions.registry import resolve_auction_source_alias, render_supported_auction_sources_hint


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


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def _mins_left(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if not dt:
        return None
    if dt <= now:
        return 0
    return int((dt - now).total_seconds() // 60)



_ADMIN_AUCTION_RUN_LOCK = asyncio.Lock()


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
        await update.message.reply_text("Use: /admin sources | /admin auctions | /admin runall | /admin matchdebug | /admin requeue | /admin reindex_wishlists | /admin tokens | /admin health | /admin audit | /admin users | /admin errors | /admin deploy | /admin premium")
        return

    action = args[0].lower()
    if action == "sources":
        await _admin_sources_dispatch(update, args[1:])
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
    if action == "premium":
        await _admin_premium(update, context, args[1:])
        return
    if action == "auctions":
        await _admin_auctions(update, args[1:])
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

    await update.message.reply_text("Ação inválida. Use: /admin sources | /admin auctions | /admin runall | /admin matchdebug | /admin requeue | /admin reindex_wishlists | /admin tokens | /admin health | /admin audit | /admin users | /admin errors | /admin deploy | /admin fb_sessions | /admin premium")


async def _admin_auctions(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    with SessionLocal() as db:
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
            lots = db.query(AuctionLot).filter(AuctionLot.source == source).order_by(AuctionLot.updated_at.desc()).limit(10).all()
            if not lots:
                await update.message.reply_text(f"Nenhum lote persistido para source={source}.")
                return
            lines = [f"⚠️ Admin Leilões — source {source} (últimos {len(lots)})", ""]
            for lot in lots:
                lines.append(render_admin_auction_lot(lot))
                lines.append("")
            await update.message.reply_text("\n".join(lines).strip())
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
            except Exception:
                logger.exception(
                    "admin_auction_run_failed",
                    extra={"source": source, "limit": limit, "enrich_details": enrich_details, "chat_id": update.effective_chat.id},
                )
                await update.message.reply_text("Falha ao rodar ingestão de leilões. Verifique logs.")
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
            lines.extend(["", "Próximo passo:", f"/admin auctions source {source}"])
            await update.message.reply_text("\n".join(lines))
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

        if sub == "match":
            if len(args) >= 3 and args[1].lower() == "wishlist":
                target_id = args[2].strip()
                try:
                    wishlist_uuid = uuid.UUID(target_id)
                except Exception:
                    wishlist_uuid = None
                wishlist = db.query(Wishlist).filter(Wishlist.id == wishlist_uuid).first() if wishlist_uuid else None
                if not wishlist:
                    await update.message.reply_text("Wishlist não encontrada.")
                    return
                matches = match_auction_lots_for_wishlist(db, wishlist, limit=10)
                if not matches:
                    await update.message.reply_text("Sem leilões compatíveis para esta busca.")
                    return
                await update.message.reply_text("\n".join(_render_admin_auction_matches(wishlist.query, matches)))
                return
            elif len(args) >= 2:
                source = resolve_auction_source_alias(args[1])
                if not source:
                    await update.message.reply_text(f"Source de leilão não suportada. {render_supported_auction_sources_hint()}")
                    return
                matches_by = match_auction_lots_for_all_wishlists(db, source=source, limit_per_wishlist=5)
            else:
                matches_by = match_auction_lots_for_all_wishlists(db, limit_per_wishlist=5)


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

    await update.message.reply_text("Use: /admin auctions | /admin auctions source <source> | /admin auctions run <source> [--limit N] [--enrich] | /admin auctions upcoming | /admin auctions motos | /admin auctions match [vip|mega|win|copart|wishlist <id>]")


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
    enabled_sources = 0
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

        if enabled and implemented:
            enabled_sources += 1

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
            if stale_eval.stale:
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
        if stale_eval is not None and stale_eval.stale and not op_class.include_in_critical_stale:
            lines.append(f"   note: role={op_class.role} (stale não crítico em /admin health)")

        if verbose and lr and lr.error:
            lines.append(f"   err_full: {_short(lr.error, 420)}")

        lines.append("")

    stale_ratio = (stale_sources / enabled_sources) if enabled_sources else 0.0
    stale_min_sources = int(getattr(settings, "scheduler_global_stale_min_sources", 3) or 3)
    stale_ratio_cut = float(getattr(settings, "scheduler_global_stale_ratio", 0.6) or 0.6)
    if stale_sources > 0:
        lines.insert(4, f"Stale sources: {stale_sources}/{enabled_sources} ({int(round(stale_ratio * 100))}%)")
    if stale_sources >= stale_min_sources and stale_ratio >= stale_ratio_cut:
        lines.insert(5, "🚨 indício global: várias sources stale simultaneamente (scheduler/orquestrador)")

    text = "\n".join(lines)
    await _reply_chunked(update, text)


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
