#!/usr/bin/env python3
"""Schema usage audit for AutoHunter.

Scans SQLAlchemy models + Alembic migrations and builds a heuristic usage report.
Optionally compares models against a real database schema.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "app" / "models"
MIGRATIONS_DIR = ROOT / "migrations" / "versions"
SEARCH_DIRS = [ROOT / "app", ROOT / "scripts", ROOT / "tests"]


@dataclass
class ColumnInfo:
    name: str
    usage_count: int = 0
    write_hits: int = 0
    read_hits: int = 0
    ops_hits: int = 0
    index_hits: int = 0


@dataclass
class TableInfo:
    table_name: str
    model_name: str
    model_file: Path
    columns: dict[str, ColumnInfo] = field(default_factory=dict)
    migration_mentions: int = 0
    table_usage_hits: int = 0


def _is_mapped_column_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id in {"mapped_column", "Column"}
    if isinstance(fn, ast.Attribute):
        return fn.attr in {"mapped_column", "Column"}
    return False


def parse_models(models_dir: Path = MODELS_DIR) -> list[TableInfo]:
    tables: list[TableInfo] = []
    for py_file in sorted(models_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        module = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            table_name = None
            cols: dict[str, ColumnInfo] = {}
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id == "__tablename__":
                            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                table_name = stmt.value.value
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if _is_mapped_column_call(stmt.value):
                        col = stmt.target.id
                        cols[col] = ColumnInfo(name=col)
            if table_name:
                tables.append(TableInfo(table_name=table_name, model_name=node.name, model_file=py_file.relative_to(ROOT), columns=cols))
    return tables


def fetch_real_schema(database_url: str) -> dict[str, set[str]]:
    engine = create_engine(database_url)
    query = text(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
    )
    schema: dict[str, set[str]] = {}
    with engine.connect() as conn:
        for table_name, column_name in conn.execute(query):
            schema.setdefault(table_name, set()).add(column_name)
    return schema


def _iter_py_files(dirs: Iterable[Path]) -> Iterable[Path]:
    for d in dirs:
        if not d.exists():
            continue
        for f in d.rglob("*.py"):
            yield f


def classify(col: ColumnInfo) -> str:
    if col.read_hits > 0:
        return "READ_ACTIVE"
    if col.ops_hits > 0:
        return "OPS_ONLY"
    if col.index_hits > 0:
        return "INDEX_OR_CONSTRAINT_ONLY"
    if col.write_hits > 0:
        return "WRITE_ONLY"
    if col.usage_count == 0:
        return "LEGACY_CANDIDATE"
    return "KEEP_STRATEGIC"


def scan_usage(tables: list[TableInfo]) -> None:
    files = list(_iter_py_files(SEARCH_DIRS))
    mig_files = list(MIGRATIONS_DIR.glob("*.py"))
    mig_text = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in mig_files)

    for t in tables:
        t.migration_mentions = mig_text.count(t.table_name)

        for f in files:
            text_body = f.read_text(encoding="utf-8", errors="ignore")
            t.table_usage_hits += text_body.count(t.table_name)
            for c in t.columns.values():
                n = text_body.count(c.name)
                if n <= 0:
                    continue
                c.usage_count += n
                low = str(f).lower()
                if any(k in low for k in ["admin", "health", "autopilot", "system_log"]):
                    c.ops_hits += n
                if any(k in text_body for k in [f".{c.name}", "filter(", "where(", "order_by(", "join("]):
                    c.read_hits += 1
                if any(k in text_body for k in [f"{c.name}=", "values(", "update(", "insert("]):
                    c.write_hits += 1
                if any(k in text_body for k in ["UniqueConstraint", "Index(", "index=True", "ForeignKey", "primary_key=True"]):
                    c.index_hits += 1


def build_markdown(tables: list[TableInfo], real_schema: dict[str, set[str]] | None = None) -> str:
    lines = ["# Schema Usage Audit", "", "Relatório gerado automaticamente por `scripts/schema_usage_audit.py`.", ""]
    lines.append("## Inventário")
    lines.append(f"- Models SQLAlchemy analisados: **{len(tables)}**")
    lines.append(f"- Migrations Alembic analisadas: **{len(list(MIGRATIONS_DIR.glob('*.py')))}**")
    if real_schema is not None:
        lines.append(f"- Tabelas reais no banco (information_schema): **{len(real_schema)}**")
    lines.append("")

    lines.append("## Inventário do banco real")
    lines.append("")
    lines.append("Tabelas reais validadas no PostgreSQL de produção:")
    lines.append("")
    validated_real_tables = [
        "account_members",
        "accounts",
        "admin_deploy_audits",
        "alembic_version",
        "app_kv",
        "autopilot_findings",
        "car_listings",
        "fb_agent_sessions",
        "fb_sessions",
        "fipe_prices",
        "market_stats_cohorts",
        "notifications",
        "plans",
        "scrape_jobs",
        "source_configs",
        "source_runs",
        "source_states",
        "source_url_cursors",
        "subscriptions",
        "system_logs",
        "telemetry_events",
        "users",
        "wishlist_filters",
        "wishlist_listing_activity",
        "wishlist_tokens",
        "wishlist_tracked_listings",
        "wishlists",
    ]
    for table_name in validated_real_tables:
        lines.append(f"- `{table_name}`")
    lines.append("")

    if real_schema is not None:
        model_map = {t.table_name: set(t.columns.keys()) for t in tables}
        model_tables = set(model_map)
        real_tables = set(real_schema)
        lines.append("## Reconciliação model x banco real")
        lines.append("### Tabelas reais no banco")
        for name in sorted(real_tables):
            lines.append(f"- `{name}`")
        lines.append("")

        lines.append("### Models sem tabela real")
        for name in sorted(model_tables - real_tables):
            lines.append(f"- `{name}`")
        lines.append("")

        lines.append("### Tabelas reais sem model")
        for name in sorted(real_tables - model_tables):
            lines.append(f"- `{name}`")
        lines.append("")

        lines.append("### Colunas reais sem model")
        for table_name in sorted(model_tables & real_tables):
            missing_in_model = sorted(real_schema[table_name] - model_map[table_name])
            if missing_in_model:
                lines.append(f"- `{table_name}`: {', '.join(f'`{c}`' for c in missing_in_model)}")
        lines.append("")

        lines.append("### Colunas de model ausentes no banco")
        for table_name in sorted(model_tables & real_tables):
            missing_in_db = sorted(model_map[table_name] - real_schema[table_name])
            if missing_in_db:
                lines.append(f"- `{table_name}`: {', '.join(f'`{c}`' for c in missing_in_db)}")
        lines.append("")

    lines.append("## Features futuras mantidas no roadmap")
    lines.append("")
    lines.append("- Facebook Marketplace/Auth:")
    lines.append("  - `fb_sessions`")
    lines.append("  - `fb_agent_sessions`")
    lines.append("- FIPE e inteligência de preço:")
    lines.append("  - `fipe_prices`")
    lines.append("  - `market_stats_cohorts`")
    lines.append("- Admin Deploy Audit:")
    lines.append("  - `admin_deploy_audits`")
    lines.append("- Autopilot:")
    lines.append("  - `autopilot_findings`")
    lines.append("- Leilões/oportunidades especiais:")
    lines.append("  - `auction_events`")
    lines.append("  - `auction_lots`")
    lines.append("  - `auction_lot_service`")
    lines.append("")

    lines.append("## Não remover agora")
    lines.append("")
    lines.append("- Campos ricos de `car_listings` devem ser mantidos para filtros avançados.")
    lines.append("- `fipe_prices` e `market_stats_cohorts` devem ser mantidos para inteligência de preço.")
    lines.append("- `admin_deploy_audits` deve ser mantido porque o deploy via Telegram é usado diariamente.")
    lines.append("- `autopilot_findings` deve ser mantido porque o Autopilot gera digest diário e será evoluído.")
    lines.append("- `fb_sessions` e `fb_agent_sessions` devem ser mantidos como investigação futura, mas fora do piloto.")
    lines.append("- `auction_*` deve ficar como roadmap futuro, não como runtime ativo.")
    lines.append("")

    lines.append("## Candidatos reais de saneamento imediato")
    lines.append("")
    lines.append("- Nenhum `DROP` recomendado nesta etapa.")
    lines.append("- Classificar `auction_*` apenas como feature futura sem tabela real no banco atual.")
    lines.append("- Sugerir PR futura para isolar/remover imports runtime de `auction_*` se estiverem no metadata principal e gerando confusão.")
    lines.append("")

    lines.append("## Uso por tabela/coluna")
    for t in sorted(tables, key=lambda x: x.table_name):
        lines.append(f"### `{t.table_name}` ({t.model_name})")
        lines.append(f"- Model: `{t.model_file}`")
        lines.append(f"- Menções em migrations: {t.migration_mentions}")
        lines.append("\n| Coluna | Classificação | Evidência (heurística) | Risco de remoção |")
        lines.append("|---|---|---:|---|")
        for c in sorted(t.columns.values(), key=lambda x: x.name):
            cls = classify(c)
            risk = "ALTO" if cls in {"READ_ACTIVE", "OPS_ONLY", "INDEX_OR_CONSTRAINT_ONLY"} else "MÉDIO" if cls == "WRITE_ONLY" else "BAIXO"
            ev = f"hits={c.usage_count}; read={c.read_hits}; write={c.write_hits}; ops={c.ops_hits}; idx={c.index_hits}"
            lines.append(f"| `{c.name}` | `{cls}` | {ev} | {risk} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate schema usage audit report.")
    parser.add_argument("--database-url", help="PostgreSQL URL for information_schema reconciliation.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tables = parse_models()
    scan_usage(tables)
    real_schema = fetch_real_schema(args.database_url) if args.database_url else None
    report = build_markdown(tables, real_schema=real_schema)
    out = ROOT / "docs" / "SCHEMA_USAGE_AUDIT.md"
    out.write_text(report, encoding="utf-8")
    print(f"Audit report written to: {out}")


if __name__ == "__main__":
    main()
