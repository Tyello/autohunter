from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy.orm import joinedload
from sqlalchemy import func
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.admin.auth import is_admin
from app.bot.admin.helpers import (
    fmt_dt as _fmt_dt,
    short as _short,
    chunk_lines as _chunk_lines,
)
from app.bot.admin.sources import (
    _render_run_summary_lines,
    _render_webmotors_blocked_diag_lines,
)
from app.bot.text_sanitize import sanitize_for_telegram
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.car_listing import CarListing
from app.models.fb_session import FBSession
from app.models.source_config import SourceConfig
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.browser_warmup_service import warmup_source
from app.services.db_io_observability_service import collect_db_io_metrics, render_db_io_metrics
from app.services.filesystem_cleanup_service import run_filesystem_cleanup
from app.services.premium_subscription_service import activate_manual_premium
from app.services.source_configs_service import ensure_source_configs, get_source_config
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.wishlist_tokens_service import reindex_active_wishlists
from app.services.wishlists_service import get_user_plan_snapshot
from app.sources.registry import list_sources

logger = logging.getLogger(__name__)


async def admin_db_io(update: Update):
    with SessionLocal() as db:
        await update.message.reply_text(render_db_io_metrics(collect_db_io_metrics(db)))


async def _admin_cleanup(update: Update, raw_args: List[str]):
    def _human_bytes(n: int) -> str:
        n = max(0, int(n or 0))
        units = ("B", "KB", "MB", "GB", "TB")
        v = float(n)
        idx = 0
        while v >= 1024.0 and idx < len(units) - 1:
            v /= 1024.0
            idx += 1
        return f"{v:.2f}{units[idx]}"

    args = [a.strip().lower() for a in (raw_args or []) if a.strip()]
    mode = args[0] if args else "status"
    if mode not in {"status", "dryrun", "apply"}:
        await update.message.reply_text("Use: /admin cleanup status | /admin cleanup dryrun | /admin cleanup apply")
        return
    if mode == "status":
        await update.message.reply_text(
            sanitize_for_telegram(
                "Cleanup config:\n"
                f"- enabled={bool(getattr(settings, 'filesystem_cleanup_enabled', True))}\n"
                f"- cache_max_bytes={int(getattr(settings, 'filesystem_cleanup_cache_max_bytes', 0) or 0)}\n"
                f"- cache_retention_days={int(getattr(settings, 'filesystem_cleanup_cache_retention_days', 14) or 14)}\n"
                f"- artifacts_days={int(getattr(settings, 'filesystem_cleanup_artifacts_days', 14) or 14)}\n"
                f"- debug_days={int(getattr(settings, 'filesystem_cleanup_debug_days', 7) or 7)}\n"
                "Run: /admin cleanup dryrun"
            )
        )
        return
    dry_run = mode != "apply"
    res = run_filesystem_cleanup(dry_run=dry_run)
    verb = "would_free" if dry_run else "freed"
    msg = (
        f"Filesystem cleanup ({'dry-run' if dry_run else 'apply'}):\n"
        f"- scanned={res.get('scanned_total', 0)} candidates={res.get('candidates_total', 0)}\n"
        f"- deleted={res.get('deleted_total', 0)} skipped={res.get('skipped_total', 0)}\n"
        f"- {verb}_bytes={res.get('would_free_total', res.get('bytes_freed_total', 0))} "
        f"({_human_bytes(res.get('would_free_total', res.get('bytes_freed_total', 0)))})"
    )
    await update.message.reply_text(sanitize_for_telegram(msg))


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
                    impl_note = f" impl={res.get('runtime_impl')}" if res.get("runtime_impl") else ""
                    lines.append(
                        f"- {src}: ✅ success{impl_note} found={res.get('found')} ins={res.get('inserted')} "
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
