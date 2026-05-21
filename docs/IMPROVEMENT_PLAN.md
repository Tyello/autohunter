# AutoHunter / Garagem Alvo — Plano de Melhorias
> Auditoria completa do código-fonte. Foco em bugs, N+1, arquivos inutilizados e escala para 100 usuários simultâneos em Raspberry Pi 4 (4 GB).

---

## Status de execução (P1-B) — 2026-05-21

- **Status:** parcialmente concluído.
- **Removidos nesta etapa:**
  - `config/rpi_config.py`, `config/raspberry_pi_config.py`, `config/notification_config.py`
  - `scripts/debug_icarros.py`, `scripts/debug_icarros_one.py`, `scripts/debug_icarros_urls.py`, `scripts/debug_manual_search.py`, `scripts/debug_mercadolivre.py`, `scripts/debug_turboclass.py`
  - `scripts/test_ml_api.py`, `scripts/test_ml_api_raw.py`, `scripts/test_ml_client.py`, `scripts/test_ml_scraper.py`, `scripts/test_olx.py`, `scripts/health_check.py`
  - `monitoring/resource_monitor.py`
  - `app/services/mercado_livre/`
  - `app/notifications/email.py`, `app/notifications/whatsapp.py`, `app/notifications/webhook.py`, `app/notifications/manager.py`
  - `app/scheduler/jobs.py::queue_notifications_for_new_listings` e `tests/test_scheduler_notifications_queue.py`
- **Mantidos por segurança operacional (validar depois):**
  - `scripts/cache_manager.py` e `scripts/database_optimizer.py` (ainda referenciados em `config/raspberry-pi/crontab`).

## Status de execução (P2-A) — 2026-05-21

- **Status:** implementado.
- `_wishlist_eligibility_snapshot` deixou de carregar todas as wishlists ativas por source para filtrar em memória.
- A elegibilidade agora é resolvida com query SQL (EXISTS em `wishlist_filters`) por source, preservando a regra:
  - wishlist sem filtro `source=eq` segue elegível apenas em sources default monitoráveis/implementadas;
  - wishlist com filtro `source=eq` segue restrita às sources explicitamente escolhidas.

## 1. Bugs Confirmados

> Status P1-A (2026-05-21): **concluído na PR #248** (pool SQLAlchemy explícito, bootstrap único de `source_configs` no scheduler e testes de regressão).

### 1.1 `scripts/health_check.py` — imports quebrados (arquivo inutilizável)
**Impacto:** O script falha imediatamente ao ser importado.

```python
# health_check.py — linhas 21–24
from app.core.resource_monitor import resource_monitor   # módulo não existe
from app.core.throttler import auto_throttler            # módulo não existe
from app.core.cache import scraping_cache, vehicle_cache # módulo não existe
```

`app/core/` contém apenas: `enthusiast.py`, `geo.py`, `query_match.py`, `runtime_paths.py`, `scoring.py`, `settings.py`, `shutdown.py`, `text_norm.py`. Os três módulos importados não existem.

**Status:** Resolvido no P1-B (arquivo removido nesta limpeza conservadora).

---

### 1.2 `app/notifications/manager.py` — classe nunca instanciada em produção
**Impacto:** `NotificationManager` importa `EmailNotifier`, `WhatsAppNotifier`, `WebhookNotifier` mas nenhum serviço da app chama `get_notification_manager()`. O canal real é o `telegram_sender` direto. Desperdício de importações e risco de falha silenciosa se os módulos forem removidos sem checar o manager primeiro.

**Status:** Resolvido no P1-B (manager e notificadores não-Telegram removidos).

---

### 1.3 Missing index: `notifications(user_id, status, sent_at)` para `count_sent_today`
**Impacto:** `count_sent_today()` é chamado **por notificação** no loop do sender. A query filtra `user_id + status='sent' + sent_at range`. O índice existente é `(user_id, status, created_at)` — **`created_at` ≠ `sent_at`**. Com 100 usuários e tabela de notificações crescendo, essa query faz varredura parcial sem aproveitar o índice correto.

**Migration necessária:**
```sql
CREATE INDEX CONCURRENTLY ix_notifications_user_sent_today
ON notifications (user_id, sent_at)
WHERE status = 'sent';
```

---

## 2. Problemas de Performance / N+1 (críticos para 100 usuários)

