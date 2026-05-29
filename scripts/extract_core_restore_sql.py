#!/usr/bin/env python3
"""Generate selective core restore SQL from an AutoHunter pg_dump .sql.gz.

This script never connects to a database and never executes the generated SQL.
It extracts only an explicit allowlist of COPY public.<table> blocks in a safe
restore order for core user/wishlist data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backup_dump_utils import CORE_RESTORE_TABLES, extract_allowed_blocks

HEADER = """-- AutoHunter selective core restore SQL.
-- Generated from a full pg_dump by scripts/extract_core_restore_sql.py.
-- Review docs/BACKUP_RESTORE.md before applying.
-- This file intentionally contains only COPY public.<allowed_table> blocks.
-- It does not perform DDL, destructive cleanup, or touch Supabase-managed schemas.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract allowlisted COPY blocks for selective AutoHunter core-data restore."
    )
    parser.add_argument("backup", help="Path to autohunter_YYYYmmdd_HHMMSS.sql.gz")
    parser.add_argument("--output", "-o", help="Write SQL to this file instead of stdout")
    return parser


def render_restore_sql(backup: str | Path) -> str:
    blocks = extract_allowed_blocks(backup, CORE_RESTORE_TABLES)
    lines: list[str] = [HEADER.rstrip(), "", "-- Restore order:", f"-- {', '.join(CORE_RESTORE_TABLES)}", ""]
    found = {block.table for block in blocks}
    missing = [table for table in CORE_RESTORE_TABLES if table not in found]
    if missing:
        lines.append(f"-- WARNING: missing COPY blocks in dump: {', '.join(missing)}")
        lines.append("")

    for block in blocks:
        lines.append(f"-- public.{block.table}: {block.row_count} rows")
        lines.extend(block.iter_sql_lines())

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sql = render_restore_sql(args.backup)
    except OSError as exc:
        print(f"ERROR: unable to read backup: {args.backup}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: invalid backup dump: {args.backup}: {exc}", file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(sql, encoding="utf-8")
        print(f"Wrote selective restore SQL: {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
