from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy import func, or_, cast, Text, case
from telegram import Update

from app.bot.admin.helpers import (
    AUCTION_SETTINGS_LIMITS as _AUCTION_SETTINGS_LIMITS,
    fmt_dt as _fmt_dt,
    parse_admin_bool as _parse_admin_bool,
    render_rejection_reason_label as _render_rejection_reason_label,
    sample_to_match_like as _sample_to_match_like,
)
from app.bot.renderers import render_admin_auctions_summary, render_admin_auction_lot, render_admin_auction_quality_report, render_admin_auction_source_history, _fmt_money_br, render_auction_alert_preview, render_auction_alert, build_auction_alert_keyboard, _friendly_wishlist_filters
from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.wishlist import Wishlist
from app.models.auction_lot import AuctionLot
from app.services.source_configs_service import get_source_config, invalidate_source_config_cache
from app.bot.admin.users import _admin_user_by_chat, _render_user_eligible_auction_sources_hint
from app.services.wishlists_service import get_wishlist_summaries
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

logger = logging.getLogger(__name__)

_ADMIN_AUCTION_RUN_LOCK = asyncio.Lock()
_ADMIN_AUCTION_NOTIFY_LOCK = asyncio.Lock()
_AUCTION_NON_ELIGIBLE_WARNING = "Fonte experimental/não elegível para usuário final."


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


