# DB Review — AutoHunter (Telegram-first)

## Escopo e método
- Revisão baseada em **código atual** (`app/models`, serviços/bot/scheduler/web) e histórico de migrations Alembic em `migrations/versions`.
- Sem criação de índice/migration “no escuro”.
- Sem alterações em scheduler/scraping/source_execution_service além de análise.
- Quando não há evidência runtime real (produção), marcar como hipótese.

## Resumo executivo
- A modelagem cobre bem o fluxo principal Telegram-first: `wishlists -> scrape_jobs -> car_listings -> matching -> notifications`.
- Há boa cobertura de índices em tabelas quentes: `notifications`, `scrape_jobs`, `source_runs`, `source_states`, `wishlist_tokens`.
- Existem pontos de risco clássico de performance por crescimento de dados operacionais (especialmente `notifications`, `source_runs`, `telemetry_events`, `system_logs`) e por consultas amplas em health/admin.
- Há oportunidades de quick win em leitura/admin (batching já existe em alguns pontos; ainda há consultas por source repetidas em alguns handlers).
- Sem `TEST_DATABASE_URL`, não foi possível validar com `EXPLAIN ANALYZE` real no PostgreSQL nesta execução.

## Inventário técnico por tabela

### users
- Finalidade: identidade/estado do usuário Telegram, plano/limites, vínculo de conta.
- Colunas principais: `id`, `telegram_chat_id`, `is_active`, `plan`, `daily_limit_override`, `last_daily_limit_notice_at`, `account_id`.
- Índices/constraints observáveis: índices para plano/override e `last_daily_limit_notice_at` (migrations), PK em `id`.
- Fluxos: onboarding bot, limites de envio, admin listagem de usuários.
- Risco/performance: consultas por `telegram_chat_id` são frequentes; garantir índice dedicado continua crítico.

### wishlists
- Finalidade: intenção de busca por usuário.
- Colunas principais: `id`, `user_id`, `query`, `is_active`, timestamps.
- Índices/constraints: índice em `user_id`, FK `user_id -> users.id (RESTRICT)`.
- Fluxos: `/wishlist`, menu wishlists, matching elegível, tracking por wishlist.
- Risco/performance: listagens por usuário são frequentes; risco de N+1 ao carregar filtros/tracking sem eager loading.

### wishlist_filters
- Finalidade: filtros estruturados por wishlist.
- Colunas principais: `id`, `wishlist_id`, `field`, `operator`, `value`.
- Índices/constraints: índice `wishlist_id`, índice `field`, unique composta (`wishlist_id`,`field`,`operator`,`value`).
- Fluxos: filtros guiados (add/list/remove), matching.
- Risco/performance: bom suporte para carga por wishlist; índice em `field` isolado pode ter utilidade baixa fora de diagnósticos.

### wishlist_tokens
- Finalidade: índice invertido token->wishlist para matching escalável.
- Colunas principais: `wishlist_id`, `token` (PK composta).
- Índices/constraints: PK composta, índice em `token`, índice em `wishlist_id`.
- Fluxos: seleção de candidatas no matching.
- Risco/performance: tabela crítica para matching; manter cardinalidade saudável e rotina de refresh consistente.

### wishlist_tracked_listings
- Finalidade: até 3 anúncios rastreados por wishlist (slots) + snapshot de preço/alertas.
- Colunas principais: `wishlist_id`, `car_listing_id`, `slot`, `price_*`, `price_drop_alert_enabled`, `last_drop_alert_at`.
- Índices/constraints: unique (`wishlist_id`,`car_listing_id`), unique (`wishlist_id`,`slot`), check slot 1..3, índice em `wishlist_id,slot`.
- Fluxos: `/wishlist_track_list`, alerta de queda de preço, tracking UI.
- Risco/performance: baixo volume por wishlist (cap 3), mas job periódico depende de filtro por `price_drop_alert_enabled` + ordenação por `updated_at`.

### car_listings
- Finalidade: anúncios normalizados com dedupe por origem.
- Colunas principais: `source`, `external_id`, `url`, `price`, `make/model/version`, `city/state`, `is_sold`, `sold_at`, timestamps.
- Índices/constraints: unique (`source`,`external_id`), índices em `source`, `created_at`, e compostos relevantes adicionados em migrations fase1 (ex.: combinações para consultas por marca/modelo/ano/price/source conforme evolução).
- Fluxos: ingestão/upsert, matching, tracking lookup, debug/admin source view.
- Risco/performance: tabela de maior crescimento; consultas por `url`/`external_id` e janelas recentes exigem plano de índice bem alinhado.

