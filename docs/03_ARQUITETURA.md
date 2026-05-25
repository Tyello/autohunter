# Arquitetura — Melhorias Estruturais
> Gaps identificados após análise do código v2. Foco em resiliência, separação de responsabilidades e operação segura no RPi 4 4GB.

---

## ARCH-01 — `source_execution_service.py` ainda é god object

**Estado atual:** um único serviço concentra elegibilidade, dispatch v1/v2/dual, scraping, ingestão, matching, telemetria, classificação de erro e reconciliação de atividade. Já foi extraído parcialmente (`build_scrape_dispatch`, `build_run_payload` em `source_execution_helpers.py`), mas o método central `run_source_for_all_wishlists` ainda tem ~500 linhas.

**O que fazer — extração incremental:**

```
Etapa 1: extrair _run_single_group(...)
  → recebe grupo de wishlists + URL
  → executa scrape + ingest + match para esse grupo
  → retorna GroupResult
  → sem efeito colateral de telemetria

Etapa 2: extrair _post_run_telemetry(...)
  → recebe GroupResult[]
  → persiste source_runs, telemetry_events, system_logs
  → separado do fluxo de execução

Etapa 3: extrair _reconcile_activity(...)
  → recebe listing_ids vistos neste run
  → marca inativos, atualiza last_seen_at
  → executado após todos os grupos
```

**Critério:** `run_source_for_all_wishlists` delega para sub-funções, não implementa lógica inline.

**Risco:** baixo se feito por etapa, com contrato externo preservado.

---

## ARCH-02 — `settings` como god object

**Estado atual:** `app/core/settings.py` tem ~240 campos cobrindo banco, Playwright, scheduler, Telegram, Mercado Pago, fontes, leilões, admin e feature flags. Qualquer import de settings em qualquer módulo cria dependência implícita no objeto inteiro.

**O que fazer — agrupamento por domínio:**

```python
# Criar namespaces de settings por domínio:
class DBSettings(BaseModel):
    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle: int = 1800

class PlaywrightSettings(BaseModel):
    playwright_max_contexts: int = 2
    playwright_context_ttl_seconds: int = 600

class SchedulerSettings(BaseModel):
    scheduler_tick_seconds: int = 60
    notification_sender_batch_size: int = 20

class Settings(BaseModel):
    db: DBSettings = DBSettings()
    playwright: PlaywrightSettings = PlaywrightSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    # ...
```

Cada módulo importa só o namespace que precisa: `from app.core.settings import settings; settings.db.pool_size`.

**Migração:** incremental. Criar os sub-objetos mantendo acesso flat por compatibilidade via `@property`.

---

## ARCH-03 — `handlers_admin.py` sem separação de domínio

**Estado atual:** handlers de admin misturam: sources, saúde, deploy, usuários, métricas, leilões, Premium, debug — tudo em um arquivo. Qualquer adição cria conflito de contexto.

**O que fazer — split por domínio:**

```
app/bot/
  handlers_admin.py           → roteador principal (só dispatch)
  handlers_admin_sources.py   → /admin sources, runall, warmup
  handlers_admin_health.py    → /admin health, audit, heartbeat
  handlers_admin_users.py     → /admin users, premium, setplan
  handlers_admin_metrics.py   → /admin metrics (novo)
  handlers_admin_deploy.py    → já existe separado ✓
  handlers_admin_auctions.py  → /admin auctions (já existe?)
```

**Critério:** cada arquivo tem no máximo 300 linhas e 1 domínio.

---

## ARCH-04 — Pool SQLAlchemy (concluído) ✅

**Estado verificado:** concluído no código. `app/db/session.py` já passa `max_overflow`, `pool_timeout` e `connect_timeout` (via `db_connect_timeout`) para conexões não-SQLite, com tratamento específico para SQLite sem parâmetros incompatíveis de pool.

**Ação:** remover de pendências ativas. Manter apenas monitoramento normal em produção.

---

## ARCH-05 — Index parcial de notificações enviadas (concluído) ✅

**Estado verificado:** concluído no código. A migration `migrations/versions/f6a1b2c3d4e5_notifications_sent_at_index.py` já cria o índice `ix_notifications_user_sent_today` em Postgres como índice parcial:

```sql
CREATE INDEX ix_notifications_user_sent_today
ON notifications (user_id, sent_at)
WHERE status = 'sent';
```

Para ambientes não-Postgres (ex.: SQLite local/testes), a mesma migration aplica fallback compatível (`user_id, status, sent_at`) para não quebrar execução local.

**Queries protegidas por este índice (limite diário/backlog por usuário):**
- `app/services/limits_service.py::count_sent_today`
- `app/services/limits_service.py::count_notifications_sent_last_n_days`

**Ação:** remover de pendências ativas e manter apenas validação operacional padrão em produção.

---

## ARCH-06 — Limpeza de scripts órfãos (concluído) ✅

**Estado verificado:** `config/raspberry-pi/crontab` usa o fluxo oficial `scripts/cleanup_operational_data.py --apply` e não referencia scripts legados.

