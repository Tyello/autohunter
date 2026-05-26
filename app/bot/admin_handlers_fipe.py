from __future__ import annotations

from telegram import Update

from app.db.session import SessionLocal
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_sync_run import FipeSyncRun
from app.models.car_listing import CarListing
from app.services.fipe_prices_import_service import build_fipe_coverage_report
from app.services.fipe_monthly_sync_service import normalize_fipe_month
from app.services.fipe_catalog_resolver_service import (
    build_fipe_resolver_coverage_report,
    resolve_listing_to_fipe_candidates,
)
from app.services.fipe_prices_planning_service import build_fipe_price_plan, apply_fipe_price_plan

def _format_brl(value) -> str:
    if value is None:
        return "-"
    return "R$ " + format(float(value), ",.2f").replace(",", "X").replace(".", ",").replace("X", ".")


def render_admin_fipe_coverage(report: dict) -> str:
    lines = [
        "📊 FIPE coverage",
        "",
        f"Competência: {report['reference_month']}",
        "",
        f"Listings com chave FIPE: {report['listings_with_fipe_keys']}",
        f"Vehicle keys distintas: {report['vehicle_keys_distinct']}",
        f"Cobertas: {report['vehicle_keys_covered']}",
        f"Cobertura: {report['vehicle_keys_covered']}/{report['vehicle_keys_distinct']} keys ({report['coverage_pct']}%)",
        "",
        "Top ausentes:",
    ]
    top_missing = report.get("top_missing_keys", [])
    if top_missing:
        lines.extend([f"- {item['vehicle_key']}: {item['count']} listings" for item in top_missing])
    else:
        lines.append("- nenhum")
    lines.extend(
        [
            "",
            "Próximo passo:",
            "1. copie as chaves de Top ausentes para um CSV",
            f"2. dry-run: python scripts/import_fipe_prices.py --file <csv> --reference-month {report['reference_month']}",
            "3. se estiver ok, rode novamente com --apply",
        ]
    )
    return "\n".join(lines)


def render_admin_fipe_resolve(result: dict, listing: CarListing) -> str:
    lines = [
        "🧭 FIPE resolver",
        "",
        f"Listing: {(listing.make or '').strip()} {(listing.model or '').strip()} {listing.year or ''}".strip(),
        f"Competência: {result['reference_month']}",
        f"Status: {result['status']}",
    ]
    best = result.get("best_candidate")
    if best:
        lines.extend([
            "",
            "Melhor candidato:",
            str(best.get("model_name") or "-"),
            f"FIPE: {best.get('fipe_code') or '-'}",
            f"Ano: {best.get('model_year') or '-'}",
            f"Combustível: {best.get('fuel') or '-'}",
            f"Preço: {_format_brl(best.get('price'))}",
            f"Confiança: {best.get('confidence_score')} ({best.get('confidence_label')})",
            "",
            "Tokens:",
            f"- encontrados: {', '.join(best.get('matched_tokens') or ['-'])}",
            f"- ausentes: {', '.join(best.get('missing_tokens') or ['-'])}",
            "",
            "Avisos:",
        ])
        lines.extend([f"- {w}" for w in (best.get("warnings") or ["nenhum"])])
    if result.get("status") == "ambiguous" and result.get("ambiguity_reason"):
        lines.extend(["", f"Motivo ambiguidade: {result['ambiguity_reason']}"])
    others = result.get("candidates", [])[1:3]
    if others:
        lines.extend(["", "Outros candidatos:"])
        lines.extend([f"- {c.get('model_name')} — {c.get('confidence_score')} {c.get('confidence_label')} | ano {c.get('model_year')} | comb {c.get('fuel')} | FIPE {c.get('fipe_code')}" for c in others])
    return "\n".join(lines)

def render_admin_fipe_resolver_status(report: dict) -> str:
    c = report["status_counts"]
    l = report.get("confidence_label_counts", {})
    d = report.get("detailed_counts", {})
    return "\n".join([
        "📈 FIPE resolver status",
        f"Competência: {report['reference_month']}",
        f"Amostra: {report['sample_size']} (amostra limitada)",
        "Read-only: diagnóstico sem persistência em fipe_prices.",
        "",
        "Status:",
        f"matched: {c['matched']}",
        f"ambiguous: {c['ambiguous']}",
        f"no_match: {c['no_match']}",
        f"insufficient_data: {c['insufficient_data']}",
        "",
        "Labels:",
        f"high: {l.get('high', 0)}",
        f"medium: {l.get('medium', 0)}",
        f"low: {l.get('low', 0)}",
        "",
        "Detalhado:",
        f"matched_high: {d.get('matched_high', 0)}",
        f"ambiguous_high: {d.get('ambiguous_high', 0)}",
        f"ambiguous_medium: {d.get('ambiguous_medium', 0)}",
    ])


