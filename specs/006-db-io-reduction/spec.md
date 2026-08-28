# 006 — Redução de I/O no Postgres/Supabase (scheduling overhead, cache, logging, writes redundantes)

`[spec-kit: T3 — 9pts: arquivos=2 (5+), decisões=2, risco=2, novidade=1, verif=2]`

Origem: relatório "Query Performance" (Supabase, slow queries), 2026-08-27. Continuação de [[002-operational-io-cleanup]] (retenção/batch de limpeza) e do "Prompt 1" mencionado pelo usuário sobre Disk IO Budget.

## Objetivo

Reduzir o volume de chamadas/tempo das queries de maior impacto identificadas no relatório, sem regressão funcional, medindo antes/depois de cada mudança e validando item por item (não tudo de uma vez).

## Não-objetivos

- Não mexer nos jobs de baixa frequência que já fazem sentido no jobstore persistente do APScheduler (FIPE mensal, digest semanal, cleanup 6h, heartbeat) — só os workers de fila de alta frequência saem do jobstore.
- Não mexer nas tabelas protegidas (`notifications`, `wishlist_listing_activity`) nem no script break-glass `scripts/cleanup_operational_data.py` — fora de escopo, coberto por guardrail de trigger.
- Não migrar o `BackgroundScheduler` (sync) para `AsyncIOScheduler` — troca desnecessária de paradigma para o que este spec resolve.
- Não implementar plataforma de observabilidade nova — apenas reduzir volume do que já existe (`system_logs`).
- Item 6 (COPY de backup) é investigativo/informativo nesta spec — mudança de frequência/formato de backup é decisão operacional do usuário, não decidida aqui.

## Decisões tomadas

- **D-01**: `job_browser_queue_worker` e os `job_http_queue_worker` (2 instâncias, `scheduler_http_worker_count`) saem do APScheduler (`sched.add_job(..., "interval", ...)`) e passam a rodar em threads daemon próprias, com seu próprio loop `while not is_shutdown_requested(): fn(); shutdown_event.wait(seconds)`. Isso elimina os `UPDATE apscheduler_jobs` de bookkeeping desses 3 jobs (5s + 2×2s = maior contribuinte de volume do relatório) sem tocar nos demais jobs do jobstore persistente.
- **D-02**: as duas funções `_get_cfg` (locais, SELECT direto em `app/scheduler/run.py:58` e `app/services/source_execution_service.py`) são substituídas por `get_source_config_snapshot(db, source)` (`app/services/source_configs_service.py`), que já tem cache TTL (`source_config_cache_ttl_seconds`, default 60s) e invalidação por evento em todo write-path. `SourceConfigSnapshot` já expõe todos os atributos usados no hot path (`proxy_server`, `force_browser`, `browser_fallback_enabled`, `is_enabled`, `sched_minutes`, `rate_limit_seconds`, `cooldown_minutes`, `extra`) — substituição é 1:1, sem mudança de comportamento downstream.
- **D-03**: `job_browser_queue_worker` para de inserir em `system_logs` no caminho de sucesso (`"job_completed"`, info) — o resultado do job já é durável e consultável em `scrape_jobs` via `mark_done`/`mark_failed`. Mantém logs de erro/exceção. Alinha com `job_http_queue_worker`, que já não loga sucesso.
- **D-04**: `updated_at` em `car_listings` só é bumpado quando pelo menos um dos demais campos do `ON CONFLICT DO UPDATE SET` realmente muda de valor (comparação via `IS DISTINCT FROM` entre o valor computado e o valor atual da linha), em vez de `func.now()` incondicional a cada conflito.
- **D-05** (Fase 2, gated): item 3 (DELETE de limpeza) não tem mudança de código decidida ainda — vai para uma etapa investigativa (`EXPLAIN ANALYZE`) antes de qualquer fix, porque a limpeza já roda em lotes de 1000 com commit por lote (implementado em [[002-operational-io-cleanup]]) e as 3 tabelas (`system_logs`, `telemetry_events`, `source_runs`) já têm índice com `created_at` como coluna líder (`ix_system_logs_created_at`, `ix_telemetry_events_created_at`, `ix_source_runs_created_status`). "Reescrever sem subquery" do pedido original não é aplicável — `DELETE ... WHERE id IN (SELECT ... LIMIT)` é o único jeito idiomático de fazer `DELETE` com `LIMIT` em Postgres.
- **D-06**: item 6 (COPY) é só investigação + relato nesta spec (origem confirmada: `pg_dump` via `scripts/backup_db.sh`, cron do SO, não é código nosso agendado via APScheduler) — decisão de mudar frequência/formato fica com o usuário.

## Premissas assumidas

