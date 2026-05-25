# Arquitetura — Melhorias Estruturais

> Roadmap estrutural do AutoHunter após confronto com a `main`.
> Foco: resiliência, separação de responsabilidades, operação segura no Raspberry Pi 4GB e evolução incremental sem reescrita arriscada.

---

## Estado atual do roadmap

### Concluído

- **ARCH-03 fase 1**: `/admin health`, `/admin audit` e `/admin errors` extraídos para `app/bot/admin_handlers_health.py`.
- **ARCH-03 fase 2A**: `/admin dedupe` e `/admin tracking` extraídos para `app/bot/admin_handlers_diagnostics.py`.
- **ARCH-03 fase 2B**: `/admin digest` extraído para `app/bot/admin_handlers_digest.py`.
- **ARCH-03 fase 3A**: `/admin fipe` extraído para `app/bot/admin_handlers_fipe.py`.
- **ARCH-04**: pool SQLAlchemy com `max_overflow`, `pool_timeout`, `db_connect_timeout` e tratamento específico para SQLite.
- **ARCH-05**: índice parcial de notificações enviadas.
- **ARCH-06**: remoção dos scripts órfãos `scripts/cache_manager.py` e `scripts/database_optimizer.py`.
- **ARCH-07**: sender validado com batch operacional e pacing configurável.
- **ARCH-08**: defaults seguros de Playwright alinhados ao baseline Raspberry.

### Ainda pendente

- **ARCH-03**: concluir o split dos domínios ainda dentro de `app/bot/handlers_admin.py`.
- **ARCH-01**: quebrar incrementalmente `app/services/source_execution_service.py`.
- **ARCH-02**: preparar `app/core/settings.py` para namespaces por domínio mantendo compatibilidade flat.

---

## ARCH-01 — `source_execution_service.py` ainda é god object

**Estado atual:** `run_source_for_all_wishlists` ainda concentra elegibilidade, dispatch v1/v2/dual, scraping, ingestão, matching, telemetria, classificação de erro, backoff e reconciliação de atividade. Já existe extração parcial em `source_execution_helpers.py` (`build_scrape_dispatch`, `build_run_payload`), mas o método central segue grande e altamente acoplado.

**O que fazer — extração incremental:**

```text
Etapa 1: extrair _run_single_group(...)
  → recebe grupo de wishlists + URL
  → executa scrape + ingest + match para esse grupo
  → retorna GroupExecutionResult / RunTotals
  → preserva contrato externo de run_source_for_all_wishlists
  → não move telemetria final nem reconciliação ainda

Etapa 2: extrair _post_run_telemetry(...)
  → recebe GroupExecutionResult[]
  → persiste source_runs, telemetry_events e system_logs
  → separa registro/observabilidade do fluxo de execução

Etapa 3: extrair _reconcile_activity(...)
  → recebe listing_ids vistos no run
  → marca inativos, atualiza last_seen_at
  → executado após todos os grupos
```

**Critério:** `run_source_for_all_wishlists` deve delegar para subfunções claras, sem reimplementar lógica inline de scraping, erro, telemetria e reconciliação no mesmo bloco.

**Risco:** baixo se feito em etapas pequenas, com contrato externo preservado e testes existentes mantidos.

---

## ARCH-02 — `settings` como god object

**Estado atual:** `app/core/settings.py` segue flat e concentra configuração de banco, Telegram, deploy admin, Playwright, scheduler, sender, tracking, dedupe, leilões, alertas, runtime paths, fontes e feature flags. Qualquer módulo que importa `settings` passa a depender implicitamente do objeto inteiro.

**O que fazer — agrupamento por domínio:**

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

class Settings(BaseModel):
    db: DBSettings = DBSettings()
    playwright: PlaywrightSettings = PlaywrightSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    # ...
