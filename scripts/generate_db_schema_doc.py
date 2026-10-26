"""Gera a referencia de tabelas/colunas em docs/DATABASE_SCHEMA.md a partir dos models.

Fonte: `Base.metadata` (SQLAlchemy) + comentarios inline dos models. So o trecho entre
`<!-- BEGIN GENERATED -->` e `<!-- END GENERATED -->` e reescrito; o texto fora dos marcadores
e curado a mao.

Uso:
    python scripts/generate_db_schema_doc.py          # reescreve o arquivo
    python scripts/generate_db_schema_doc.py --check  # exit 1 se estiver desatualizado
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOC_PATH = ROOT / "docs" / "DATABASE_SCHEMA.md"
BEGIN = "<!-- BEGIN GENERATED -->"
END = "<!-- END GENERATED -->"

# Agrupamento por dominio (so apresentacao). Tabela fora do mapa cai em "Outras".
DOMAINS: List[tuple] = [
    ("Usuarios, contas e planos", ["users", "accounts", "account_members", "plans", "subscriptions", "user_digest_preferences"]),
    ("Buscas (wishlists) e rastreamento", ["wishlists", "wishlist_filters", "wishlist_tokens", "wishlist_tracked_listings", "wishlist_listing_activity"]),
    ("Anuncios e notificacoes", ["car_listings", "notifications"]),
    ("Scraping: configuracao, estado e execucao", ["source_configs", "source_states", "source_runs", "source_url_cursors", "scrape_jobs"]),
    ("Leiloes", ["auction_lots", "auction_events"]),
    ("FIPE", ["fipe_prices", "fipe_sync_runs", "fipe_catalog_entries", "fipe_lookup_requests", "fipe_update_runs"]),
    ("Facebook", ["fb_sessions", "fb_agent_sessions"]),
    ("Observabilidade, admin e KV", ["system_logs", "telemetry_events", "admin_deploy_audits", "app_kv", "autopilot_findings", "market_stats_cohorts"]),
]


def _model_comments() -> Dict[str, Dict[str, str]]:
    """{tablename: {coluna: comentario}} lendo os arquivos de app/models.

    Pega comentario na mesma linha do atributo ou nas linhas `#` imediatamente acima.
    """
    out: Dict[str, Dict[str, str]] = {}
    attr_re = re.compile(r"^\s{4}(\w+)\s*:\s*Mapped\[")
    for path in sorted((ROOT / "app" / "models").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        m = re.search(r"__tablename__\s*=\s*[\"'](\w+)[\"']", src)
        if not m:
            continue
        table = m.group(1)
        lines = src.splitlines()
        cols: Dict[str, str] = {}
        for i, line in enumerate(lines):
            am = attr_re.match(line)
            if not am:
                continue
            notes: List[str] = []
            j = i - 1
            while j >= 0 and lines[j].strip().startswith("#"):
                notes.insert(0, lines[j].strip().lstrip("#").strip())
                j -= 1
            if "#" in line:
                tail = line.split("#", 1)[1].strip()
                if tail:
                    notes.append(tail)
            if notes:
                cols[am.group(1)] = " ".join(notes)
        out[table] = cols
    return out


def _import_all_models() -> None:
    # Estes dois nao sao importados por app/models/__init__.py, mas sao tabelas reais.
    import app.models  # noqa: F401
    import app.models.autopilot_finding  # noqa: F401
    import app.models.market_stats  # noqa: F401


def _model_docstrings() -> Dict[str, str]:
    _import_all_models()
    from app.db.base import Base

    out: Dict[str, str] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = getattr(cls, "__tablename__", None)
        if table:
            doc = (cls.__doc__ or "").strip()
            out[table] = f"`{cls.__module__}.{cls.__name__}`" + (f" — {doc.splitlines()[0]}" if doc else "")
    return out


def _fmt_default(col) -> str:
    sd = col.server_default
    if sd is not None:
        arg = getattr(sd, "arg", sd)
        return f"server: `{str(arg)[:40]}`"
    d = col.default
    if d is None:
        return ""
    if getattr(d, "is_scalar", False):
        return f"`{d.arg!r}`"
    return "callable"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _table_md(table, comments: Dict[str, str], header: str) -> str:
    fk_by_col = {}
    for fk in table.foreign_keys:
        fk_by_col[fk.parent.name] = f"{fk.column.table.name}.{fk.column.name}" + (f" ({fk.ondelete})" if fk.ondelete else "")

    lines = [f"### `{table.name}`", "", header, "", "| Coluna | Tipo | Null | Default | Chave | Notas |", "|---|---|---|---|---|---|"]
    for col in table.columns:
        key = []
        if col.primary_key:
            key.append("PK")
        if col.name in fk_by_col:
            key.append("FK → " + fk_by_col[col.name])
        if col.unique:
            key.append("UQ")
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                col.name,
                _cell(str(col.type)),
                "sim" if col.nullable else "não",
                _cell(_fmt_default(col)),
                _cell(", ".join(key)),
                _cell(comments.get(col.name, "")),
            )
        )

    extras: List[str] = []
    from sqlalchemy import CheckConstraint, UniqueConstraint

    constraint_lines: List[str] = []
    for c in table.constraints:
        if isinstance(c, UniqueConstraint) and len(c.columns) > 0:
            constraint_lines.append(f"- UNIQUE `{c.name or ''}` ({', '.join(x.name for x in c.columns)})")
        elif isinstance(c, CheckConstraint):
            constraint_lines.append(f"- CHECK `{c.name or ''}`: `{str(c.sqltext)[:120]}`")
    # table.constraints e um set: ordenar para a saida ser deterministica entre processos.
    extras.extend(sorted(constraint_lines))
    for ix in sorted(table.indexes, key=lambda i: i.name or ""):
        cols = ", ".join(getattr(e, "name", str(e)) for e in ix.expressions)
        extras.append(f"- {'UNIQUE ' if ix.unique else ''}INDEX `{ix.name}` ({cols})")
    if extras:
        lines += ["", "Constraints e índices:", ""] + extras
    return "\n".join(lines)


def generate() -> str:
    from app.db.base import Base

    _import_all_models()

    tables = Base.metadata.tables
    comments = _model_comments()
    docs = _model_docstrings()

    placed = set()
    parts: List[str] = [f"Total de tabelas nos models: **{len(tables)}**.", ""]
    parts += ["## Índice", ""]
    sections: List[tuple] = []
    for title, names in DOMAINS:
        present = [n for n in names if n in tables]
        placed.update(present)
        sections.append((title, present))
    rest = sorted(n for n in tables if n not in placed)
    if rest:
        sections.append(("Outras", rest))
    for title, names in sections:
        if names:
            parts.append(f"- **{title}:** " + ", ".join(f"[`{n}`](#{n})" for n in names))
    parts.append("")

    for title, names in sections:
        if not names:
            continue
        parts += [f"## {title}", ""]
        for n in names:
            parts += [_table_md(tables[n], comments.get(n, {}), docs.get(n, "")), ""]
    return "\n".join(parts).rstrip() + "\n"


def render(existing: Optional[str]) -> str:
    body = generate()
    block = f"{BEGIN}\n\n{body}\n{END}"
    if existing and BEGIN in existing and END in existing:
        pre = existing.split(BEGIN, 1)[0]
        post = existing.split(END, 1)[1]
        return pre + block + post
    return block + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="falha se o doc estiver desatualizado")
    args = ap.parse_args()

    existing = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else None
    new = render(existing)
    if args.check:
        if (existing or "").replace("\r\n", "\n") != new:
            print("docs/DATABASE_SCHEMA.md desatualizado. Rode: python scripts/generate_db_schema_doc.py")
            return 1
        return 0
    DOC_PATH.write_text(new, encoding="utf-8", newline="\n")
    print(f"escrito {DOC_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
