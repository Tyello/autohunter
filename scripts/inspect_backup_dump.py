#!/usr/bin/env python3
"""Inspect AutoHunter pg_dump .sql.gz backups without connecting to a database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backup_dump_utils import CRITICAL_NON_EMPTY_TABLES, INSPECT_TABLES, inspect_dump


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect a gzip-compressed AutoHunter SQL dump and count COPY public.<table> rows."
    )
    parser.add_argument("backup", help="Path to autohunter_YYYYmmdd_HHMMSS.sql.gz")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backup_path = Path(args.backup)

    try:
        report = inspect_dump(backup_path)
    except OSError as exc:
        print(f"ERROR: unable to read backup: {backup_path}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: invalid backup dump: {backup_path}: {exc}", file=sys.stderr)
        return 2

    print(f"Backup: {report.path}")
    print(f"Size bytes: {report.size_bytes}")
    print("COPY public.* table counts:")
    for table in INSPECT_TABLES:
        marker = "present" if report.present.get(table, False) else "missing"
        print(f"- {table}: {report.counts.get(table, 0)} ({marker})")

    failures = report.failed_requirements()
    if failures:
        required = ", ".join(CRITICAL_NON_EMPTY_TABLES)
        print(f"FAILED: critical table requirement not met ({'; '.join(failures)}).", file=sys.stderr)
        print(f"Critical tables expected to be non-empty: {required}.", file=sys.stderr)
        return 1

    print("OK: critical tables users, wishlists and source_configs are non-empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