```

**Migração:** incremental. Criar subobjetos mantendo o acesso flat atual por compatibilidade. Não renomear variáveis de ambiente na primeira etapa.

**Critério:** módulos novos podem usar `settings.db`, `settings.playwright`, `settings.scheduler`, mas `settings.database_url`, `settings.playwright_max_contexts` e demais acessos legados continuam funcionando.

---

## ARCH-03 — `handlers_admin.py` ainda não é apenas dispatcher

**Estado atual verificado na `main`:** `handlers_admin.py` já delega vários comandos para módulos dedicados, mas ainda mistura domínios grandes. O dispatcher já chama diretamente módulos extraídos para health, diagnostics, digest e FIPE, mas ainda mantém lógica de users/premium, auctions, runall/warmup, matchdebug/requeue/reindex, source/fb_sessions e parte de sources.

### Já extraído

```text
app/bot/admin_handlers_sources.py       → /admin sources parcial
app/bot/admin_handlers_deploy.py        → /admin deploy
app/bot/admin_handlers_health.py        → /admin health, /admin audit, /admin errors
app/bot/admin_handlers_diagnostics.py   → /admin dedupe, /admin tracking
app/bot/admin_handlers_digest.py        → /admin digest
app/bot/admin_handlers_fipe.py          → /admin fipe
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
Fase 3B: extrair users/premium
  → app/bot/admin_handlers_users.py
  → /admin users, /admin premium e comandos diretamente ligados a plano/assinatura

Fase 3C: extrair runall/warmup/source/fb_sessions
  → app/bot/admin_handlers_execution.py ou módulos menores por domínio
  → /admin runall, /admin warmup, /admin source, /admin fb_sessions

Fase 3D: extrair matchdebug/requeue/reindex_wishlists
  → app/bot/admin_handlers_matching_ops.py
  → /admin matchdebug, /admin requeue, /admin reindex_wishlists

Fase 3E: extrair auctions
  → app/bot/admin_handlers_auctions.py
  → /admin auctions e subcomandos relacionados

Fase 3F: limpeza final do dispatcher
  → handlers_admin.py deve conter apenas cmd_admin, delegações e glue mínimo
