#!/usr/bin/env python3
"""Utilities for safely reading AutoHunter pg_dump .sql.gz backups.

These helpers intentionally do not import application settings, read .env files,
or connect to a database. They only stream gzip-compressed SQL dumps.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

COPY_RE = re.compile(r"^COPY\s+public\.([A-Za-z_][A-Za-z0-9_]*)\s*\(.*\)\s+FROM\s+stdin;\s*$")

INSPECT_TABLES: tuple[str, ...] = (
    "users",
    "accounts",
    "account_members",
    "wishlists",
    "wishlist_filters",
    "wishlist_tokens",
    "wishlist_tracked_listings",
    "wishlist_listing_activity",
    "notifications",
    "source_configs",
    "source_states",
    "scrape_jobs",
    "source_runs",
)

CRITICAL_NON_EMPTY_TABLES: tuple[str, ...] = ("users", "wishlists", "source_configs")

CORE_RESTORE_TABLES: tuple[str, ...] = (
    "users",
    "account_members",
    "user_digest_preferences",
    "wishlists",
    "wishlist_filters",
    "wishlist_tokens",
    "wishlist_tracked_listings",
    "wishlist_listing_activity",
    "notifications",
)


class CopyBlock:
    def __init__(self, table: str, header: str, rows: list[str] | None = None) -> None:
        self.table = table
        self.header = header
        self.rows = rows or []

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def iter_sql_lines(self) -> Iterator[str]:
        yield self.header
        yield from self.rows
        yield "\\."
        yield ""


class DumpInspection:
    def __init__(self, path: Path, size_bytes: int, counts: dict[str, int], present: dict[str, bool]) -> None:
        self.path = path
        self.size_bytes = size_bytes
        self.counts = counts
        self.present = present

    def failed_requirements(self) -> list[str]:
        failures: list[str] = []
        for table in CRITICAL_NON_EMPTY_TABLES:
            if self.counts.get(table, 0) == 0:
                failures.append(f"{table}=0")
        return failures

    @property
    def ok(self) -> bool:
        return not self.failed_requirements()


def stream_copy_blocks(path: str | Path) -> Iterator[CopyBlock]:
    """Yield COPY public.<table> blocks from a gzip-compressed pg_dump.

    The dump is streamed in text mode and is not extracted to disk. Only COPY
    blocks in the public schema are yielded; DDL and Supabase-managed schemas are
    ignored by callers that consume this iterator.
    """

    backup_path = Path(path)
    with gzip.open(backup_path, "rt", encoding="utf-8", errors="replace") as dump:
        active: CopyBlock | None = None
        for raw_line in dump:
            line = raw_line.rstrip("\n")
            if active is not None:
                if line == "\\.":
                    yield active
                    active = None
                else:
                    active.rows.append(line)
                continue

            match = COPY_RE.match(line)
            if match:
                active = CopyBlock(table=match.group(1), header=line)

        if active is not None:
            raise ValueError(f"COPY block for public.{active.table} ended before terminator \\.")


def inspect_dump(path: str | Path, tables: Iterable[str] = INSPECT_TABLES) -> DumpInspection:
    backup_path = Path(path)
    size_bytes = backup_path.stat().st_size
    table_list = tuple(tables)
    table_set = set(table_list)
    counts = {table: 0 for table in table_list}
    present = {table: False for table in table_list}

    for block in stream_copy_blocks(backup_path):
        if block.table in table_set:
            present[block.table] = True
            counts[block.table] += block.row_count

    return DumpInspection(path=backup_path, size_bytes=size_bytes, counts=counts, present=present)


def extract_allowed_blocks(path: str | Path, ordered_tables: Iterable[str] = CORE_RESTORE_TABLES) -> list[CopyBlock]:
    """Return COPY blocks for the explicit allowlist, sorted by restore order."""

    ordered = tuple(ordered_tables)
    allowed = set(ordered)
    by_table: dict[str, CopyBlock] = {}
    for block in stream_copy_blocks(path):
        if block.table in allowed:
            if block.table in by_table:
                by_table[block.table].rows.extend(block.rows)
            else:
                by_table[block.table] = block

    return [by_table[table] for table in ordered if table in by_table]
