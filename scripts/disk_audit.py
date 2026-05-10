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
    for root, _, files in os.walk(path):
        for name in files:
            fp = Path(root) / name
            try:
                if fp.is_symlink():
                    continue
                total += fp.stat().st_size
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
    return total


def top_files(paths: list[str], limit: int = 30):
    items: list[tuple[int, str]] = []
    for base in paths:
        p = Path(base)
        if not p.exists() or not p.is_dir():
            continue
        for root, _, files in os.walk(p):
            for name in files:
                fp = Path(root) / name
                try:
                    if fp.is_symlink():
                        continue
                    size = fp.stat().st_size
                except (FileNotFoundError, PermissionError):
                    continue
                items.append((size, str(fp)))
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:limit]


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

    print("\n# Top 30 largest files")
    for idx, (size, path) in enumerate(top_files(TARGET_DIRS, 30), start=1):
        print(f"{idx:02d}. {human(size):>8}  {path}")


if __name__ == "__main__":
    main()