```

**Critério:** cada módulo deve ter responsabilidade única, evitar import circular e manter comportamento/textos existentes. `handlers_admin.py` deve caminhar para roteador puro.

---

## ARCH-04 — Pool SQLAlchemy (concluído) ✅

**Estado verificado:** concluído no código. `app/db/session.py` já passa `max_overflow`, `pool_timeout` e `connect_timeout` via `db_connect_timeout` para conexões não-SQLite, com tratamento específico para SQLite sem parâmetros incompatíveis de pool.

**Ação:** fora da fila de pendências. Manter apenas monitoramento normal em produção.

---

## ARCH-05 — Índice parcial de notificações enviadas (concluído) ✅

**Estado verificado:** concluído no código. A migration `migrations/versions/f6a1b2c3d4e5_notifications_sent_at_index.py` cria o índice `ix_notifications_user_sent_today` em Postgres como índice parcial:

```sql
CREATE INDEX ix_notifications_user_sent_today
ON notifications (user_id, sent_at)
WHERE status = 'sent';
```

Para ambientes não-Postgres, a migration aplica fallback compatível (`user_id, status, sent_at`) para não quebrar execução local.

**Queries protegidas:**

- `app/services/limits_service.py::count_sent_today`
- `app/services/limits_service.py::count_notifications_sent_last_n_days`

**Ação:** fora da fila de pendências.

---

## ARCH-06 — Limpeza de scripts órfãos (concluído) ✅

**Estado verificado:** `config/raspberry-pi/crontab` usa `scripts/cleanup_operational_data.py --apply` como fluxo oficial de limpeza operacional.

**Concluído:**

1. Removidos `scripts/cache_manager.py` e `scripts/database_optimizer.py`.
2. Eliminada ambiguidade operacional.
3. Mantido `scripts/cleanup_operational_data.py` como caminho oficial.

---

## ARCH-07 — Calibrar throughput seguro do sender (concluído) ✅

**Estado verificado:** o sender real está em `app/scheduler/jobs_send.py::send_queued_notifications`, drenando notificações `queued` via `claim_queued_notifications` e reciclando `processing` stale com `reclaim_stale_processing_notifications` em `app/services/notification_delivery_service.py`.

**Validação de pacing/rate:**

- `notification_sender_sleep_seconds` é aplicado entre envios bem-sucedidos.
- O sleep não roda quando não houve envio real anterior.
- O lote é controlado por `notification_sender_batch_size`.
- O scheduler mantém `SCHED_SENDER_SECONDS=60`.

**Valores recomendados para produção:**

```env
SCHED_SENDER_SECONDS=60
NOTIFICATION_SENDER_BATCH_SIZE=50
NOTIFICATION_SENDER_SLEEP_SECONDS=0.04
```

O default interno de `notification_sender_batch_size=20` permanece como fallback conservador.

---

## ARCH-08 — Defaults seguros de Playwright para Raspberry (concluído) ✅

**Estado verificado:** defaults internos de Playwright em `app/core/settings.py` alinhados ao baseline Raspberry Pi 4GB:

```text
playwright_max_contexts=1
playwright_context_ttl_seconds=600
playwright_queue_max_jobs=10
```

**Contrato preservado:**

- Valores seguem sobrescrevíveis por env.
- `source_configs`/DB continuam decidindo quando cada source usa browser.
- A mudança reduz risco quando `.env` está incompleto/ausente.

---

## Estado verificado em código

Arquivos conferidos nesta revisão documental:

```text
app/db/session.py
app/core/settings.py
.env.example
config/raspberry-pi/crontab
app/services/source_execution_service.py
app/services/source_execution_helpers.py
app/bot/handlers_admin.py
app/bot/admin_handlers_sources.py
app/bot/admin_handlers_deploy.py
app/bot/admin_handlers_health.py
app/bot/admin_handlers_diagnostics.py
app/bot/admin_handlers_digest.py
app/bot/admin_handlers_fipe.py
```

---

## Prioridade atual

### P0 — Operacional

Sem itens ativos neste documento. O bloco operacional identificado nesta revisão foi concluído em ARCH-04, ARCH-05, ARCH-06, ARCH-07 e ARCH-08.

### P1 — Refactor seguro

| Ordem | Item | Escopo | Esforço | Risco de não fazer |
|---|---|---|---|---|
| 1 | ARCH-03 fase 3B | Extrair users/premium | Médio | Plano/assinatura continuam acoplados ao dispatcher |
| 2 | ARCH-03 fase 3C | Extrair runall/warmup/source/fb_sessions | Médio | Operação de execução continua misturada com admin geral |
| 3 | ARCH-03 fase 3D | Extrair matchdebug/requeue/reindex_wishlists | Médio | Diagnóstico e reprocessamento seguem dentro do arquivo principal |
| 4 | ARCH-03 fase 3E | Extrair auctions | Alto | Bloco grande de leilões mantém alto acoplamento |
| 5 | ARCH-03 fase 3F | Limpeza final do dispatcher | Baixo/Médio | `handlers_admin.py` continua importando domínios demais |

### P2 — Arquitetura de longo prazo

| Ordem | Item | Escopo | Esforço | Risco de não fazer |
|---|---|---|---|---|
| 1 | ARCH-01 fase 1 | Extrair `_run_single_group` de `source_execution_service.py` | Alto | Fluxo central de source continua difícil de testar/evoluir |
| 2 | ARCH-01 fase 2 | Extrair `_post_run_telemetry` | Médio/Alto | Observabilidade segue acoplada à execução |
| 3 | ARCH-01 fase 3 | Extrair `_reconcile_activity` | Médio | Regras de atividade/inatividade continuam misturadas ao runner |
| 4 | ARCH-02 fase 1 | Criar namespaces de settings mantendo acesso flat | Alto | Configuração segue sem fronteiras por domínio |

---

## Itens concluídos fora da fila de pendências

- **ARCH-03 fase 1**: health/audit/errors extraídos.
- **ARCH-03 fase 2A**: dedupe/tracking extraídos.
- **ARCH-03 fase 2B**: digest extraído.
- **ARCH-03 fase 3A**: FIPE extraído.
- **ARCH-04**: pool SQLAlchemy endurecido.
- **ARCH-05**: índice parcial de notificações confirmado.
- **ARCH-06**: scripts órfãos removidos.
- **ARCH-07**: sender throughput/pacing validado.
- **ARCH-08**: Playwright alinhado ao baseline Raspberry.

---

## Próxima PR recomendada

**ARCH-03 fase 3B — extrair users/premium**.

Diretriz para a próxima PR:

```text
Criar app/bot/admin_handlers_users.py
Mover apenas /admin users e /admin premium, mais helpers exclusivos
Não mexer em auctions, runall, warmup, matchdebug, requeue ou source
Manter textos e comportamento existentes
Evitar import circular
Atualizar esta doc ao final da PR
```
