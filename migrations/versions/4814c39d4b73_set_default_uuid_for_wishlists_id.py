from alembic import op

revision = "4814c39d4b73_wishlists_id"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # gen_random_uuid() vem da extensão pgcrypto
    op.execute("create extension if not exists pgcrypto;")
    op.execute("alter table wishlists alter column id set default gen_random_uuid();")


def downgrade():
    op.execute("alter table wishlists alter column id drop default;")
