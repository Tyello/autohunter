# Arquitetura — Melhorias Estruturais

Atualizado em: 2026-05-25.  
Estado confrontado com a `main` após a entrada de `/admin metrics`.

> Roadmap estrutural do AutoHunter após confronto com o código real.  
> Foco: resiliência, separação de responsabilidades, operação segura no Raspberry Pi 4GB e evolução incremental sem reescrita arriscada.

---

## Estado atual do roadmap

### Concluído / não reabrir

- **ARCH-03 fase 1:** `/admin health`, `/admin audit` e `/admin errors` extraídos para `app/bot/admin_handlers_health.py`.
- **ARCH-03 fase 2A:** `/admin dedupe` e `/admin tracking` extraídos para `app/bot/admin_handlers_diagnostics.py`.
- **ARCH-03 fase 2B:** `/admin digest` extraído para `app/bot/admin_handlers_digest.py`.
- **ARCH-03 fase 3A:** `/admin fipe` extraído para `app/bot/admin_handlers_fipe.py`.
- **ARCH-03 fase 3B parcial:** `/admin metrics` extraído para `app/bot/admin_handlers_metrics.py`.
- **ARCH-04:** pool SQLAlchemy com `max_overflow`, `pool_timeout`, `db_connect_timeout` e tratamento específico para SQLite.
- **ARCH-05:** índice parcial de notificações enviadas confirmado por migration e validação PostgreSQL/Supabase.
- **ARCH-06:** remoção dos scripts órfãos `scripts/cache_manager.py` e `scripts/database_optimizer.py`.
- **ARCH-07:** sender validado com batch operacional e pacing configurável.
- **ARCH-08:** defaults seguros de Playwright alinhados ao baseline Raspberry.

### Ainda pendente

- Concluir o split dos domínios ainda dentro de `app/bot/handlers_admin.py`.
- Quebrar incrementalmente `app/services/source_execution_service.py`.
- Preparar `app/core/settings.py` para namespaces por domínio mantendo compatibilidade flat.

---

## ARCH-01 — `source_execution_service.py` ainda é god object

**Estado atual:** `run_source_for_all_wishlists` ainda concentra elegibilidade, dispatch v1/v2/dual, scraping, ingestão, matching, telemetria, classificação de erro, backoff e reconciliação de atividade. Já existe extração parcial em `source_execution_helpers.py`, mas o método central segue grande e sensível.

**Extração incremental recomendada:**

```text
Etapa 1: extrair _run_single_group(...)
  → recebe grupo de wishlists + URL
  → executa scrape + ingest + match para esse grupo
  → retorna GroupExecutionResult / RunTotals
  → preserva contrato externo de run_source_for_all_wishlists

Etapa 2: extrair _post_run_telemetry(...)
  → recebe resultados de grupos
  → persiste source_runs, telemetry_events e system_logs
  → separa observabilidade do fluxo de execução

Etapa 3: extrair _reconcile_activity(...)
  → recebe listing_ids vistos no run
  → marca inativos, atualiza last_seen_at
  → roda após todos os grupos
```

**Critério:** `run_source_for_all_wishlists` deve virar orquestrador, sem reimplementar scraping, erro, telemetria e reconciliação no mesmo bloco.

---

## ARCH-02 — `settings` como god object

**Estado atual:** `app/core/settings.py` segue flat e concentra configuração de banco, Telegram, deploy admin, Playwright, scheduler, sender, tracking, dedupe, leilões, alertas, runtime paths, fontes e feature flags.

**Direção:** criar namespaces por domínio mantendo acesso flat por compatibilidade.

Exemplo de direção:

```python
class DBSettings(BaseModel):
    database_url: str
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle: int = 1800

class PlaywrightSettings(BaseModel):
    playwright_queue_max_jobs: int = 10
    playwright_context_ttl_seconds: int = 600
    playwright_max_contexts: int = 1

class SchedulerSettings(BaseModel):
    sched_sender_seconds: int = 60
    notification_sender_batch_size: int = 20
    notification_sender_sleep_seconds: float = 0.04
```

**Migração:** incremental. Não renomear variáveis de ambiente na primeira etapa.

**Critério:** módulos novos podem usar `settings.db`, `settings.playwright`, `settings.scheduler`, mas acessos legados como `settings.database_url` e `settings.playwright_max_contexts` continuam funcionando.

---

## ARCH-03 — `handlers_admin.py` ainda não é apenas dispatcher

**Estado atual verificado:** `handlers_admin.py` já delega vários comandos para módulos dedicados, mas ainda mistura domínios grandes. A `main` já inclui `/admin metrics` como módulo próprio.

### Já extraído

```text
app/bot/admin_handlers_sources.py       → /admin sources parcial
app/bot/admin_handlers_deploy.py        → /admin deploy
app/bot/admin_handlers_health.py        → /admin health, /admin audit, /admin errors
app/bot/admin_handlers_diagnostics.py   → /admin dedupe, /admin tracking
app/bot/admin_handlers_digest.py        → /admin digest
app/bot/admin_handlers_fipe.py          → /admin fipe
app/bot/admin_handlers_metrics.py       → /admin metrics
```

### Ainda dentro de `handlers_admin.py`

```text
/admin users
/admin premium
/admin auctions
/admin runall
/admin warmup
/admin matchdebug
/admin requeue
/admin reindex_wishlists
/admin source
/admin fb_sessions
helpers compartilhados e imports remanescentes de vários domínios
```

### Próximas fases recomendadas

