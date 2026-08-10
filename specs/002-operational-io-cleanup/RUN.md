2026-08-10 | plan | T3 declarado, clarificação com usuário (3 perguntas) antes da spec
2026-08-10 | finding | root cause: scripts/cleanup_operational_data.py quebra silenciosamente em notifications/wishlist_listing_activity desde a migration 5c8f1a2b3d4e (guardrail, 2026-05-29) — sem SET LOCAL app.allow_core_data_delete, sem isolamento por regra
2026-08-10 | etapa 1 | app/services/operational_data_cleanup_service.py criado — auto-aprovada (extração, sem lógica nova)
2026-08-10 | etapa 2 [sensível] | scripts/cleanup_operational_data.py refatorado com break-glass + try/except por regra — REQ-001, REQ-002 — testes existentes (7) continuam passando
2026-08-10 | etapa 3 | app/scheduler/operational_data_cleanup_job.py criado — REQ-004 — auto-aprovada (padrão idêntico a cleanup_job.py/filesystem_cleanup_job.py)
2026-08-10 | etapa 4 | app/scheduler/run.py — job registrado (id=operational_data_cleanup, interval hours=6) — REQ-004
2026-08-10 | etapa 5 [sensível] | migrations/versions/b2c4d6e8f0a1_system_logs_component_message_index.py — REQ-003 — down_revision=p0_03_supabase_io_indexes; alembic heads confirmado (3 heads pré-existentes não resolvidos, fora de escopo)
2026-08-10 | etapa 6 | app/core/settings.py — retenções 7/7/30 -> 10/10/10 — REQ-005, REQ-006 (notifications/wishlist_activity inalterados)
2026-08-10 | etapa 7 | testes novos: test_operational_data_cleanup_service.py (3), test_operational_data_cleanup_job.py (2), test_operational_data_cleanup_registration.py (1) — todos verdes; test_cleanup_operational_data.py (7 existentes) continuam verdes
2026-08-10 | etapa 8 | config/raspberry-pi/crontab + docs/DB_REVIEW.md atualizados com causa raiz e escopo residual
2026-08-10 | status | spec fechada; pendência documentada: confirmar 5ª tabela e stats_reset contra produção (sem acesso a DB nesta sessão)