### 2.1 Sender loop: 4–5 queries por notificação (N+1 severo)
**Localização:** `app/scheduler/jobs_send.py` → `send_queued_notifications`

`claim_queued_notifications` carrega as notificações **sem** eager-load. Para cada `n` no loop:

| Acesso | Queries por item |
|---|---|
| `n.user` | 1 (lazy relationship) |
| `n.car_listing` | 1 (lazy relationship) |
| `count_sent_today(db, n.user_id)` | 1 (SELECT COUNT com janela de tempo) |
| `get_active_subscription_limit_for_user(db, n.user_id)` | 2 (SELECT user + SELECT subscription+plan JOIN) |
| **Total por notificação** | **~5 queries** |

Com batch de 20 notificações de usuários distintos = ~100 queries por ciclo do sender.

**Correção em `notification_delivery_service.py`:**
```python
from sqlalchemy.orm import joinedload

rows = (
    db.query(Notification)
    .options(
        joinedload(Notification.user),
        joinedload(Notification.car_listing),
    )
    .filter(...)
    .limit(batch)
    .all()
)
```

**Correção no loop do sender — cache de limite por usuário:**
```python
_limit_cache: dict[str, tuple[int, int]] = {}  # user_id -> (sent, limit)

def _get_user_budget(db, user_id):
    if user_id not in _limit_cache:
        sent = count_sent_today(db, user_id)
        limit = get_active_subscription_limit_for_user(db, user_id)
        _limit_cache[user_id] = (sent, limit)
    return _limit_cache[user_id]
```
Isso reduz de ~100 para ~2 queries por batch inteiro para a checagem de limite.

---

### 2.2 `_wishlist_eligibility_snapshot` carrega todas as wishlists a cada tick do scheduler
**Localização:** `app/services/source_execution_service.py:104`

```python
active_wishlists = (
    db.query(Wishlist)
    .options(joinedload(Wishlist.filters))
    .filter(Wishlist.is_active.is_not(False))
    .all()
)
```

Com 100 usuários × 3 wishlists médias = 300 wishlists + filtros carregados a cada tick de **cada source** (10+ sources = 3.000+ carregamentos de wishlist por ciclo de scheduler). O índice invertido `wishlist_tokens` **já está implementado** mas só é usado no matching — o pré-filtro por source ainda carrega tudo.

**Correção:** Usar `wishlist_tokens` também na seleção de wishlists elegíveis por source, ou manter um cache de wishlists ativas com TTL de 30s (o custo de refresh é 1 query vs N queries por tick).

---

### 2.3 `ensure_source_configs` chamado em todo tick do scheduler
**Localização:** `app/scheduler/run.py:104` → `ensure_source_configs(db)`

Essa função abre uma sessão e verifica/insere source_configs a cada tick. O cache de 60s em `source_configs_service` mitiga parcialmente, mas a sessão ainda é aberta para cada source por tick.

**Correção:** Mover `ensure_source_configs` para o boot do scheduler (chamado 1× na inicialização) e remover do tick individual, já que os plugins não mudam em runtime.

---

### 2.4 `get_wishlist_summaries` — 4+ queries por chamada de menu
**Localização:** `app/services/wishlists_service.py:433`

Já batched por `IN (wishlist_ids)` — padrão correto. Não é N+1 mas são 4–5 roundtrips para renderizar o menu. Com 100 usuários abrindo `/menu` simultaneamente, isso gera ~500 queries no mesmo instante.

**Correção de curto prazo:** Cache por `user_id` com TTL de 10s usando um dict em memória ou `lru_cache` com timeout — o menu raramente muda entre 2 toques seguidos.

---

## 3. Arquivos Inutilizados que Podem Ser Removidos

### 3.1 Configs legados sem uso no runtime

| Arquivo | Motivo |
|---|---|
| `config/rpi_config.py` | `RaspberryPiConfig` class nunca importada em `app/` |
| `config/raspberry_pi_config.py` | Gera arquivos em `config/raspberry-pi/` mas nunca usado em runtime |
| `config/notification_config.py` | Zero imports em todo o projeto |

**Ação:** Remover os três. Os arquivos que `raspberry_pi_config.py` gera já estão em `config/raspberry-pi/` e em `deploy/raspberry/`.

---

### 3.2 Canal de notificações não-Telegram (código de roadmap sem integração)