### notifications
- Finalidade: fila e trilha de entrega de notificações Telegram.
- Colunas principais: `user_id`, `wishlist_id`, `car_listing_id`, `status`, `sent_at`, `next_attempt_at`, `processing_started_at`, `attempts`, `reason`, `score_v2`.
- Índices/constraints: índices de status, created_at, user_id; endurecimento de delivery com índices adicionais; índice parcial PostgreSQL para 24h sent (`wishlist_id, sent_at WHERE status='sent'`) + fallback SQLite.
- Fluxos: enqueue matching, sender, resumo de wishlist 24h, cleanup.
- Risco/performance: tabela muito quente de escrita/leitura; risco de bloat e retenção longa.

### scrape_jobs
- Finalidade: fila persistente de scraping (http/browser), retry e lock.
- Colunas principais: `source`, `queue`, `status`, `run_at`, `priority`, `locked_at`, `started_at`, `attempt`.
- Índices/constraints: índices para dequeue e jobs stale/requeue (migrations fase1_003 e guard de conflito).
- Fluxos: scheduler enqueue, workers dequeue, monitor health/admin.
- Risco/performance: crítico operacional; sem índice correto, latência de fila cresce rapidamente.

### source_runs
- Finalidade: histórico de execuções por source (status, duração, contadores).
- Colunas principais: `source`, `status`, `created_at`, `duration_ms`, `items_*`, `error`.
- Índices/constraints: índices (`source, created_at`) e (`status, created_at`).
- Fluxos: admin health/sources, monitor, autopilot, diagnóstico.
- Risco/performance: alto crescimento; consultas por source e janela temporal são constantes.

### source_states
- Finalidade: estado operacional corrente por source (backoff/saúde).
- Colunas principais: `source`, `next_allowed_at`, `last_run_at`, `last_effective_run_at`, `consecutive_*`, `last_status`.
- Índices/constraints: índice único `source`, índice em `next_allowed_at`, índice em `last_effective_run_at`.
- Fluxos: scheduler due/backoff, admin monitor.
- Risco/performance: baixo volume, alta criticidade funcional.

### system_logs
- Finalidade: logs estruturados operacionais.
- Colunas principais: `level`, `component`, `message`, `created_at`, payload.
- Índices/constraints: índices em `level` e `created_at`.
- Fluxos: admin health, monitor de erros, heartbeat scheduler.
- Risco/performance: crescimento contínuo; consultas por `component+message` podem pedir índice composto dedicado.

### telemetry_events
- Finalidade: telemetria analítica/operacional por source/evento.
- Colunas principais: `source`, `event_type`, `fingerprint`, `created_at`, payload.
- Índices/constraints: created_at; (`source`,`created_at`); (`event_type`,`created_at`); (`fingerprint`,`created_at`); (`source`,`event_type`,`fingerprint`).
- Fluxos: observabilidade e troubleshooting.
- Risco/performance: potencialmente grande; controlar retenção.

### wishlist_listing_activity
- Finalidade: atividade de anúncio por wishlist (estado ativo/sumiu etc.).
- Colunas principais: `wishlist_id`, `car_listing_id`, `source_name`, `listing_identity_key`, `status`, `last_seen_at`.
- Índices/constraints: unique (`wishlist_id`,`listing_identity_key`), índices por `wishlist_id,status,last_seen_at` e `car_listing_id`.
- Fluxos: digest semanal, atividade/listing lifecycle.
- Risco/performance: consulta por wishlist+status+ordenação precisa índice alinhado (já existe).

