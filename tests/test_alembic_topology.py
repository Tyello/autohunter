from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


EXPECTED_REVISION = "fase1_008_car_listing_new_fields"


def _script_directory() -> ScriptDirectory:
    config = Config("alembic.ini")
    return ScriptDirectory.from_config(config)


def test_alembic_has_single_head() -> None:
    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly one Alembic head, found: {heads}"


def test_all_down_revisions_exist() -> None:
    script = _script_directory()
    revision_map = script.revision_map

    for revision in script.walk_revisions(base="base", head="heads"):
        down_revisions = revision._normalized_down_revisions
        for down_revision in down_revisions:
            assert revision_map.get_revision(down_revision) is not None, (
                f"Revision {revision.revision} points to missing down_revision {down_revision}"
            )


def test_fase1_008_is_reachable_from_head() -> None:
    script = _script_directory()
    reachable = {
        revision.revision for revision in script.walk_revisions(base="base", head="heads")
    }
    assert EXPECTED_REVISION in reachable, (
        f"{EXPECTED_REVISION} is not reachable from Alembic head chain"
    )
