from __future__ import annotations

import shutil
import os
from pathlib import Path

from app.core.settings import settings


def _safe_base(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    p.chmod(0o700)
    try:
        if p.stat().st_uid != os.getuid():
            raise ValueError("invalid base dir owner")
    except AttributeError:
        pass
    return p


def _is_within(base: Path, target: Path) -> bool:
    return target != base and base in target.parents


def ensure_profile_dir(user_id: str) -> Path:
    base = _safe_base(settings.fb_profile_base_dir)
    user_dir = (base / user_id).resolve()
    if not _is_within(base, user_dir):
        raise ValueError("invalid profile dir")
    user_dir.mkdir(parents=True, exist_ok=True)
    user_dir.chmod(0o700)
    try:
        if user_dir.stat().st_uid != os.getuid():
            raise ValueError("invalid profile dir owner")
    except AttributeError:
        pass
    return user_dir


def ensure_debug_dir(user_id: str) -> Path:
    base = _safe_base(settings.fb_debug_base_dir)
    user_dir = (base / user_id).resolve()
    if not _is_within(base, user_dir):
        raise ValueError("invalid debug dir")
    user_dir.mkdir(parents=True, exist_ok=True)
    user_dir.chmod(0o700)
    return user_dir


def rotate_debug_files(user_id: str, max_files: int = 20) -> None:
    debug_dir = ensure_debug_dir(user_id)
    files = sorted([p for p in debug_dir.iterdir() if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[max_files:]:
        old.unlink(missing_ok=True)


def delete_profile_dir(user_id: str) -> bool:
    base = _safe_base(settings.fb_profile_base_dir)
    user_dir = (base / user_id).resolve()
    if not _is_within(base, user_dir):
        return False
    if not user_dir.exists() or not user_dir.is_dir():
        return False
    if user_dir.exists():
        shutil.rmtree(user_dir)
    return True