| Arquivo | Motivo |
|---|---|
| `app/notifications/email.py` | Só importado em `manager.py` |
| `app/notifications/whatsapp.py` | Só importado em `manager.py` |
| `app/notifications/webhook.py` | Só importado em `manager.py` |
| `app/notifications/manager.py` | `get_notification_manager()` nunca chamado em `app/` |

**Ação:** Mover para `app/notifications/roadmap/` ou remover completamente. O sender real é `app/bot/sender.py` → `telegram_sender`.

---

### 3.3 Scripts de debug sem integração ao runtime

| Arquivo | Motivo |
|---|---|
| `scripts/debug_icarros.py` | Debug manual, sem testes |
| `scripts/debug_icarros_one.py` | Idem |
| `scripts/debug_icarros_urls.py` | Idem |
| `scripts/debug_manual_search.py` | Idem |
| `scripts/debug_mercadolivre.py` | Idem |
| `scripts/debug_turboclass.py` | Idem |
| `scripts/test_ml_api.py` | Usa `app.services.mercado_livre.client` que não existe |
| `scripts/test_ml_api_raw.py` | Idem |
| `scripts/test_ml_client.py` | Idem |
| `scripts/test_ml_scraper.py` | Usa `MercadoLivreIngestService` não integrado ao pipeline |
| `scripts/test_olx.py` | Debug manual |
| `scripts/health_check.py` | Imports quebrados (ver Bug 1.1) |
| `scripts/cache_manager.py` | Nunca importado em `app/`; cache real está em `source_configs_service` |
| `scripts/database_optimizer.py` | Só chamado no `health_check.py` quebrado |
| `monitoring/resource_monitor.py` | Não integrado a nenhum serviço do app |

**Ação:** Mover para `scripts/archive/` ou remover. Manter apenas scripts operacionais: `backup_core_data.py`, `restore_core_data.py`, `validate_core_backup.py`, `compare_core_backup_to_db.py`, `cleanup_operational_data.py`, `disk_audit.py`.

---

### 3.4 `app/services/mercado_livre/` — módulo paralelo não integrado

| Arquivo | Motivo |
|---|---|
| `app/services/mercado_livre/scraper.py` | Só referenciado em scripts de debug mortos |
| `app/services/mercado_livre/ingest.py` | Idem |
| `app/services/mercado_livre/parser.py` | Idem |

O pipeline real usa `app/scrapers/mercadolivre.py` (v1) e `app/scrapers/sources/mercadolivre.py` (v2). Este módulo em `services/` é um experimento desconectado.

**Ação:** Remover o diretório `app/services/mercado_livre/`.

---

### 3.5 `app/scheduler/jobs.py::queue_notifications_for_new_listings` — função morta

```python
# jobs.py:174
def queue_notifications_for_new_listings(db: Session, component: str, new_listing_ids: list):
```

Não chamada em nenhum ponto do pipeline de produção. Aparece apenas em testes. O matching real usa `scrape_ingest_match_many` em `jobs.py`.

**Ação:** Remover a função e atualizar os testes que a testam diretamente (ou transformá-los em testes do `scrape_ingest_match_many`).

---

## 4. Abstrações e Refatorações Recomendadas

### 4.1 Consolidar caminhos de scraper v1/v2
**Situação atual:** Dois diretórios paralelos com implementações duplicadas:
- `app/scrapers/chavesnamao.py` (v1) + `app/scrapers/sources/chavesnamao.py` (v2)
- Idem para mercadolivre, olx, icarros, kavak, webmotors, gogarage, turboclass

O `source_execution_service` seleciona o caminho por flag `impl=v1|v2|dual` no `source_configs.extra`.

**Ação:** Quando uma source for validada com v2, marcar v1 como `_legacy` no nome e adicionar deprecation warning. Não remover ainda — manter trilha de rollback.

---

### 4.2 Extrair lógica de limit-check do sender para `LimitChecker` isolado

A checagem `can_send_more_today` envolve 3 serviços (`limits_service`, `notifications_service`, `users_service`). Para 100 usuários, deve virar um objeto que pré-carrega todos os limites do batch de uma vez:

```python
class BatchLimitChecker:
    def __init__(self, db, user_ids: list[UUID]):
        # Uma query IN para todos os user_ids do batch
        self._counts = _load_sent_counts_bulk(db, user_ids)
        self._limits = _load_limits_bulk(db, user_ids)

    def can_send(self, user_id) -> bool:
        return self._counts.get(user_id, 0) < self._limits.get(user_id, 10)

    def register_sent(self, user_id):
        self._counts[user_id] = self._counts.get(user_id, 0) + 1
```