- **PREM-01**: a medição "antes/depois" é feita pelo usuário no painel Supabase "Query Performance" (registrar os números atuais antes de cada fase, comparar depois do deploy). Este agente não tem acesso direto ao Supabase de produção — não executa a medição, só documenta o checklist.
- **PREM-02**: escopo do item 1 inclui `http_queue_worker` além de `browser_queue_worker` (confirmado com o usuário) — mesmo padrão, mesma causa raiz, maior contribuinte de volume ainda (2 jobs × 2s vs 1 job × 5s).
- **PREM-03**: a Fase 2 (itens 3–6) só é executada depois que o usuário validar os números de Fase 1 (itens 1–2) no Supabase — gate explícito, não automático.

## Plano de testes (Fase 1)

- `tests/test_scheduler_shutdown.py` — deve continuar passando; graceful shutdown precisa parar as novas threads (não só `sched.pause()/shutdown()`).
- Novo: `tests/test_scheduler_worker_threads.py` — cobre `start_worker_thread`/`stop_worker_threads`: thread chama `fn()` repetidamente respeitando o intervalo, para quando `request_shutdown()` é chamado, `stop_worker_threads(timeout=...)` faz join sem pendurar o processo.
- `tests/test_browser_queue_job_session_lifecycle.py`, `tests/test_scheduler_suppressed_instrumentation.py` — não podem quebrar (job em si não muda, só quem o dispara).
- `tests/test_source_configs_cache.py`, `tests/test_source_execution_service.py`, `tests/test_scheduler_source_config_bootstrap.py` — devem continuar passando após troca de `_get_cfg` por `get_source_config_snapshot`; adicionar teste que comprova que `run_source_for_all_wishlists` não faz mais um SELECT direto em `source_configs` por chamada (usa cache dentro do TTL).
- Novo: teste em `tests/test_car_listings_repo_bulk_homogenize.py` (ou arquivo próprio) — upsert do mesmo listing sem nenhum campo diferente não altera `updated_at`; upsert com um campo diferente (ex. preenche `year` que estava nulo) bump `updated_at`.
- Novo/ajuste em log de sucesso do browser worker — teste que confirma que `job_browser_queue_worker` não chama `log(..., "info", ..., "job_completed", ...)` mais no caminho feliz (grep de chamadas em `tests/test_browser_queue_job_session_lifecycle.py` ou novo teste dedicado).

## Requisitos (EARS)

- **REQ-001**: Quando o processo do scheduler inicia, o sistema DEVE rodar `job_browser_queue_worker` e os `job_http_queue_worker` fora do jobstore persistente do APScheduler (thread própria), preservando o intervalo configurado (`scheduler_browser_worker_seconds`, `scheduler_http_worker_seconds`) e a semântica de não sobrepor execuções (equivalente a `max_instances=1`).
- **REQ-002**: Quando o processo recebe `SIGTERM`/`SIGINT` (via `request_shutdown`), o sistema DEVE parar essas threads e aguardar o join (com timeout) antes do processo encerrar, sem deixar thread órfã.
- **REQ-003**: Quando `run_source_for_all_wishlists` (ou o tick de scheduler em `app/scheduler/run.py`) precisa da config de uma source, o sistema DEVE ler do cache TTL existente (`get_source_config_snapshot`) em vez de fazer `SELECT` direto em `source_configs`.
- **REQ-004**: Quando `job_browser_queue_worker` conclui um job com sucesso, o sistema NÃO DEVE inserir um registro em `system_logs` para esse evento (mantém inserção em caso de erro/exceção).
- **REQ-005**: Quando um upsert de `car_listings` via `ON CONFLICT DO UPDATE` não resulta em nenhum valor de coluna efetivamente diferente do que já está na linha, o sistema NÃO DEVE alterar `updated_at`.
- **REQ-006** (Fase 2, gated por PREM-03): Quando a Fase 1 for validada, o sistema DEVE produzir um relatório `EXPLAIN (ANALYZE, BUFFERS)` das 3 queries de `DELETE` de limpeza antes de qualquer mudança de índice/batch nelas.

## Etapas — Fase 1 (prioridade: itens 1 e 2)

### Etapa 1 — Baseline de medição (documentação, sem código)
**Toca**: nenhum arquivo de código; escrever checklist em `specs/006-db-io-reduction/BASELINE.md`.
**Faz**: listar as 6 queries do relatório com contagem/tempo atuais informados pelo usuário nesta conversa, e um checklist de "antes de cada fase, anote os números atuais no painel Query Performance do Supabase; depois do deploy, espere pelo menos 1h de tráfego e compare".
**Valida com**: arquivo criado, revisão visual do usuário.
**Risco**: nenhum (T0, sem escalação).

