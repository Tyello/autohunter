"""add priority indexes for IO hot paths

Revision ID: p0_03_supabase_io_indexes
Revises: 6bc6fd42271c
Create Date: 2026-08-09
"""
from alembic import op

revision = "p0_03_supabase_io_indexes"
down_revision = "6bc6fd42271c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_system_logs_created_component", "system_logs", ["created_at", "component"], if_not_exists=True)
    op.create_index("ix_source_runs_created_status", "source_runs", ["created_at", "status"], if_not_exists=True)
    op.create_index("ix_scrape_jobs_status_created", "scrape_jobs", ["status", "created_at"], if_not_exists=True)
    op.create_index("ix_wishlist_activity_created_status", "wishlist_listing_activity", ["created_at", "status"], if_not_exists=True)


def downgrade():
    op.drop_index("ix_wishlist_activity_created_status", table_name="wishlist_listing_activity", if_exists=True)
    op.drop_index("ix_scrape_jobs_status_created", table_name="scrape_jobs", if_exists=True)
    op.drop_index("ix_source_runs_created_status", table_name="source_runs", if_exists=True)
    op.drop_index("ix_system_logs_created_component", table_name="system_logs", if_exists=True)