---

### 4.3 Configuração explícita do pool SQLAlchemy

`app/db/session.py` usa apenas `pool_pre_ping=True`. Para RPi 4 com 4 GB:

```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,           # conexões ativas (threads do scheduler)
    max_overflow=5,        # pico controlado
    pool_recycle=1800,     # 30 min — evita conexão stale com Supabase
    pool_timeout=20,       # falha rápida se pool saturado
    connect_args={"connect_timeout": 10},
)
```

Acrescentar ao `settings.py`:
```python
db_pool_size: int = 5
db_max_overflow: int = 5
db_pool_recycle: int = 1800
db_pool_timeout: int = 20
```

---

### 4.4 Cache de `source_configs` já existe — usar em todos os paths

O `source_configs_service` tem cache de 60s (`_CACHE_BY_SOURCE`). Porém `ensure_source_configs` no tick do scheduler abre uma session mesmo quando o cache está válido, porque ela verifica/insere novos plugins.

**Ação:** Adicionar flag `_configs_bootstrapped: bool = False` no scheduler. Chamar `ensure_source_configs` apenas no boot e ao receber sinal explícito de invalidação (ex: `/admin source X enable`).

---

## 5. Melhorias para Escalar a 100 Usuários no RPi 4 (4 GB)

### 5.1 Resumo de impacto por área

| Área | Situação atual | Com 100 usuários | Correção |
|---|---|---|---|
| Sender loop | ~5 queries/notificação | ~500 queries/batch de 20 | Eager-load + cache de limite |
| Index `notifications` | `user_id+status+created_at` | Seq scan em `sent_at` | Novo partial index com `sent_at` |
| Wishlist loading | Carrega tudo por tick/source | ~3.000 cargas/ciclo | Cache de wishlists 30s |
| `ensure_source_configs` | Por tick | ~10 sessions/min extras | Mover para boot |
| DB pool | Defaults (5+10) | Pool pode saturar | Configurar explicitamente |

---

### 5.2 Índice adicional para `count_sent_today` (P0)

```python
# Nova migration: xxxx_notifications_user_sent_today_index.py
def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_user_sent_today
            ON notifications (user_id, sent_at)
            WHERE status = 'sent'
        """)
    else:
        op.create_index(
            "ix_notifications_user_sent_today",
            "notifications",
            ["user_id", "status", "sent_at"],
        )
```

---

### 5.3 Configurações recomendadas de `.env` para RPi 4 (4 GB) com 100 usuários

```env
# DB Pool
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_RECYCLE=1800
DB_POOL_TIMEOUT=20

# Sender
NOTIFICATION_SENDER_BATCH_SIZE=30     # era 20; 30 reduz ciclos sem sobrecarregar
NOTIFICATION_SENDER_COMMIT_BATCH_SIZE=5  # commit a cada 5, não 1

# Scheduler workers
SCHEDULER_WORKERS=2
SCHEDULER_HTTP_WORKERS=3
SCHEDULER_HTTP_WORKER_COUNT=2

# Source configs cache
SOURCE_CONFIG_CACHE_TTL_SECONDS=120   # aumentar de 60 para 120s

# Playwright (manter conservador)
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_CONTEXT_TTL_SECONDS=600
PLAYWRIGHT_QUEUE_MAX_JOBS=10          # era 25; 10 evita RAM blowup

# Tick do scheduler (reduzir batimento)
SCHEDULER_TICK_SECONDS=90             # era 60; 90s reduz 33% das sessions abertas
```

---

### 5.4 PostgreSQL local no RPi 4 — ajustes de `postgresql.conf`

O arquivo em `config/raspberry-pi/postgresql.conf` já existe mas precisa de ajuste:

```conf
# Para RPi 4 com 4 GB e uso local (sem rede pública)
max_connections = 25               # Nunca mais que pool_size + max_overflow + margem
shared_buffers = 512MB             # 12% da RAM (padrão é 128MB)
effective_cache_size = 2GB
work_mem = 8MB                     # Sorts/joins por operação
maintenance_work_mem = 128MB

# Reduz escritas no SD card
checkpoint_completion_target = 0.9
wal_buffers = 32MB
synchronous_commit = off           # Aceitável para logs/telemetry
```

