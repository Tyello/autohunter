#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
from pathlib import Path

TARGET_DIRS = [
    "/opt/autohunter",
    "/opt/autohunter/.data",
    "/opt/autohunter/artifacts",
    "/opt/autohunter/debug",
    "/opt/autohunter/profiles",
    "/var/lib/autohunter",
    "/var/cache/autohunter",
    "/var/log/autohunter",
    "/var/cache/autohunter/artifacts/source_audit_candidates",
    "/var/cache/autohunter/debug",
    "/var/cache/autohunter/pw-browsers",
    "/var/lib/autohunter/playwright",
    "/var/lib/autohunter/profiles/fb",
]


def human(n: int) -> str:
    n = float(max(0, n))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def dir_size(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    total = 0
    for root, _, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            fp = Path(root) / name
            try:
                if fp.is_symlink():
                    continue
                total += fp.stat().st_size
            except (FileNotFoundError, PermissionError, OSError):
                continue
    return total


def top_files(paths: list[str], limit: int = 30):
    items: list[tuple[int, str]] = []
    for base in paths:
        p = Path(base)
        if not p.exists() or not p.is_dir():
            continue
        for root, _, files in os.walk(p, onerror=lambda _e: None):
            for name in files:
                fp = Path(root) / name
                try:
                    if fp.is_symlink():
                        continue
                    size = fp.stat().st_size
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                items.append((size, str(fp)))
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:limit]


def top_subdirs(base: Path, limit: int = 12, max_depth: int = 2):
    if not base.exists() or not base.is_dir():
        return []
    rows: list[tuple[int, str]] = []
    base_depth = len(base.parts)
    for root, dirs, _files in os.walk(base, onerror=lambda _e: None):
        root_p = Path(root)
        depth = len(root_p.parts) - base_depth
        if depth > max_depth:
            dirs[:] = []
            continue
        if root_p == base:
            continue
        try:
            size = dir_size(root_p)
        except Exception:
            continue
        rows.append((size, str(root_p)))
    rows.sort(key=lambda x: x[0], reverse=True)
    return rows[:limit]


def main() -> None:
    usage = shutil.disk_usage("/")
    used_pct = (usage.used / usage.total * 100) if usage.total else 0.0
    print("# Disk summary (/)")
    print(f"total={human(usage.total)} used={human(usage.used)} free={human(usage.free)} used_pct={used_pct:.1f}%")

    print("\n# Directory sizes")
    for raw in TARGET_DIRS:
        p = Path(raw)
        exists = p.exists()
        size = dir_size(p) if exists and p.is_dir() else 0
        status = "ok" if exists else "missing"
        print(f"{raw}\t{human(size)}\t{status}")

    cache_root = Path("/var/cache/autohunter")
    print("\n# Cache hotspots (/var/cache/autohunter)")
    if not cache_root.exists():
        print("/var/cache/autohunter\tmissing")
    else:
        for size, path in top_subdirs(cache_root, limit=15, max_depth=2):
            print(f"{human(size):>8}  {path}")

    print("\n# Focus areas")
    for p in [
        Path("/var/cache/autohunter/artifacts"),
        Path("/var/cache/autohunter/debug"),
        Path("/var/cache/autohunter/pw-browsers"),
        Path("/var/cache/autohunter"),
    ]:
        print(f"{str(p)}\t{human(dir_size(p))}\t{'ok' if p.exists() else 'missing'}")

    print("\n# Top 30 largest files")
    for idx, (size, path) in enumerate(top_files(TARGET_DIRS, 30), start=1):
        print(f"{idx:02d}. {human(size):>8}  {path}")


if __name__ == "__main__":
    main()