## Queries críticas mapeadas (por fluxo)
1. `/wishlist` e menu wishlists: leitura de wishlists por usuário + filtros/contagens agregadas em serviços de summary/UI.
2. `/wishlist_track_list`: join `wishlist_tracked_listings` + `car_listings` por wishlist/slot.
3. filtros guiados: CRUD em `wishlist_filters` por `wishlist_id`.
4. criação de wishlist + enqueue inicial: insert `wishlists`, seguido de enqueue `scrape_jobs`.
5. matching: candidatas por `wishlist_tokens`, checagem filtros e dedupe em `notifications`.
6. fila de notifications: consultas por `status`, `next_attempt_at`, lock/processing e dedupe por (`wishlist_id`,`car_listing_id`, motivo/estado).
7. sender Telegram: busca lote de pendentes + joins de `user`/`wishlist`/`car_listing`.
8. admin health: agregações em `scrape_jobs`, `notifications`, leituras recentes de `source_runs`, `system_logs`, `source_states`.
9. admin sources: por source, últimas runs + estado/config.
10. scheduler/jobs: due/backoff em `source_states/config`; dequeue/cleanup em `scrape_jobs`.

## N+1 e loops com query (achados)
- **Severidade média**: handlers admin que para cada source executam consultas separadas de `source_runs` (latest/non-skipped/aggregates). Pode escalar com número de sources.
- **Severidade baixa/média**: alguns fluxos UI de tracking carregam entidades por ID em callbacks; em volume alto pode gerar repetição.
- **Severidade baixa**: rotinas debug/admin pontuais com múltiplas queries sem batching (aceitável fora hot-path).

### Quick wins aplicados nesta entrega
- Não houve alteração de código nesta rodada para evitar risco funcional sem benchmark PostgreSQL.
- Quick wins ficam propostos para PR dedicado após coleta de `EXPLAIN ANALYZE`/`pg_stat_statements`.

## Índices existentes importantes
- `notifications`: índices de status/fila + índice parcial `status='sent'` para 24h por wishlist.
- `scrape_jobs`: índices de dequeue/lock/requeue.
- `source_runs`: (`source`,`created_at`) e (`status`,`created_at`).
- `wishlist_tokens`: índice em `token` (matching).
- `wishlist_listing_activity`: unique identidade por wishlist + índice para ativos por recência.

## Candidatos de índice (proposta, sem migration)

### P1 — `system_logs(component, message, created_at desc)`
- Query suportada: heartbeat (`component='scheduler' and message='heartbeat' order by created_at desc`).
- Evidência: usado em admin health/monitor repetidamente.
- Impacto esperado: reduzir custo de varredura em tabela crescente.
- Risco: aumento de escrita em logs.
- Produção: considerar `CREATE INDEX CONCURRENTLY`.

### P1 — `car_listings(url)` (ou hash funcional dependendo padrão)
- Query suportada: tracking resolve por URL em `wishlist_tracking_service`.
- Evidência: lookup direto por URL com `order by created_at desc`.
- Impacto: melhora lookup em tabela grande.
- Risco: índice potencialmente grande; validar seletividade.
- Produção: `CONCURRENTLY`.

### P2 — `source_runs(source, status, created_at desc)`
- Query suportada: admin sources por source + status != skipped / status específicos.
- Evidência: múltiplas consultas por source nos handlers.
- Impacto: possivelmente incremental (já há índices próximos).
- Risco: redundância se planner já usa índices atuais eficientemente.
- Produção: só após EXPLAIN comprovar ganho.

### NÃO FAZER (por ora)
- Índices adicionais em `wishlist_filters(field)` compostos sem evidência de consulta cross-wishlist por field.
- Novos índices em `wishlists(is_active)` isolado (filtro geralmente combinado com usuário/contexto e volume tende baixo).

## Lacunas de evidência operacional
- `TEST_DATABASE_URL` ausente nesta execução: não foi possível rodar lane postgres nem `EXPLAIN ANALYZE` real.
- `pg_stat_statements` não avaliado neste ambiente.
- Conclusões de prioridade de índice são hipóteses técnicas a validar em staging/prod.

## Evidência real coletada nesta execução (2026-05-03)
- Comando executado: `pytest -q -m postgres -rs`.
- Resultado: **1 teste pulado** (`tests/test_alembic_postgres.py`) por ausência de `TEST_DATABASE_URL`.
- Evidência textual do pytest: `requires TEST_DATABASE_URL for PostgreSQL integration tests`.
- `TEST_DATABASE_URL` no ambiente: **não definido** (`<unset>`).
- `psql` client: não encontrado no PATH deste runner (não foi possível abrir sessão SQL manual).