---

### 5.5 Aumentar `notification_sender_batch_size` com cuidado

Com 100 usuários e limite de 5 notificações/dia cada = até 500 notificações acumuladas. O batch de 20 precisaria de 25 ciclos para drenar. Com batch de 50 + lazy-loading corrigido, 2–3 ciclos bastam.

**Limitante:** Cada envio Telegram tem rate limit de ~30 mensagens/segundo. Com 50 notificações em sequência síncrona, pode atingir o rate limit. Considerar sleep de 50ms entre envios ou usar `asyncio` no sender.

---

### 5.6 Wishlist tokens — garantir que está sendo usado no scheduler

O `wishlist_tokens_service` com índice invertido está implementado e a tabela existe. Verificar se o scheduler está usando o path de candidatos por token em vez de carregar todas as wishlists:

```python
# Em source_execution_service.py — confirmar que match usa tokens
# app/services/matching_service.py já usa tokens internamente?
# Se não, adicionar pré-filtragem em _wishlist_eligibility_snapshot:

from app.services.wishlist_tokens_service import get_candidate_wishlist_ids_for_listing

# Antes do loop de match por wishlist, filtrar por candidatos via token
```

---

## 6. Sugestões de Limpeza de Arquivos — Resumo Executivo

### Remover imediatamente (zero risco)
```
config/rpi_config.py
config/raspberry_pi_config.py
config/notification_config.py
scripts/debug_icarros.py
scripts/debug_icarros_one.py
scripts/debug_icarros_urls.py
scripts/debug_manual_search.py
scripts/debug_mercadolivre.py
scripts/debug_turboclass.py
scripts/test_ml_api.py
scripts/test_ml_api_raw.py
scripts/test_ml_client.py
scripts/test_ml_scraper.py
scripts/test_olx.py
scripts/health_check.py           (imports quebrados)
monitoring/resource_monitor.py    (não integrado)
app/services/mercado_livre/       (diretório inteiro)
```

### Remover após validar que não há uso oculto
```
app/notifications/email.py
app/notifications/whatsapp.py
app/notifications/webhook.py
app/notifications/manager.py
app/scheduler/jobs.py::queue_notifications_for_new_listings (só a função)
```

### Marcar como legado (não remover ainda)
```
app/scrapers/chavesnamao.py       → v1 legado
app/scrapers/gogarage.py          → v1 legado
app/scrapers/icarros.py           → v1 legado
app/scrapers/kavak.py             → v1 legado
app/scrapers/mercadolivre.py      → v1 legado
app/scrapers/mobiauto.py          → v1 legado
app/scrapers/olx.py               → v1 legado
app/scrapers/turboclass.py        → v1 legado
app/scrapers/webmotors.py         → v1 legado
```

---

## 7. Prioridades de Implementação

| Prioridade | Item | Impacto | Esforço |
|---|---|---|---|
| P0 | Eager-load em `claim_queued_notifications` | Remove ~80% das queries do sender | Baixo (5 linhas) |
| P0 | Cache de limite por usuário no sender loop | Remove ~3 queries/usuário/batch | Baixo (20 linhas) |
| P0 | Migration: `ix_notifications_user_sent_today` | Corrige scan parcial crescente | Baixo (migration) |
| P1 | Configurar pool SQLAlchemy explicitamente | Evita saturação com 100 usuários | Trivial |
| P1 | Mover `ensure_source_configs` para boot | Reduz sessões desnecessárias | Baixo |
| P1 | Remover arquivos mortos (seção 3) | Reduz ruído e risco de confusão | Trivial |
| P1 | Ajustar `.env` RPi 4 (seção 5.3) | Otimiza uso de RAM e CPU | Trivial |
| P2 | `BatchLimitChecker` (seção 4.2) | Escala elegante para >100 usuários | Médio |
| P2 | Cache de wishlists ativas com TTL 30s | Reduz cargas por tick | Médio |
| P3 | Consolidar v1→v2 scrapers por source | Reduz manutenção futura | Alto |
| P3 | Ajustar `postgresql.conf` (seção 5.4) | Melhora throughput de queries | Baixo (config) |

---

*Documento gerado com base em análise estática completa de 548 arquivos Python, migrations Alembic e configurações de deploy. Data: 2026-05-21.*
