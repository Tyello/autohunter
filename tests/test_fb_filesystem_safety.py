from app.integrations.facebook.storage import delete_profile_dir, ensure_profile_dir


def test_delete_profile_dir_refuses_path_traversal():
    ensure_profile_dir("safe-user")
    assert delete_profile_dir("../etc") is False