### Impacto na coleta solicitada
Sem `TEST_DATABASE_URL` real apontando para staging/prod (e sem cliente `psql`), **não foi possível** coletar nesta execução:
- maiores tabelas;
- inventário real de índices;
- índices pouco usados (`pg_stat_user_indexes`);
- top queries reais via `pg_stat_statements`;
- `EXPLAIN ANALYZE` dos fluxos críticos (notifications 24h, sender queue, scrape_jobs dequeue, admin health, wishlist summaries, tracking list).

### Reclassificação de candidatos (com evidência atual)
Como não há telemetria/planos reais nesta execução, a classificação precisa permanecer conservadora:
- **P0 aplicar agora:** nenhum.
- **P1 provável:** `system_logs(component, message, created_at desc)` e `car_listings(url)` **continuam hipóteses**, aguardando `EXPLAIN ANALYZE` + `pg_stat_statements`.
- **P2 observar:** `source_runs(source, status, created_at desc)` (potencial redundância com índices existentes).
- **Não fazer (por ora):** novos índices em `wishlist_filters(field)` compostos e `wishlists(is_active)` isolado sem evidência de workload real.

### Recomendação objetiva
**Nenhuma migration agora.** Próximo passo obrigatório é repetir esta fase em ambiente com `TEST_DATABASE_URL` PostgreSQL real (staging/prod) e executar integralmente o roteiro de `docs/DB_REVIEW_SQL.md` antes de propor índice/migration.


## Update 2026-05-04 — Supabase Disk IO Budget (P0)
- Hot query ajustada em `app/services/autopilot_service.py`: removido `GROUP BY component, message`; agregado por `component,event_type,source,level,fingerprint` com `max(message)` como amostra.
- Índices operacionais P0 adicionados via migration `a1b2c3d4e5f6_operational_io_indexes.py` para `system_logs` e `source_runs` com estratégia `CONCURRENTLY` no PostgreSQL.
- Cache TTL curto para `source_configs` implementado em `app/services/source_configs_service.py` (default 60s), com invalidação explícita em mutações admin.
- Script operacional `scripts/cleanup_operational_data.py` criado com dry-run padrão e `--apply` explícito para retenção de logs/eventos/jobs/runs/notificações/activity.
- Diagnóstico de hot paths no código:
  - `/admin health` agrega `scrape_jobs` e `notifications` e faz leituras recentes de `source_runs`/`source_states`.
  - Detector de burst do autopilot consulta `system_logs` por janela temporal.
  - Scheduler/workers usam `source_configs` repetidamente; cache TTL curto reduz SELECTs redundantes no período.
  - Workers de fila consomem `scrape_jobs` em batches de 1 job por tick (sem `SELECT *` em loop aberto contínuo dentro do worker).

### SQLs de validação pós-deploy (obrigatório)
1. Validar queda de custo/tempo das queries quentes:
   ```sql
   select query, calls, total_exec_time, mean_exec_time, rows
   from pg_stat_statements
   where query ilike '%system_logs%'
      or query ilike '%source_runs%'
      or query ilike '%source_configs%'
      or query ilike '%scrape_jobs%'
   order by total_exec_time desc
   limit 20;
   ```
2. Validar uso dos novos índices:
   ```sql
   select relname as table_name, indexrelname as index_name, idx_scan, idx_tup_read, idx_tup_fetch
   from pg_stat_user_indexes
   where indexrelname in (
     'ix_system_logs_created_level_event_type',
     'ix_system_logs_created_source_fingerprint',
     'ix_source_runs_source_created_status'
   )
   order by idx_scan desc;
   ```
3. Validar redução de varredura sequencial:
   ```sql
   select relname, seq_scan, seq_tup_read, idx_scan, n_live_tup
   from pg_stat_user_tables
   where relname in ('system_logs','source_runs','source_configs','scrape_jobs')
   order by seq_tup_read desc;
   ```
4. EXPLAIN da agregação de logs (sem GROUP BY message):
   ```sql
   explain (analyze, buffers)
   select
     component,
     coalesce(event_type,'') as event_type,
     coalesce(source,'') as source,
     coalesce(level,'') as level,
     coalesce(fingerprint,'') as fingerprint,
     max(message) as sample_message,
     count(id) as cnt
   from system_logs
   where created_at >= now() - interval '24 hours'
     and level in ('warn','error')
   group by component, coalesce(event_type,''), coalesce(source,''), coalesce(level,''), coalesce(fingerprint,'')
   order by count(id) desc
   limit 25;
   ```