**Concluído nesta etapa:**
1. Confirmada ausência de uso real no runtime/testes/operação para `scripts/cache_manager.py` e `scripts/database_optimizer.py`.
2. Scripts legados removidos do repositório para eliminar ambiguidade operacional.
3. Documentação alinhada para manter `scripts/cleanup_operational_data.py` como caminho oficial de limpeza operacional.

---

## ARCH-07 — Calibrar throughput seguro do sender (concluído) ✅

**Estado verificado:** concluído no código e nos testes. O sender real está em `app/scheduler/jobs_send.py::send_queued_notifications`, drenando notificações `queued` via `claim_queued_notifications` e processando `processing` stale com `reclaim_stale_processing_notifications` em `app/services/notification_delivery_service.py`.

**Validação de pacing/rate:**
- `notification_sender_sleep_seconds` é aplicado **entre envios bem-sucedidos** (`time.sleep`) e não roda quando não houve envio real anterior.
- O lote continua controlado por `notification_sender_batch_size` no claim (`claim_queued_notifications`).
- O scheduler mantém ciclo de envio por `SCHED_SENDER_SECONDS=60` (sem mudança).

**Valores finais recomendados para produção:**
- `SCHED_SENDER_SECONDS=60`
- `NOTIFICATION_SENDER_BATCH_SIZE=50` (operacional via `.env`)
- `NOTIFICATION_SENDER_SLEEP_SECONDS=0.04` (~25 envios/s teórico máximo, com pacing explícito)
- `notification_sender_batch_size` interno em `settings.py` permanece `20` como fallback conservador de DEV/bootstrapping.

**Evidência de teste (sender):**
- pacing aplicado entre envios reais e ausente quando há somente 1 envio, falha inicial, bloqueio de limite diário ou ausência de destino (`tests/test_sender_daily_limit.py`).

---

## ARCH-08 — Alinhar defaults seguros de `settings.py` com baseline Raspberry de produção (concluído) ✅

**Estado verificado:** concluído no código. Os defaults internos de Playwright em `app/core/settings.py` agora estão alinhados ao baseline seguro já documentado em `.env.example` para Raspberry Pi 4GB.

**Valores finais alinhados (fallback/default):**
- `playwright_max_contexts=1`
- `playwright_context_ttl_seconds=600`
- `playwright_queue_max_jobs=10`

**Observações de contrato preservado:**
- Defaults continuam sobrescrevíveis por variáveis de ambiente.
- `source_configs`/DB continuam determinando quando cada source usa browser; esta mudança apenas reduz risco no fallback quando `.env` estiver incompleto/ausente.


## Estado verificado em código

Arquivos conferidos nesta revisão documental:

- `app/db/session.py`
- `app/core/settings.py`
- `.env.example`
- `config/raspberry-pi/crontab`
- `scripts/cache_manager.py`
- `scripts/database_optimizer.py`
- `app/services/source_execution_service.py`
- `app/bot/handlers_admin.py`
- `app/bot/admin_handlers_sources.py`

---

## Prioridade

### P0 — Operacional (estabilidade/risco imediato)

| # | Item | Esforço | Risco de não fazer |
|---|---|---|---|

### P1 — Refactor seguro (higiene técnica incremental)

| # | Item | Esforço | Risco de não fazer |
|---|---|---|---|
| ARCH-03 | Split de handlers admin por domínio | Médio | Arquivo monolítico, alto custo de evolução |

### P2 — Arquitetura de longo prazo

| # | Item | Esforço | Risco de não fazer |
|---|---|---|---|
| ARCH-01 | Split incremental de `source_execution_service.py` | Alto | Acoplamento alto, difícil teste/evolução |
| ARCH-02 | Quebra de `settings` por namespaces de domínio | Alto | Dependências implícitas e menor clareza de configuração |

### Itens concluídos (fora da fila de pendências)

- **ARCH-04**: concluído no código (`session.py` já contempla `max_overflow`, `pool_timeout`, `db_connect_timeout` e exceção adequada para SQLite).
- **ARCH-06**: concluído com remoção de `scripts/cache_manager.py` e `scripts/database_optimizer.py`; operação oficial permanece em `scripts/cleanup_operational_data.py` via `config/raspberry-pi/crontab`.
- **ARCH-08**: concluído com alinhamento dos defaults internos de Playwright ao baseline Raspberry (`playwright_max_contexts=1`, `playwright_context_ttl_seconds=600`, `playwright_queue_max_jobs=10`) mantendo override por env e decisão de uso por source via `source_configs`/DB.
- **ARCH-07**: concluído com validação do sender real (`jobs_send` + `notification_delivery_service`), pacing via `NOTIFICATION_SENDER_SLEEP_SECONDS=0.04`, batch operacional recomendado `NOTIFICATION_SENDER_BATCH_SIZE=50` em `.env.example` e `SCHED_SENDER_SECONDS=60` preservado.
