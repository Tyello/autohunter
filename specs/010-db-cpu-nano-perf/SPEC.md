# SPEC 010 — Redução de carga no Postgres (Supabase Free / Nano)

[spec-kit: T3 — 9pts: arquivos=5+, decisões=2, risco=2, novidade=0, verif=2]
Branch: `perf/db-cpu-nano-optimizations`. Skill base: `ai/skills/tdd.md` + `docs/DATABASE_SCHEMA.md` + `docs/DB_GUARDRAILS.md`.

## Contexto (fatos medidos em produção em 2026-11-06)
- Supabase Free, compute Nano (CPU compartilhada, 0.5 GB), disco 1 GB, banco 285 MB. Backup diário no Pi (`/etc/cron.d/autohunter`, 02:00 local, retenção 14d) validado.
- `count()` de obsoletos em `car_listings` (OLX, `inactive_reconcile.mode=dry_run`): 116 chamadas, média 4,8 s.
- `system_logs`: 25 MB de heap e 105 MB de índices (pkey ~1379 B/linha = bloat).
- `pipeline_summary` gravado 2x (system_logs + telemetry_events); **nenhum leitor** fora de `app/scheduler/jobs.py`.
- Upsert de `car_listings` reescreve toda linha vista a cada run (2,2M updates / 26 mil inserts; 31% não-HOT).
- Polling de fila ~1,2 ciclos/s (2 workers http a cada 2 s + browser a cada 5 s), ~3 queries/ciclo mesmo com fila vazia.
- Honestidade de escala: o tempo absoluto de DB somado é pequeno (~poucos milhares de s em 18 dias). Ganho esperado é **moderado**; a lentidão é dominada por picos em CPU burstável.

## Autorizações do usuário (2026-11-06)
- DDL em produção: autorizado (índices; `REINDEX CONCURRENTLY` fora de tabela protegida).
- OLX `inactive_reconcile.mode`: `on` (decisão do usuário; executar só DEPOIS do código das etapas 1 e 5 em produção e backup novo).
- Janela de throttle de `last_seen_at`: **30 minutos**.

## Não-objetivos
- Não mexer em tabelas protegidas (`DB_GUARDRAILS.md`), billing, leilões, gates de notificação.
- Não trocar role `postgres`, não mexer em Supabase/painel, não alterar `.env` de produção.
- Não alterar o contrato de retorno de `insert_ignore_duplicates_return_ids`.

## Decisões travadas
- D1: `count()` passa a ser `db.query(func.count(CarListing.id)).filter(...).scalar()`.
- D2: índice parcial `ix_car_listings_source_last_seen_active` em `car_listings (source, last_seen_at) WHERE status = 'ativo'`.
- D3: throttle via `DO UPDATE ... WHERE (changed OR last_seen_at < now-30min OR status IS DISTINCT FROM 'ativo')`. Como `RETURNING` omite linhas puladas, o repo adiciona `source, external_id` ao RETURNING e busca por SELECT os ids das linhas puladas, mantendo `ids/upserted/updated/inserted_new` idênticos ao contrato atual (`upserted` = total de linhas distintas de entrada).
- D4: `reconcile_search_presence` só atualiza linhas vistas cujo estado realmente muda (`last_seen_search_key` diferente, `missing_runs_count != 0` ou `status = 'inativo'`).
- D5: polling adaptativo — `start_worker_thread` aceita `max_idle_seconds`; se `fn()` retorna exatamente `False` (ocioso) o intervalo cresce (`seconds * 2^streak`, teto `max_idle_seconds`); qualquer outro retorno (inclusive `None`) mantém o comportamento atual. Workers http/browser passam a retornar `False` quando a fila está vazia e `True` quando processaram job. Tetos: http 10 s, browser 15 s.
- D6: `pipeline_summary`/`pipeline_summary_many` mantêm `emit_event` (telemetry_events, estruturado) e deixam de persistir em `system_logs`; o espelho em stdout (journalctl) é preservado via novo parâmetro `persist: bool = True` em `log()`.
- D7: autopilot `_candidate_blocked_spike` usa **uma** query para janela+baseline (conditional aggregation), mesmo resultado.
- D8 (REVISADA 2026-11-06): migration Alembic cria D2 e remove SOMENTE `car_listings_updated_at_idx` (única query que ordena por updated_at, `cross_source_dedupe_service.py:100`, filtra antes por fingerprint, <=8 linhas) e `idx_car_listings_status_active` (redundante com `car_listings_status_idx`, 0 scans), com `CONCURRENTLY` em `autocommit_block`. `idx_car_listings_location_trgm` é MANTIDO: `search_service.py:200` usa `location ILIKE` na busca manual do usuário; os 0 scans refletem tabela pequena (34k linhas), não inutilidade.
- D10 (2026-11-06): o teste pré-existente `tests/test_car_listings_repo_updated_at.py::test_last_seen_at_updates_without_changing_updated_at` codifica o contrato antigo (last_seen_at avança a cada upsert) e é REESCRITO para o novo contrato da janela de 30 min (decisão do usuário): upsert idêntico dentro de 30 min NÃO avança last_seen_at nem updated_at; após 30 min (forçado por UPDATE direto no teste) avança last_seen_at e updated_at permanece. Esse arquivo passa a constar em TOCA da etapa 5.
- D9: `REINDEX INDEX CONCURRENTLY` de `system_logs_pkey`, `ix_system_logs_component_message_created_at`, `ix_system_logs_created_component` é manual, pós-backup, fora da migration.

