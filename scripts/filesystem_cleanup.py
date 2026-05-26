#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.settings import settings
from app.services.filesystem_cleanup_service import run_filesystem_cleanup
from app.services.operational_alerts_service import _dir_size_bytes, _human_gb, _top_subdirs


def _print_summary(res: dict, before: int, after: int) -> None:
    print(json.dumps({"cache_before": before, "cache_after": after, "freed": max(0, before - after)}, indent=2))
    print(f"cache_before={_human_gb(before)} cache_after={_human_gb(after)}")
    dry_run = bool(res.get("dry_run", True))
    action_label = "would_delete" if dry_run else "deleted"
    bytes_label = "would_free" if dry_run else "freed"
    action_total = res.get("would_delete_total", res.get("deleted_total", 0)) if dry_run else res.get("deleted_total", 0)
    bytes_total = res.get("would_free_total", res.get("bytes_freed_total", 0)) if dry_run else res.get("bytes_freed_total", 0)
    print(
        f"scanned={res.get('scanned_total', 0)} candidates={res.get('candidates_total', 0)} "
        f"{action_label}={action_total} skipped={res.get('skipped_total', 0)}"
    )
    print(
        f"bytes_candidate={res.get('bytes_candidate_total', 0)} "
        f"{bytes_label}={bytes_total} dry_run={dry_run}"
    )
    for key in ("artifacts", "debug"):
        part = res.get(key, {})
        print(f"{key}: path={part.get('path')} scanned={part.get('scanned', 0)} candidates={part.get('candidates', 0)} deleted={part.get('deleted', 0)} skipped={part.get('skipped', 0)} bytes_freed={part.get('bytes_freed', 0)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe filesystem cleanup for AutoHunter runtime cache/artifacts")
    parser.add_argument("--apply", action="store_true", help="Apply deletion. Default is dry-run.")
    args = parser.parse_args()

    cache_root = Path(getattr(settings, "runtime_cache_dir", "/var/cache/autohunter")).expanduser().resolve()
    before = _dir_size_bytes(cache_root)
    res = run_filesystem_cleanup(dry_run=not args.apply)
    after = _dir_size_bytes(cache_root)

    _print_summary(res, before, after)
    print("top_dirs:")
    for size, path in _top_subdirs(cache_root, limit=12, max_depth=2):
        print(f"  - {_human_gb(size)}\t{path}")


if __name__ == "__main__":
    main()
