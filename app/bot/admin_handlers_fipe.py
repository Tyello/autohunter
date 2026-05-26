from __future__ import annotations

from telegram import Update

from app.db.session import SessionLocal
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.models.fipe_sync_run import FipeSyncRun
from app.services.fipe_prices_import_service import build_fipe_coverage_report
from app.services.fipe_monthly_sync_service import normalize_fipe_month


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


async def admin_fipe(update: Update, raw_args: list[str]) -> None:
    args = [a.strip() for a in (raw_args or []) if a.strip()]
    if args and args[0].lower() == "catalog":
        month = args[1] if len(args) >= 2 else None
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

    await update.message.reply_text("Use: /admin fipe | /admin fipe coverage [YYYY-MM] [1-50] | /admin fipe catalog [YYYY-MM]")
