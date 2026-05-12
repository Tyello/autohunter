#!/usr/bin/env python3
"""Schema usage audit for AutoHunter.

Scans SQLAlchemy models + Alembic migrations and builds a heuristic usage report.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

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
            text = f.read_text(encoding="utf-8", errors="ignore")
            t.table_usage_hits += text.count(t.table_name)
            for c in t.columns.values():
                n = text.count(c.name)
                if n <= 0:
                    continue
                c.usage_count += n
                low = str(f).lower()
                if any(k in low for k in ["admin", "health", "autopilot", "system_log"]):
                    c.ops_hits += n
                if any(k in text for k in [f".{c.name}", f"filter(", "where(", "order_by(", "join("]):
                    c.read_hits += 1
                if any(k in text for k in [f"{c.name}=", "values(", "update(", "insert("]):
                    c.write_hits += 1
                if any(k in text for k in ["UniqueConstraint", "Index(", "index=True", "ForeignKey", "primary_key=True"]):
                    c.index_hits += 1


def build_markdown(tables: list[TableInfo]) -> str:
    lines = ["# Schema Usage Audit", "", "Relatório gerado automaticamente por `scripts/schema_usage_audit.py`.", ""]
    lines.append("## Inventário")
    lines.append(f"- Models SQLAlchemy analisados: **{len(tables)}**")
    lines.append(f"- Migrations Alembic analisadas: **{len(list(MIGRATIONS_DIR.glob('*.py')))}**")
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

    lines.append("## Candidatos priorizados (heurístico)")
    candidates = []
    for t in tables:
        for c in t.columns.values():
            cls = classify(c)
            if cls in {"LEGACY_CANDIDATE", "WRITE_ONLY"}:
                candidates.append((cls, t.table_name, c.name, c.usage_count))
    for cls, table, col, hits in sorted(candidates, key=lambda x: (x[0], x[3]))[:120]:
        lines.append(f"- `{table}.{col}` → **{cls}** (hits={hits})")

    lines.append("\n## Próxima migration sugerida (NÃO aplicada nesta etapa)")
    lines.append("1. Validar candidatos `LEGACY_CANDIDATE` em produção (queries reais/pg_stat_statements + logs).")
    lines.append("2. Separar remoções por domínio (ops, tracking, listing, billing) em migrations pequenas.")
    lines.append("3. Fazer rollout em 2 fases: remover leitura -> remover escrita -> drop coluna/tabela.")
    lines.append("4. Criar migration com `DROP COLUMN/TABLE` apenas após janela de observabilidade sem uso.")
    return "\n".join(lines) + "\n"


def main() -> None:
    tables = parse_models()
    scan_usage(tables)
    report = build_markdown(tables)
    out = ROOT / "docs" / "SCHEMA_USAGE_AUDIT.md"
    out.write_text(report, encoding="utf-8")
    print(f"Audit report written to: {out}")


if __name__ == "__main__":
    main()
