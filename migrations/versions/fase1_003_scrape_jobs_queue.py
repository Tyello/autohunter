"""scrape_jobs queue (browser FIFO)

Revision ID: fase1_003_scrape_jobs
Revises: fase1_002_car_listings
Create Date: 2026-02-19

Cria a tabela `scrape_jobs` para enfileirar execuções de scraping.
Objetivo principal: serializar execuções Playwright (ordem + previsibilidade).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fase1_003_scrape_jobs"
down_revision = "fase1_002_car_listings"
branch_labels = None
depends_on = None


def upgrade():
    # gen_random_uuid() vem do pgcrypto
    op.execute("create extension if not exists pgcrypto;")

    op.create_table(
        "scrape_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),

        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("queue", sa.Text(), nullable=False, server_default=sa.text("'browser'")),

        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),

        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),

        sa.Column("lock_owner", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),

        sa.Column("result_status", sa.Text(), nullable=True),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Checks
    op.create_check_constraint(
        "chk_scrape_jobs_status",
        "scrape_jobs",
        "status IN ('queued','running','done','failed')",
    )
    op.create_check_constraint(
        "chk_scrape_jobs_queue",
        "scrape_jobs",
        "queue IN ('browser','http')",
    )

    # Índices principais
    op.create_index(
        "ix_scrape_jobs_queue_status_run_at",
        "scrape_jobs",
        ["queue", "status", "run_at"],
    )
    op.create_index(
        "ix_scrape_jobs_source",
        "scrape_jobs",
        ["source"],
    )

    # Dedupe: somente 1 job ativo por (source, queue)
    op.create_index(
        "uq_scrape_jobs_active_source_queue",
        "scrape_jobs",
        ["source", "queue"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )

    # updated_at trigger (reusa função update_updated_at())
    op.execute(
        """
        create trigger scrape_jobs_updated_at
        before update on scrape_jobs
        for each row
        execute function update_updated_at();
        """
    )


def downgrade():
    op.execute("drop trigger if exists scrape_jobs_updated_at on scrape_jobs;")
    op.drop_index("uq_scrape_jobs_active_source_queue", table_name="scrape_jobs")
    op.drop_index("ix_scrape_jobs_source", table_name="scrape_jobs")
    op.drop_index("ix_scrape_jobs_queue_status_run_at", table_name="scrape_jobs")
    op.drop_constraint("chk_scrape_jobs_queue", "scrape_jobs", type_="check")
    op.drop_constraint("chk_scrape_jobs_status", "scrape_jobs", type_="check")
    op.drop_table("scrape_jobs")
