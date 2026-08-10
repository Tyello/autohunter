# 002 — Operational data IO cleanup (Supabase Disk IO Budget)

`[spec-kit: T3 — 9pts: arquivos=2 (5+), decisões=2 (design de job vs cron, tabelas protegidas), risco=2 (dados, migração), novidade=1 (variação de padrão existente), verif=2 (testes novos)]`

## Contexto

Investigação (ver conversa) já achou a causa raiz provável: `scripts/cleanup_operational_data.py` roda via cron a cada 6h (`config/raspberry-pi/crontab:5`) com `--apply`, mas desde a migration `5c8f1a2b3d4e_core_data_delete_guardrails.py` (2026-05-29) as tabelas `notifications` e `wishlist_listing_activity` têm um trigger `BEFORE DELETE`/`BEFORE TRUNCATE` que bloqueia qualquer DELETE sem `SET LOCAL app.allow_core_data_delete = 'on'`. O script nunca foi atualizado para setar essa flag, e o loop de regras não tem `try/except` por tabela — então a primeira exceção (na regra `notifications`) aborta o `main()` inteiro, e a regra seguinte (`wishlist_listing_activity`) nunca roda. Isso está silenciosamente quebrado há ~2,5 meses (toda execução de cron desde 2026-05-29), o que é a explicação mais provável para a tabela nº5 com IO desproporcional e para o crescimento contínuo dessas duas tabelas.

Índices para `system_logs`, `source_runs`, `scrape_jobs` já existem em produção (migrations `a1b2c3d4e5f6_operational_io_indexes.py`, `p0_03_supabase_io_indexes.py`, confirmado pelo usuário). `scrape_jobs` com 11,7M idx_scan é esperado dado a arquitetura de polling atual (workers HTTP a cada 2s × 2, browser a cada 5s, mais `requeue_stale_running_jobs` rodando em toda invocação) — não é bug.

Gap real de índice: `app/bot/admin_handlers_health.py` faz `SELECT ... WHERE component='scheduler' AND message='heartbeat' ORDER BY created_at DESC LIMIT 1` duas vezes; `message` não é indexado.

`notifications` é uma tabela protegida por design (`app/services/notifications_cleanup_service.py` já documenta: "Runtime cleanup must not issue physical DELETE; destructive retention is an explicit maintenance task") — a limpeza automática em processo (APScheduler) NUNCA deve apagar `notifications` fisicamente. Isso é intencional e deve ser preservado.

## Objetivo

1. Corrigir o script de limpeza para não quebrar silenciosamente nas tabelas protegidas (break-glass + isolamento por regra).
2. Adicionar o índice faltante em `system_logs` para o lookup de heartbeat.
3. Automatizar a limpeza das tabelas NÃO protegidas via APScheduler (jobstore persistente, mesmo padrão do job mensal da FIPE), mantendo o cron apenas para as tabelas protegidas (que continuam sendo "explicit maintenance task").
4. Padronizar janelas de retenção para 10 dias nas tabelas puramente operacionais/efêmeras (`system_logs`, `telemetry_events`, `source_runs`); manter `notifications`/`wishlist_listing_activity` em 90 dias (valor de auditoria/relatório de entrega) e `scrape_jobs` como está (fila, já em escala de horas).

## Não-objetivos

- Não resolver o problema pré-existente de múltiplos heads do Alembic (`p0_02_fipe_update_runs`, `p0_03_supabase_io_indexes`, `p1_notif_dq_partial` são heads divergentes hoje) — fora de escopo, flagar apenas.
- Não mudar a retenção de `notifications`/`wishlist_listing_activity` nem remover a proteção do guardrail.
- Não otimizar a arquitetura de polling do `scrape_jobs` (volume já é esperado).
- Não confirmar a identidade exata da "5ª tabela" contra produção (sem acesso a DB) — a spec assume que é `notifications` e/ou `wishlist_listing_activity`, ambas explicadas pelo bug do guardrail.

## Decisões tomadas

- Break-glass (`SET LOCAL app.allow_core_data_delete = 'on'`) só é setado dentro da mesma transação da regra que apaga tabela protegida, nunca globalmente.
- Job novo no APScheduler cobre apenas: `system_logs`, `telemetry_events`, `source_runs`, `scrape_jobs` (done/failed) — reusa lógica extraída para `app/services/operational_data_cleanup_service.py` (compartilhada com o script CLI, evita duplicar SQL).
- `scripts/cleanup_operational_data.py` continua sendo o único caminho para apagar `notifications`/`wishlist_listing_activity`, agora com break-glass + try/except por regra (uma falha não aborta as demais).
- Cron do Raspberry Pi permanece (cobre as tabelas protegidas); redundância com o job do APScheduler nas tabelas não-protegidas é aceitável (idempotente, custo marginal baixo com retenção de 10 dias).
- Novo índice: `CREATE INDEX CONCURRENTLY ix_system_logs_component_message_created_at ON system_logs (component, message, created_at DESC)`, seguindo o padrão de migração condicional a Postgres já usado em `a1b2c3d4e5f6_operational_io_indexes.py`.
- Nova migration usa `down_revision = "p0_03_supabase_io_indexes"` (branch adicional; não tenta resolver os múltiplos heads pré-existentes).
- Job novo registrado como `id="operational_data_cleanup"`, `interval hours=6` (mesma cadência do cron atual), reaproveitando o executor default do `run.py`.

## Premissas assumidas

