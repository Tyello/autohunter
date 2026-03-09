from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUDIT_FIELDS = [
    "price",
    "title",
    "location",
    "year",
    "km",
    "gearbox",
    "images",
    "thumbnail_url",
    "source_listing_id",
    "ad_date",
    "seller_type",
    "description",
    "risk_signals",
]


@dataclass(frozen=True)
class FieldAudit:
    present_in_listing: bool = False
    present_in_detail: bool = False
    captured_before_merge: bool = False
    present_after_merge: bool = False
    persisted: bool = False
    used_in_message: bool = False
    quality_flag_false_positive: bool = False

    def status(self) -> str:
        if self.persisted:
            return "ok"
        if self.present_after_merge or self.captured_before_merge:
            return "parcial"
        if self.present_in_listing or self.present_in_detail:
            return "capturado_na_origem"
        return "gap"


def _bool(v: Any) -> bool:
    return bool(v)


def build_matrix(samples: list[dict[str, Any]]) -> dict[str, dict[str, FieldAudit]]:
    matrix: dict[str, dict[str, FieldAudit]] = {}
    for row in samples:
        src = str(row.get("source") or "unknown").lower()
        field = str(row.get("field") or "")
        if field not in AUDIT_FIELDS:
            continue
        by_src = matrix.setdefault(src, {})
        prev = by_src.get(field, FieldAudit())
        by_src[field] = FieldAudit(
            present_in_listing=prev.present_in_listing or _bool(row.get("present_in_listing")),
            present_in_detail=prev.present_in_detail or _bool(row.get("present_in_detail")),
            captured_before_merge=prev.captured_before_merge or _bool(row.get("captured_before_merge")),
            present_after_merge=prev.present_after_merge or _bool(row.get("present_after_merge")),
            persisted=prev.persisted or _bool(row.get("persisted")),
            used_in_message=prev.used_in_message or _bool(row.get("used_in_message")),
            quality_flag_false_positive=prev.quality_flag_false_positive or _bool(row.get("quality_flag_false_positive")),
        )

    for src in matrix:
        for f in AUDIT_FIELDS:
            matrix[src].setdefault(f, FieldAudit())
    return matrix


def write_reports(samples: list[dict[str, Any]], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = build_matrix(samples)

    json_path = out_dir / "source_coverage_matrix.json"
    md_path = out_dir / "source_coverage_matrix.md"
    csv_path = out_dir / "source_coverage_matrix.csv"

    serializable = {
        src: {f: {**vars(v), "status": v.status()} for f, v in fields.items()}
        for src, fields in sorted(matrix.items())
    }
    json_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "field", "status", "present_in_listing", "present_in_detail", "captured_before_merge", "present_after_merge", "persisted", "used_in_message", "quality_flag_false_positive"])
        for src, fields in sorted(matrix.items()):
            for field in AUDIT_FIELDS:
                v = fields[field]
                w.writerow([src, field, v.status(), v.present_in_listing, v.present_in_detail, v.captured_before_merge, v.present_after_merge, v.persisted, v.used_in_message, v.quality_flag_false_positive])

    lines = [
        "# Source Audit Coverage Matrix",
        "",
        "Source | " + " | ".join(AUDIT_FIELDS) + " |",
        "------ | " + " | ".join(["-----"] * len(AUDIT_FIELDS)) + " |",
    ]
    for src, fields in sorted(matrix.items()):
        row = [src]
        for field in AUDIT_FIELDS:
            row.append(fields[field].status())
        lines.append(" | ".join(row) + " |")
    lines += [
        "",
        "## Proposta normalizeAd final",
        "- Obrigatórios: source, source_listing_id, url, title, price.",
        "- Opcionais desejáveis: location, year, km, thumbnail_url/images, gearbox.",
        "- Dependem de detalhe em várias fontes: description, seller_type, risk_signals.",
        "- Flags críticas quando ausentes: missing_url, missing_source_listing_id, missing_price.",
        "- Não tratar como missing_* global em todas as fontes: gearbox, seller_type, description.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"json": json_path, "md": md_path, "csv": csv_path}
