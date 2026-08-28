# RUN — 006-db-io-reduction

2026-08-27 spec criada. Tier T3 (9pts). Fase 1 = etapas 1-6 (itens 1 e 2 do relatório, prioridade do usuário). Fase 2 = etapas 7-8 (itens 3 e 6), gated por validação humana pós-deploy da Fase 1 no painel Query Performance do Supabase.
2026-08-27 Etapa 1 (baseline) concluída — specs/006-db-io-reduction/BASELINE.md criado.
2026-08-27 Etapa 2 (worker_threads.py) concluída pelo spec-executor — app/scheduler/worker_threads.py + tests/test_scheduler_worker_threads.py (novos). VALIDA COM passou: 4 testes novos + 6 de test_scheduler_shutdown.py, todos verdes.
2026-08-27 Etapa 2 [APROVADO] pelo spec-reviewer-senior. Observação não-bloqueante: log de exceção via print() em vez de _log_suppressed_exception (evita acoplamento a SessionLocal/import circular) — risco residual aceito.
2026-08-27 Etapa 3 (migrar browser_queue_worker/http_queue_worker para threads) concluída pelo spec-executor — app/scheduler/run.py, app/cli/run_scheduler.py, app/scheduler/cli.py. VALIDA COM passou: 41/41 testes de scheduler.
2026-08-27 Etapa 3 [APROVADO] pelo spec-reviewer-senior. Sem riscos residuais.
2026-08-27 Etapa 4 (trocar _get_cfg por get_source_config_snapshot) concluída pelo spec-executor — app/services/source_execution_service.py, app/scheduler/run.py, tests/test_source_execution_service.py, tests/test_scheduler_source_config_bootstrap.py. VALIDA COM passou: 4+5+3 testes.