- PREM-01: A 5ª tabela com IO desproporcional é `notifications` e/ou `wishlist_listing_activity`, explicada pelo bug do guardrail. Se o usuário rodar a query de confirmação e o resultado for outra tabela, essa etapa é revisitada — não invalida o resto da spec.
- PREM-02: Retenção de 10 dias é segura para `system_logs`, `telemetry_events`, `source_runs` — confirmado por análise de código (sem FK dependente de longo prazo, sem uso em billing/analytics), consistente com a decisão do usuário na clarificação.

## Critérios de aceitação (EARS)

- REQ-001: O sistema DEVE isolar falhas por regra em `scripts/cleanup_operational_data.py`/serviço compartilhado, de forma que uma exceção numa tabela não impeça a execução das regras seguintes.
- REQ-002: O sistema DEVE setar `SET LOCAL app.allow_core_data_delete = 'on'` na mesma transação antes de qualquer DELETE em `notifications` ou `wishlist_listing_activity`, e SOMENTE nessas tabelas.
- REQ-003: O sistema DEVE registrar um índice `(component, message, created_at DESC)` em `system_logs`, criado com `CREATE INDEX CONCURRENTLY` em Postgres (fallback simples em SQLite para os testes).
- REQ-004: O sistema DEVE executar via APScheduler (jobstore persistente `SQLAlchemyJobStore`) a limpeza de `system_logs`, `telemetry_events`, `source_runs`, `scrape_jobs` (done/failed) a cada 6 horas, sem tocar em `notifications`/`wishlist_listing_activity`.
- REQ-005: `operational_retention_system_logs_days`, `operational_retention_telemetry_events_days`, `operational_retention_source_runs_days` DEVEM ser 10 (hoje 7, 7, 30).
- REQ-006: `operational_retention_notifications_days` e `operational_retention_wishlist_activity_days` DEVEM permanecer 90 (sem mudança).
- REQ-007: O script CLI (`scripts/cleanup_operational_data.py`) DEVE continuar funcionando standalone (dry-run em SQLite, apply só em Postgres) usando a lógica compartilhada para as regras não-protegidas.

## Plano de testes (antes da implementação)

- `tests/test_cleanup_operational_data.py` (existente, ajustar): dry-run continua reportando contagens; regra "falha em uma tabela não aborta as outras" simulada com uma regra que lança exceção via monkeypatch.
- Novo `tests/test_operational_data_cleanup_service.py`: função compartilhada retorna contagem por tabela; garante que `notifications`/`wishlist_listing_activity` NUNCA aparecem nas regras do serviço usado pelo job do APScheduler.
- Novo `tests/test_operational_data_cleanup_job.py`: `job_operational_data_cleanup()` chama o serviço, loga em `system_logs` via `log()`, comita — mesmo padrão de `tests/test_scheduler_fipe_registration.py` para registro em `run.py` (id, interval, hours=6).
- `@pytest.mark.postgres` novo teste (segue padrão de `tests/test_db_guardrails.py`): DELETE em `notifications` com break-glass setado pelo script funciona; sem break-glass, é bloqueado (já coberto indiretamente pelo teste existente do guardrail — só precisa confirmar que o script usa o padrão certo).

## Etapas

1. `app/services/operational_data_cleanup_service.py` (novo) — extrai regras de `system_logs`, `telemetry_events`, `source_runs`, `scrape_jobs` (done/failed) do script CLI para uma função reutilizável `run_operational_cleanup(db, apply: bool) -> dict`, batched (1000/lote), mesma SQL de hoje.
2. `scripts/cleanup_operational_data.py` — refatora para usar o serviço acima nas regras não-protegidas; isola `notifications`/`wishlist_listing_activity` em regras próprias com break-glass (`SET LOCAL app.allow_core_data_delete = 'on'`) + try/except por regra (loga erro, continua). `[sensível]` — mexe em lógica de DELETE de dado protegido.
3. `app/scheduler/operational_data_cleanup_job.py` (novo) — `job_operational_data_cleanup()`, mesmo padrão de `app/scheduler/cleanup_job.py`/`filesystem_cleanup_job.py`: abre `SessionLocal()`, chama o serviço da etapa 1, loga resultado via `system_logs_service.log`, comita, captura exceção e loga erro.
4. `app/scheduler/run.py` — registra o job da etapa 3: `sched.add_job(job_operational_data_cleanup, "interval", hours=6, id="operational_data_cleanup", replace_existing=True)`, próximo ao bloco de `cleanup_notifications`/`filesystem_cleanup_daily`.
5. `migrations/versions/<nova>_system_logs_component_message_index.py` (novo) — `down_revision="p0_03_supabase_io_indexes"`, cria `ix_system_logs_component_message_created_at` via `CREATE INDEX CONCURRENTLY IF NOT EXISTS` em Postgres / `op.create_index` em SQLite (padrão de `a1b2c3d4e5f6_operational_io_indexes.py`). `[sensível]` — migração de schema em produção.
6. `app/core/settings.py` — `operational_retention_system_logs_days` 7→10, `operational_retention_telemetry_events_days` 7→10, `operational_retention_source_runs_days` 30→10 (linhas 307/308/312).
7. Testes: atualizar `tests/test_cleanup_operational_data.py`, criar `tests/test_operational_data_cleanup_service.py` e `tests/test_operational_data_cleanup_job.py` conforme plano de testes.
8. `config/raspberry-pi/crontab` + `docs/DB_REVIEW.md` — comentário atualizado explicando que o cron agora só é estritamente necessário para as tabelas protegidas (o resto é redundante com o job do APScheduler), e nota sobre o bug do guardrail corrigido.

## Gate de fechamento

Sem perguntas em aberto além da PREM-01 (5ª tabela), assumida e documentada acima.