```text
Fase 3C: extrair users/premium
  → app/bot/admin_handlers_users.py
  → /admin users, /admin premium e comandos ligados a plano/assinatura

Fase 3D: extrair runall/warmup/source/fb_sessions
  → app/bot/admin_handlers_execution.py ou módulos menores por domínio
  → /admin runall, /admin warmup, /admin source, /admin fb_sessions

Fase 3E: extrair matchdebug/requeue/reindex_wishlists
  → app/bot/admin_handlers_matching_ops.py
  → /admin matchdebug, /admin requeue, /admin reindex_wishlists

Fase 3F: extrair auctions
  → app/bot/admin_handlers_auctions.py
  → /admin auctions e subcomandos relacionados

Fase 3G: limpeza final do dispatcher
  → handlers_admin.py deve conter apenas cmd_admin, delegações e glue mínimo
```

**Critério:** cada módulo deve ter responsabilidade única, evitar import circular e manter comportamento/textos existentes.

---

## ARCH-04 — Pool SQLAlchemy ✅

**Estado verificado:** concluído. `app/db/session.py` aplica `max_overflow`, `pool_timeout` e `connect_timeout` para conexões não-SQLite, com tratamento específico para SQLite.

---

## ARCH-05 — Índice parcial de notificações enviadas ✅

**Estado verificado:** concluído. A migration `migrations/versions/f6a1b2c3d4e5_notifications_sent_at_index.py` cria índice parcial em PostgreSQL:

```sql
CREATE INDEX ix_notifications_user_sent_today
ON notifications (user_id, sent_at)
WHERE status = 'sent';
```

`docs/07_BUGS.md` registra validação em PostgreSQL/Supabase real.

---

## ARCH-06 — Limpeza de scripts órfãos ✅

**Estado verificado:** `config/raspberry-pi/crontab` usa `scripts/cleanup_operational_data.py --apply` como fluxo oficial de limpeza operacional.

Removidos:

```text
scripts/cache_manager.py
scripts/database_optimizer.py
```

---

## ARCH-07 — Throughput seguro do sender ✅

**Estado verificado:** o sender real está em `app/scheduler/jobs_send.py::send_queued_notifications`, com lote via `notification_sender_batch_size` e pacing via `notification_sender_sleep_seconds`.

Profile recomendado:

```env
SCHED_SENDER_SECONDS=60
NOTIFICATION_SENDER_BATCH_SIZE=50
NOTIFICATION_SENDER_SLEEP_SECONDS=0.04
```

---

## ARCH-08 — Defaults seguros de Playwright ✅

**Estado verificado:** defaults internos em `app/core/settings.py` alinhados ao Raspberry Pi 4GB:

```text
playwright_max_contexts=1
playwright_context_ttl_seconds=600
playwright_queue_max_jobs=10
```

---

## Estado verificado em código nesta revisão

```text
app/bot/handlers_admin.py
app/bot/admin_handlers_metrics.py
app/bot/admin_handlers_health.py
app/bot/admin_handlers_diagnostics.py
app/bot/admin_handlers_digest.py
app/bot/admin_handlers_fipe.py
app/bot/admin_handlers_sources.py
app/core/settings.py
app/db/session.py
app/services/source_execution_service.py
app/services/source_execution_helpers.py
migrations/versions/f6a1b2c3d4e5_notifications_sent_at_index.py
```

---

## Prioridade atual

### P0 — Operacional

Sem P0 ativo neste documento. As pendências operacionais anteriores foram fechadas ou movidas para documentos próprios.

### P1 — Refactor seguro

| Ordem | Item | Escopo | Esforço | Risco de não fazer |
|---|---|---|---|---|
| 1 | ARCH-03 fase 3C | Extrair users/premium | Médio | Plano/assinatura continuam acoplados ao dispatcher |
| 2 | ARCH-03 fase 3D | Extrair runall/warmup/source/fb_sessions | Médio | Operação de execução continua misturada com admin geral |
| 3 | ARCH-03 fase 3E | Extrair matchdebug/requeue/reindex_wishlists | Médio | Diagnóstico e reprocessamento seguem dentro do arquivo principal |
| 4 | ARCH-03 fase 3F | Extrair auctions | Alto | Bloco grande de leilões mantém alto acoplamento |
| 5 | ARCH-03 fase 3G | Limpeza final do dispatcher | Baixo/Médio | `handlers_admin.py` continua importando domínios demais |

### P2 — Arquitetura de longo prazo

| Ordem | Item | Escopo | Esforço | Risco de não fazer |
|---|---|---|---|---|
| 1 | ARCH-01 fase 1 | Extrair `_run_single_group` | Alto | Runner de source continua difícil de testar/evoluir |
| 2 | ARCH-01 fase 2 | Extrair `_post_run_telemetry` | Médio/Alto | Observabilidade segue acoplada à execução |
| 3 | ARCH-01 fase 3 | Extrair `_reconcile_activity` | Médio | Atividade/inatividade continua misturada ao runner |
| 4 | ARCH-02 fase 1 | Criar namespaces de settings mantendo acesso flat | Alto | Configuração segue sem fronteiras por domínio |

---

## Próxima PR recomendada

**ARCH-03 fase 3C — extrair users/premium.**

Diretriz:

```text
Criar app/bot/admin_handlers_users.py
Mover apenas /admin users e /admin premium, mais helpers exclusivos
Não mexer em auctions, runall, warmup, matchdebug, requeue ou source
Manter textos e comportamento existentes
Evitar import circular
Atualizar esta doc ao final da PR
```
