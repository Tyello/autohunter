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

## ARCH-05 — Index `ix_notifications_user_sent_today` não confirmado

**Estado atual:** o arquivo `f6a1b2c3d4e5_notifications_sent_at_index.py` existe nas migrations mas não sabemos se é o índice composto correto com `WHERE status='sent'`. `count_sent_today` filtra por `user_id + status='sent' + sent_at range` — sem partial index isso é seq scan em tabela crescente.

**Validar:**

```sql
-- Checar se o índice existe e é o correto
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'notifications'
  AND indexname LIKE '%sent%';
```

**Se não existir como partial index:**

```sql
CREATE INDEX CONCURRENTLY ix_notifications_user_sent_today
ON notifications (user_id, sent_at)
WHERE status = 'sent';
```

**Criar migration:** `xxxx_notifications_partial_sent_at_index.py`

---

## ARCH-06 — Limpeza de scripts órfãos (refactor seguro)

**Estado atual:** `config/raspberry-pi/crontab` já foi migrado para `scripts/cleanup_operational_data.py` e não referencia mais `scripts/cache_manager.py` nem `scripts/database_optimizer.py`.

**Pendência real:** os scripts legados ainda existem no repositório e podem gerar ambiguidade operacional/documental.

**Ação:**
1. Confirmar ausência de import/call no runtime.
2. Remover scripts órfãos com changelog claro.
3. Atualizar documentação de operação para apontar apenas para o fluxo de cleanup operacional vigente.

---

## ARCH-07 — Validar throughput real do sender e ajustar batch/rate limit com segurança

**Estado atual:** `.env.example` já sobe `SCHEDULER_TICK_SECONDS=90`, mas não explicita `NOTIFICATION_SENDER_BATCH_SIZE=50`. Além disso, `settings.py` segue com defaults conservadores voltados a DEV (`notification_sender_batch_size=20`).

**Pendência real:** validar throughput real do sender em produção (picos), e então fixar parâmetros operacionais seguros sem violar rate limit do Telegram.

**Ação:**
1. Medir backlog/latência por janela horária.
2. Definir batch e ritmo de envio (sleep/semafóro) com margem para rate limit.
3. Registrar baseline e limites operacionais no runbook.

---

## ARCH-08 — Alinhar defaults seguros de `settings.py` com baseline Raspberry de produção

**Estado atual:** `.env.example` já recomenda baseline seguro para Raspberry (`PLAYWRIGHT_MAX_CONTEXTS=1`, `PLAYWRIGHT_CONTEXT_TTL_SECONDS=600`, `PLAYWRIGHT_QUEUE_MAX_JOBS=10`), mas `app/core/settings.py` mantém defaults mais agressivos (`playwright_max_contexts=2`, `playwright_context_ttl_seconds=900`, `playwright_queue_max_jobs=25`).

**Pendência real:** reduzir divergência entre fallback de código e baseline operacional para evitar risco em ambientes que não carreguem `.env` esperado.

**Ação:** alinhar defaults internos a perfil seguro de produção Raspberry (ou documentar explicitamente o motivo técnico da divergência).

---

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
| ARCH-05 | Confirmar (ou criar) index parcial de notificações enviadas | Baixo | Seq scan crescente no sender e degradação progressiva |
| ARCH-07 | Validar throughput real do sender e calibrar batch/rate limit | Médio | Backlog e latência de entrega em janelas de pico |
| ARCH-08 | Alinhar defaults seguros de Playwright em `settings.py` | Trivial | Risco de consumo excessivo de RAM em fallback de configuração |

### P1 — Refactor seguro (higiene técnica incremental)

| # | Item | Esforço | Risco de não fazer |
|---|---|---|---|
| ARCH-06 | Limpeza de scripts órfãos (`cache_manager.py`, `database_optimizer.py`) | Baixo | Ambiguidade operacional e manutenção confusa |
| ARCH-03 | Split de handlers admin por domínio | Médio | Arquivo monolítico, alto custo de evolução |

### P2 — Arquitetura de longo prazo

| # | Item | Esforço | Risco de não fazer |
|---|---|---|---|
| ARCH-01 | Split incremental de `source_execution_service.py` | Alto | Acoplamento alto, difícil teste/evolução |
| ARCH-02 | Quebra de `settings` por namespaces de domínio | Alto | Dependências implícitas e menor clareza de configuração |

### Itens concluídos (fora da fila de pendências)

- **ARCH-04**: concluído no código (`session.py` já contempla `max_overflow`, `pool_timeout`, `db_connect_timeout` e exceção adequada para SQLite).
