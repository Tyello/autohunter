"""seed turboclass in source_configs

Revision ID: fase1_004_seed_turboclass
Revises: fase1_003_scrape_jobs
Create Date: 2026-02-21

Insere a source 'turboclass' na tabela source_configs.
A tabela é a base da verdade para enable/schedule/etc.

"""

from alembic import op


revision = "fase1_004_seed_turboclass"
down_revision = "fase1_003_scrape_jobs"
branch_labels = None
depends_on = None


def upgrade():
    # Default config: começa desabilitado; cadence mais espaçada; fallback browser on.
    op.execute(
        """
        INSERT INTO source_configs (
            source,
            is_enabled,
            sched_minutes,
            cooldown_minutes,
            rate_limit_seconds,
            proxy_server,
            browser_fallback_enabled,
            force_browser,
            extra
        ) VALUES (
            'turboclass',
            false,
            90,
            0,
            0,
            NULL,
            true,
            false,
            '{
              "http_connect_timeout_s": 5,
              "http_read_timeout_s": 20,
              "http_min_delay_ms": 220,
              "http_max_delay_ms": 650,
              "browser_timeout_ms": 35000,
              "browser_wait_until": "domcontentloaded"
            }'::jsonb
        )
        ON CONFLICT (source) DO NOTHING;
        """
    )


def downgrade():
    op.execute("DELETE FROM source_configs WHERE source = 'turboclass';")
