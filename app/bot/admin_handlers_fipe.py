from __future__ import annotations

from typing import List

from telegram import Update

from app.db.session import SessionLocal
from app.services.fipe_prices_import_service import build_fipe_coverage_report


async def _admin_fipe(update: Update, raw_args: List[str]):
    args = [a.strip() for a in (raw_args or []) if a.strip()]
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
        await update.message.reply_text("\n".join(lines))
        return

    await update.message.reply_text("Use: /admin fipe | /admin fipe coverage [YYYY-MM] [1-50]")


async def admin_fipe(update: Update, args: List[str]):
    await _admin_fipe(update, args)