def render_admin_fipe_plan(report: dict) -> str:
    skipped = report.get("skipped_counts", {})
    lines = [
        "🧪 FIPE price plan — dry-run",
        "",
        f"Competência: {report['reference_month']}",
        f"Amostra: {report['sample_size']} listings",
        "",
        "Planejado:",
        f"- inserts: {report['planned_inserts_count']}",
        f"- would updates: {report['would_update_count']}",
        f"- already exists: {report.get('already_exists_count', skipped.get('already_exists', 0))}",
        "",
        "Skipped:",
    ]
    for reason in ["ambiguous", "no_match", "insufficient_data", "below_confidence", "missing_price", "missing_vehicle_key", "already_exists", "already_planned"]:
        lines.append(f"- {reason}: {skipped.get(reason, 0)}")
    lines.extend(["", "Exemplos de inserts:"])
    inserts = report.get("planned_inserts", [])[:2]
    if inserts:
        for item in inserts:
            lines.append(
                f"- {item.get('vehicle_key')} -> {_format_brl(item.get('fipe_price'))} | score {item.get('confidence_score')} | {item.get('model_name') or '-'}"
            )
    else:
        lines.append("- nenhum")
    lines.extend(["", "Read-only: nada foi gravado."])
    return "\n".join(lines)


def render_admin_fipe_apply_plan(report: dict) -> str:
    skipped = report.get("skipped_counts", {})
    mode = "dry-run" if report.get("dry_run", True) else "live"
    lines = [
        "🧾 FIPE apply plan",
        "",
        f"Competência: {report['reference_month']}",
        f"Modo: {mode}",
        f"Amostra: {report.get('sample_size', 0)} listings",
        "",
        "Plano:",
        f"- planned inserts: {report.get('planned_inserts_count', 0)}",
        f"- would updates: {report.get('would_update_count', 0)}",
        "",
        "Aplicado:",
        f"- inserted: {report.get('inserted_count', 0)}",
        f"- updated: {report.get('updated_count', 0)}",
        "",
        "Skipped:",
    ]
    for reason in ["ambiguous", "no_match", "insufficient_data", "below_confidence", "missing_price", "missing_vehicle_key", "already_exists", "already_planned"]:
        lines.append(f"- {reason}: {skipped.get(reason, 0)}")

    if report.get("dry_run", True):
        lines.extend(["", "Dry-run: nada foi gravado.", f"Para aplicar: /admin fipe apply_plan {report['reference_month']} live 100"])
    else:
        lines.extend(["", "fipe_prices atualizado."])

    return "\n".join(lines)


