import os
import stat
from pathlib import Path

from app.core.settings import settings
from app.integrations.facebook.storage import delete_profile_dir, ensure_profile_dir


def test_delete_profile_dir_only_under_base(tmp_path, monkeypatch):
    base = tmp_path / "profiles"
    monkeypatch.setattr(settings, "fb_profile_base_dir", str(base))

    user_dir = ensure_profile_dir("u-safe")
    assert user_dir.exists()
    assert delete_profile_dir("u-safe") is True
    assert not user_dir.exists()

    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    target = outside / "u-bad"
    target.mkdir(parents=True, exist_ok=True)

    assert delete_profile_dir("../outside/u-bad") is False
    assert target.exists()


def test_profile_dir_private_permissions(tmp_path, monkeypatch):
    base = tmp_path / "profiles-perm"
    monkeypatch.setattr(settings, "fb_profile_base_dir", str(base))
    user_dir = ensure_profile_dir("u-perm")
    mode = stat.S_IMODE(os.stat(user_dir).st_mode)
    assert mode == 0o700