### Etapa 2 — Helper de thread de intervalo `[sensível]`
**Toca**: novo arquivo `app/scheduler/worker_threads.py`.
**Faz**: implementar `start_worker_thread(fn: Callable[[], None], *, seconds: int, name: str) -> threading.Thread` (loop `while not is_shutdown_requested(): try: fn() except Exception: log via _log_suppressed_exception-style helper; if shutdown_state aguarda `seconds` via evento (não `time.sleep` cego, para reagir rápido ao shutdown) — reaproveitar `app.core.shutdown.is_shutdown_requested`/o evento interno já usado em `tests/test_scheduler_shutdown.py` (`shutdown_state._shutdown_event`). Expor também `stop_worker_threads(timeout: float = 10.0) -> None` que faz join em todas as threads registradas (lista módulo-level) e `WORKER_THREADS: list[threading.Thread]`.
**Valida com**: `tests/test_scheduler_worker_threads.py` (novo) — thread chama `fn` 2x+ dentro do intervalo esperado num teste com `seconds` pequeno e `fn` instrumentada; após `request_shutdown()`, a thread para de chamar `fn` e `stop_worker_threads()` retorna sem timeout.
**Condição de escalação**: se `app.core.shutdown` não expuser um `threading.Event` reutilizável (só booleano simples), escalar — decisão de adicionar evento novo ao módulo de shutdown é de design, não mecânica.

### Etapa 3 — Migrar `browser_queue_worker` e `http_queue_worker` para as threads `[sensível]`
**Toca**: `app/scheduler/run.py` (dentro de `start_scheduler()`), `app/cli/run_scheduler.py`, `app/scheduler/cli.py`.
**Faz**: remover os `sched.add_job(job_browser_queue_worker, "interval", ..., id="browser_queue_worker", ...)` e o(s) `sched.add_job(job_http_queue_worker, ...)` (loop de `scheduler_http_worker_count` instâncias); substituir por chamadas a `start_worker_thread(...)` com os mesmos intervalos (`scheduler_browser_worker_seconds`, `scheduler_http_worker_seconds`) dentro de `start_scheduler()`, antes do `return sched`. Em `app/cli/run_scheduler.py` e `app/scheduler/cli.py`, no bloco de shutdown (depois de `sched.shutdown(wait=True)` / `sched.shutdown(wait=False)`), chamar `stop_worker_threads(timeout=10)`.
**Valida com**: `tests/test_scheduler_shutdown.py` (todos os testes existentes continuam passando), `tests/test_browser_queue_job_session_lifecycle.py`, `tests/test_scheduler_suppressed_instrumentation.py`, `tests/test_http_worker_registration.py` (ou equivalente, se existir — grep por "http_queue_worker" em `tests/`) continuam passando; teste manual: rodar `python -m app.scheduler.cli` localmente e confirmar via log que os workers ainda processam jobs da fila.
**Condição de escalação**: se algum teste existente depender explicitamente de `browser_queue_worker`/`http_queue_worker_N` como job IDs do APScheduler (ex. checando `sched.get_jobs()`), escalar — decidir se o teste deve ser atualizado ou se o ID precisa ser preservado em outro lugar.

### Etapa 4 — Trocar `_get_cfg` por `get_source_config_snapshot`
**Toca**: `app/scheduler/run.py` (função `_get_cfg`, linha 58, e seu único call site), `app/services/source_execution_service.py` (função `_get_cfg` local e seu call site dentro de `run_source_for_all_wishlists`).
**Faz**: substituir `cfg = _get_cfg(db, src)` por `cfg = get_source_config_snapshot(db, src)` (importar de `app.services.source_configs_service`); remover as definições locais de `_get_cfg` se, após a troca, não tiverem mais nenhum call site (confirmar via grep antes de apagar).
**Valida com**: `tests/test_source_configs_cache.py`, `tests/test_source_execution_service.py`, `tests/test_scheduler_source_config_bootstrap.py`. Adicionar um teste que, com TTL de cache ativo, chama `run_source_for_all_wishlists` 2x seguidas para a mesma source dentro do TTL e confirma que só houve 1 SELECT em `source_configs` (via contagem de queries/monkeypatch no `get_source_config_snapshot` ou spy no `db.execute`).
**Condição de escalação**: se algum atributo usado via `cfg.<x>` no hot path não existir em `SourceConfigSnapshot` (checar todo uso de `cfg.` nos dois arquivos, não só os já confirmados), escalar — decisão de estender o snapshot é de schema/design.

### Etapa 5 — Remover log de sucesso do `browser_queue_worker`
**Toca**: `app/scheduler/browser_queue_job.py` (chamada `_log_best_effort(..., "info", "browser_queue_worker", "job_completed", ...)` no caminho de sucesso).
**Faz**: remover essa chamada específica de log de sucesso, mantendo intactas as chamadas de log em caminhos de erro/exceção/shutdown_suppressed.
**Valida com**: `tests/test_browser_queue_job_session_lifecycle.py` — ajustar/confirmar que não há mais asserção esperando o evento `"job_completed"` em sucesso; se algum teste hoje depende desse log, atualizar o teste para refletir o novo comportamento (o resultado do job continua rastreável via `scrape_jobs`).
**Condição de escalação**: nenhuma esperada — mudança mecânica de 1 linha. Se um teste depender do log para outra finalidade (ex. alerta downstream que lê `system_logs`), escalar.

### Etapa 6 — `car_listings.updated_at` condicional
**Toca**: `app/repositories/car_listings_repo.py` (dict `SET` do `ON CONFLICT DO UPDATE`, função de upsert em massa, por volta da linha 360-419).
**Faz**: para cada chave do dict `SET` exceto `updated_at`, construir `<expressão_já_existente_para_a_coluna>.is_distinct_from(CarListing.<coluna>)`; combinar todas com `OR` numa variável `changed`; trocar `"updated_at": func.now()` por `"updated_at": case((changed, func.now()), else_=CarListing.updated_at)`. Reaproveitar literalmente as expressões já escritas no dict (não recalcular a lógica de cada campo) — é comparação do valor computado contra o valor atual da linha, não uma nova regra de negócio.
**Valida com**: novo teste em `tests/test_car_listings_repo_bulk_homogenize.py` (ou arquivo dedicado `tests/test_car_listings_repo_updated_at.py`) — 2 casos: (a) upsert do mesmo listing com todos os campos idênticos → `updated_at` não muda; (b) upsert com pelo menos 1 campo preenchendo um `NULL` (ex. `year`) ou `url` diferente → `updated_at` atualizado para o novo `now()`. Rodar também `tests/test_car_listings_repo_controlled_fields.py` e `tests/test_car_listings_repo_fallback.py` para confirmar que não há regressão nos demais campos.
**Condição de escalação**: se a expressão combinada (OR de ~18 `is_distinct_from`) gerar SQL inválido ou erro de tipo no Postgres (ex. campos JSON como `raw_payload`/`extra` não suportam `IS DISTINCT FROM` diretamente), escalar — decisão de excluir esses campos da comparação ou usar cast é de design.

## Gate pós-Fase 1

Após etapas 1–6 e revisão, **parar** e pedir ao usuário para: (a) fazer deploy, (b) aguardar tráfego real, (c) reabrir o painel Query Performance do Supabase e comparar os números das 3 queries afetadas (apscheduler_jobs UPDATE, source_configs SELECT, system_logs INSERT) contra o baseline da Etapa 1. Só prosseguir para a Fase 2 (itens 3–6 do pedido original) com confirmação explícita do usuário.

## Etapas — Fase 2 (gated, itens 3 e 6 do relatório original)

### Etapa 7 — Investigação `EXPLAIN ANALYZE` das queries de limpeza (sem mudança de código)
**Toca**: nenhum código de produção; script auxiliar `scripts/explain_cleanup_queries.py` (novo, read-only, roda os 3 `EXPLAIN (ANALYZE, BUFFERS)` das queries de `unprotected_cleanup_rules()` contra o banco configurado em `DATABASE_URL` e imprime o plano).
**Faz**: gerar o script e as instruções de uso; usuário roda contra o banco (idealmente staging, não produção, dado que `ANALYZE` executa a query de verdade) e cola o resultado de volta.
**Valida com**: script roda sem erro localmente contra um banco de teste com dados sintéticos antigos (`created_at` no passado).
**Decisão de fix (index/batch/nenhum)**: só tomada depois do resultado do `EXPLAIN`, como etapa FIX-V separada — não especificada agora para não adivinhar.

### Etapa 8 — Relato da origem do COPY (informativo)
**Toca**: nenhum código; relatar ao usuário, com base na investigação já feita nesta sessão, que os `COPY` do relatório vêm de `pg_dump` (`scripts/backup_db.sh`), agendado via cron do SO (`config/raspberry-pi/crontab`), não via APScheduler — e perguntar se o usuário quer mudar frequência/formato (decisão dele, fora do escopo mecânico desta spec).

## Checklist de fechamento

- [ ] Todos os REQ-001 a REQ-005 (Fase 1) têm evidência arquivo:linha + teste passando.
- [ ] `PREM-01`, `PREM-02`, `PREM-03` registradas e respeitadas (gate humano antes da Fase 2).
- [ ] Nenhuma mudança na Fase 1 tocou tabelas protegidas ou o script break-glass.
- [ ] RUN.md atualizado a cada etapa concluída/escalada.
