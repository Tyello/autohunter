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

## ARCH-04 — Pool SQLAlchemy: `max_overflow` ausente

**Estado atual:** `settings.py` tem `db_pool_size=5` e `db_max_overflow=5`, mas o `session.py` ainda usa:

```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    pool_recycle=settings.db_pool_recycle,
    pool_timeout=settings.db_pool_timeout,
)
```

`max_overflow` não está sendo passado. Com 100 usuários simultâneos, o pool pode saturar silenciosamente.

**Correção em `app/db/session.py`:**

```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,   # ← ADICIONAR
    pool_recycle=settings.db_pool_recycle,
    pool_timeout=settings.db_pool_timeout,
    connect_args={"connect_timeout": 10},     # ← ADICIONAR
)
```

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

## ARCH-06 — `scripts/cache_manager.py` e `scripts/database_optimizer.py` ainda existem

**Estado atual:** referenciados em `config/raspberry-pi/crontab` mas sem integração real ao runtime. Risco de confusão operacional.

**Ação:** verificar se o crontab ainda referencia esses arquivos. Se sim, substituir por `scripts/cleanup_operational_data.py` (que já existe e está integrado). Depois remover os dois scripts.

```bash
grep -r "cache_manager\|database_optimizer" /home/claude/autohunterv2/config/
```

---

## ARCH-07 — `notification_sender_batch_size=20` baixo para 100 usuários

**Estado atual:** com 100 usuários × 5 alertas/dia = 500 notificações/dia. Batch de 20 = 25 ciclos para drenar. Se o scheduler roda a cada 60s e o sender roda a cada ciclo, o backlog não drena rápido o suficiente em horários de pico.

**Ajustar `.env`:**

```env
NOTIFICATION_SENDER_BATCH_SIZE=50
SCHEDULER_TICK_SECONDS=90
```

**Cuidado com rate limit do Telegram:** ~30 mensagens/segundo. Com batch 50 em sequência síncrona, adicionar sleep de 33ms entre envios ou usar asyncio gather com semáforo.

---

## ARCH-08 — Playwright com `max_contexts=2` no RPi (risco de RAM)

**Estado atual:** `playwright_max_contexts=2` no settings. Cada contexto Chromium consome ~150–250MB. Com 2 contextos simultâneos = ~400MB só de browser, em um RPi com 4GB compartilhado com PostgreSQL, bot e scheduler.

**Ajustar para produção com 100 usuários:**

```env
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_CONTEXT_TTL_SECONDS=600
PLAYWRIGHT_QUEUE_MAX_JOBS=10
```

Com `max_contexts=1`, sources browser rodam em série, não em paralelo. É mais lento mas mais seguro para o RPi.

---

## Prioridade

| # | Item | Esforço | Risco de não fazer |
|---|---|---|---|
| ARCH-04 | `max_overflow` no pool SQLAlchemy | Trivial (1 linha) | Pool satura silenciosamente com 100 usuários |
| ARCH-05 | Confirmar index `sent_at` partial | Baixo | Seq scan crescente no sender |
| ARCH-08 | `max_contexts=1` no Playwright | Trivial | OOM no RPi sob carga |
| ARCH-07 | Batch sender 50 + tick 90s | Trivial | Backlog não drena rápido |
| ARCH-06 | Remover scripts órfãos | Baixo | Confusão operacional |
| ARCH-01 | Split source_execution_service | Alto | Manutenção cara, bugs escondidos |
| ARCH-03 | Split handlers_admin | Médio | Conflitos em adições futuras |
| ARCH-02 | Settings por namespace | Alto | Baixo impacto imediato, alto de longo prazo |
