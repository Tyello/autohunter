from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.core.settings import settings


def _ensure_private_owner(path: Path) -> None:
    path.chmod(0o700)
    st = path.stat()
    if st.st_uid != os.getuid():
        raise PermissionError("invalid owner")


def _safe_base(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    _ensure_private_owner(p)
    return p


def _safe_user_dir(base: Path, user_id: str) -> Path:
    user_dir = (base / user_id).resolve()
    if base not in user_dir.parents:
        raise ValueError("invalid user dir")
    return user_dir


def ensure_profile_dir(user_id: str) -> Path:
    base = _safe_base(settings.fb_profile_base_dir)
    user_dir = _safe_user_dir(base, user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    _ensure_private_owner(user_dir)
    return user_dir


def ensure_debug_dir(user_id: str) -> Path:
    base = _safe_base(settings.fb_debug_base_dir)
    user_dir = _safe_user_dir(base, user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    _ensure_private_owner(user_dir)
    return user_dir


def rotate_debug_files(user_id: str, max_files: int = 20) -> None:
    debug_dir = ensure_debug_dir(user_id)
    files = sorted([p for p in debug_dir.iterdir() if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[max_files:]:
        old.unlink(missing_ok=True)


def delete_profile_dir(user_id: str) -> bool:
    base = _safe_base(settings.fb_profile_base_dir)
    try:
        user_dir = _safe_user_dir(base, user_id)
    except ValueError:
        return False
    if not user_dir.exists():
        return True
    if base not in user_dir.parents:
        return False
    shutil.rmtree(user_dir)
    return True
