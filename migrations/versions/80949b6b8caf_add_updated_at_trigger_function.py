from alembic import op

revision = "0001_updated_at_fn"
down_revision = None

def upgrade():
    op.execute("""
    create or replace function update_updated_at()
    returns trigger as $$
    begin
      new.updated_at = now();
      return new;
    end;
    $$ language plpgsql;
    """)

def downgrade():
    op.execute("drop function if exists update_updated_at();")
