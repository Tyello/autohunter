"""merge auction source config head

Revision ID: e1f2a3b4c5d6
Revises: b3f7a1e9c2d4, c9a1d7b2e4f0
Create Date: 2026-05-16
"""

from typing import Sequence, Union

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = ("b3f7a1e9c2d4", "c9a1d7b2e4f0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