async def admin_fipe(update: Update, raw_args: list[str]) -> None:
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if args and args[0].lower() == "catalog":
        month = args[1] if len(args) >= 2 else None
        try:
            with SessionLocal() as db:
                if month:
                    month = normalize_fipe_month(month)
                else:
                    month_row = db.query(FipeCatalogEntry.reference_month).order_by(FipeCatalogEntry.reference_month.desc()).first()
                    month = month_row[0] if month_row else None
                if not month:
                    await update.message.reply_text("Sem dados no catálogo FIPE staging.")
                    return
                total = db.query(FipeCatalogEntry).filter(FipeCatalogEntry.reference_month == month).count()
                brands = db.query(FipeCatalogEntry.brand_name).filter(FipeCatalogEntry.reference_month == month, FipeCatalogEntry.brand_name.isnot(None)).distinct().count()
                models = db.query(FipeCatalogEntry.model_name).filter(FipeCatalogEntry.reference_month == month).distinct().count()
                years = db.query(FipeCatalogEntry.model_year).filter(FipeCatalogEntry.reference_month == month, FipeCatalogEntry.model_year.isnot(None)).distinct().count()
                run = db.query(FipeSyncRun).filter(FipeSyncRun.reference_month == month).order_by(FipeSyncRun.created_at.desc()).first()
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        msg = [
            "📦 FIPE catálogo staging",
            f"Competência: {month}",
            f"Total entries: {total}",
            f"Brands distinct: {brands}",
            f"Models distinct: {models}",
            f"Years distinct: {years}",
        ]
        if run:
            msg.extend([f"Latest sync run: {run.id}", f"Status: {run.status}", f"Source: {run.source}"])
        await update.message.reply_text("\n".join(msg))
        return

    if args and args[0].lower() == "resolve":
        if len(args) < 2:
            await update.message.reply_text("Use: /admin fipe resolve <listing_id> [YYYY-MM]")
            return
        listing_id = args[1]
        month = args[2] if len(args) >= 3 else None
        try:
            with SessionLocal() as db:
                if month:
                    month = normalize_fipe_month(month)
                else:
                    month_row = db.query(FipeCatalogEntry.reference_month).order_by(FipeCatalogEntry.reference_month.desc()).first()
                    month = month_row[0] if month_row else None
                if not month:
                    await update.message.reply_text("Sem dados no catálogo FIPE staging.")
                    return
                listing = db.query(CarListing).filter(CarListing.id == listing_id).first()
                if not listing:
                    await update.message.reply_text("Listing não encontrado para o ID informado.")
                    return
                result = resolve_listing_to_fipe_candidates(db, listing=listing, reference_month=month, limit=10)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(render_admin_fipe_resolve(result, listing))
        return

    if args and args[0].lower() == "plan":
        month = args[1] if len(args) >= 2 else None
        limit = 100
        if len(args) >= 3:
            try:
                limit = int(args[2])
            except Exception:
                limit = 100
        limit = max(1, min(500, limit))
        try:
            with SessionLocal() as db:
                if month:
                    month = normalize_fipe_month(month)
                else:
                    month_row = db.query(FipeCatalogEntry.reference_month).order_by(FipeCatalogEntry.reference_month.desc()).first()
                    month = month_row[0] if month_row else None
                if not month:
                    await update.message.reply_text("Sem dados no catálogo FIPE staging.")
                    return
                report = build_fipe_price_plan(db, reference_month=month, limit=limit)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(render_admin_fipe_plan(report))
        return


    if args and args[0].lower() == "apply_plan":
        month = None
        mode = "dry"
        limit = 100
        rest = args[1:]
        if rest and rest[0].lower() not in ("dry", "live"):
            month = rest[0]
            rest = rest[1:]
        if rest:
            mode = rest[0].lower()
            rest = rest[1:]
        if rest:
            try:
                limit = int(rest[0])
            except Exception:
                limit = 100
        limit = max(1, min(500, limit))
        dry_run = mode != "live"

        try:
            with SessionLocal() as db:
                if month:
                    month = normalize_fipe_month(month)
                else:
                    month_row = db.query(FipeCatalogEntry.reference_month).order_by(FipeCatalogEntry.reference_month.desc()).first()
                    month = month_row[0] if month_row else None
                if not month:
                    await update.message.reply_text("Sem dados no catálogo FIPE staging.")
                    return
                report = apply_fipe_price_plan(
                    db,
                    reference_month=month,
                    limit=limit,
                    min_confidence=80,
                    dry_run=dry_run,
                    allow_updates=False,
                )
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(render_admin_fipe_apply_plan(report))
        return

    if args and args[0].lower() == "resolver_status":
        month = args[1] if len(args) >= 2 else None
        limit = 100
        if len(args) >= 3:
            try:
                limit = int(args[2])
            except Exception:
                limit = 100
        limit = max(1, min(200, limit))
        try:
            with SessionLocal() as db:
                report = build_fipe_resolver_coverage_report(db, reference_month=month, limit=limit)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(render_admin_fipe_resolver_status(report))
        return

    if not args or args[0].lower() == "coverage":
        month = args[1] if len(args) >= 2 else None
        limit = 20
        if len(args) >= 3:
            try:
                limit = int(args[2])
            except Exception:
                limit = 20
        limit = max(1, min(50, limit))
        with SessionLocal() as db:
            try:
                report = build_fipe_coverage_report(db, reference_month=month, limit=limit)
            except ValueError as exc:
                await update.message.reply_text(str(exc))
                return
        await update.message.reply_text(render_admin_fipe_coverage(report))
        return

    await update.message.reply_text("Use: /admin fipe | /admin fipe coverage [YYYY-MM] [1-50] | /admin fipe catalog [YYYY-MM] | /admin fipe resolve <listing_id> [YYYY-MM] | /admin fipe resolver_status [YYYY-MM] [1-200] | /admin fipe plan [YYYY-MM] [1-500] | /admin fipe apply_plan [YYYY-MM] [dry|live] [1-500]")