## Requisitos (EARS)
- REQ-001: Quando `mark_stale_listings_inactive`/`reconcile_search_presence` contarem candidatos em dry-run, o sistema deve usar `count(CarListing.id)` direto, sem subquery com todas as colunas.
- REQ-002: Quando um listing é visto de novo com `last_seen_at` < 30 min e `status='ativo'` e nenhum campo mudou, o upsert não deve gravar a linha.
- REQ-003: O upsert deve continuar retornando em `ids` todos os listings de entrada (inseridos, atualizados ou pulados) e `inserted_new` deve contar só os inseridos.
- REQ-004: Se o listing está `inativo` ou `last_seen_at` ≥ 30 min, o upsert deve atualizar `last_seen_at` e `status='ativo'`.
- REQ-005: `reconcile_search_presence` não deve reescrever linhas já com a mesma `last_seen_search_key`, `missing_runs_count=0` e `status` ativo; deve continuar reativando `inativo` e zerando contagem.
- REQ-006: Workers http/browser devem retornar `False` quando ociosos e `start_worker_thread` deve aumentar o intervalo até o teto e voltar ao intervalo base após um job.
- REQ-007: `pipeline_summary*` não deve inserir linha em `system_logs`, mas deve continuar emitindo `telemetry_events` e stdout conforme `log_stdout_always_messages`.
- REQ-008: `_candidate_blocked_spike` deve executar 1 query agregada e produzir os mesmos candidatos que a versão de 2 queries.
- REQ-009: Migration deve criar o índice D2 e dropar os 2 índices do D8 revisada (`car_listings_updated_at_idx`, `idx_car_listings_status_active`; `location_trgm` é mantido), com `downgrade` reversível.
- REQ-010: `docs/DATABASE_SCHEMA.md` regenerado e modelos alinhados com a migration.

## Etapas
| # | REQs | Arquivos | Sensível | Valida com |
|---|---|---|---|---|
| 1 | 001 | `app/services/listing_presence_service.py` (apenas count) + `tests/test_listing_presence_service.py` | não | pytest do arquivo |
| 2 | 006 | `app/scheduler/worker_threads.py`, `http_queue_job.py`, `browser_queue_job.py` + testes novos | não | pytest dos testes novos + `test_browser_queue_job_session_lifecycle.py` |
| 3 | 008 | `app/services/autopilot_service.py` + `tests/test_autopilot_*.py` | não | `pytest tests/test_autopilot_*.py` |
| 4 | 007 | `app/services/system_logs_service.py`, `app/scheduler/jobs.py` + `tests/test_system_logs_stdout_level.py` | não | pytest dos testes de logs e de jobs relacionados |
| 5 | 002-005 | `app/repositories/car_listings_repo.py`, `app/services/listing_presence_service.py` (UPDATE de reconcile) + testes | **sim** (contrato de ingestão) | testes de repo/presence/pipeline + suíte de ingestão |
| 6 | 009-010 | `migrations/versions/<novo>.py`, models, `docs/DATABASE_SCHEMA.md` | **sim** (DDL) | `alembic upgrade head` em SQLite/PG de teste, `alembic downgrade -1`, grep de dependências |
| 7 | — | operação em produção (manual, com o usuário): backup novo → deploy → migration → REINDEX → `mode: on` | **sim** | checagens SQL pós-operação |

Ordem: 1, 2, 3, 4 em paralelo (arquivos disjuntos); depois 5 (toca `listing_presence_service.py` como a 1); depois 6; 7 por último.

## Condições de escalação (todas as etapas)
- Arquivo/função citada não existe ou assinatura difere.
- Teste existente quebra por motivo que não seja a mudança prevista.
- Etapa 5: qualquer consumidor de `insert_ignore_duplicates_return_ids` depender de ordem ou de `ids` só de linhas gravadas.
- Etapa 6: grep achar uso de `location ILIKE`/ordenação por `updated_at` que dependa dos índices a dropar.

## Premissas assumidas
- PREM-01: janela de 30 min é suficiente para `stale_days=30` e `initial_backfill` (checado: só usa cutoff em dias).
- PREM-02: nenhum job lê `pipeline_summary` de `system_logs` (grep em app/scripts/tests/docs: nenhum leitor).
- PREM-03: `mode: on` do OLX vai marcar ~14 mil anúncios como `inativo` (86% dos "ativos" não são vistos há 30+ dias); reversível pelo upsert, que devolve `ativo`.
