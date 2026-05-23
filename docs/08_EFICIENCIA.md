# Eficiência — Performance e Escala no RPi 4
> O que foi implementado, o que ainda falta e o que monitorar em produção.

---

## O que já foi resolvido (não reabrir)

- Pool SQLAlchemy com `pool_size`, `pool_recycle`, `pool_timeout` (PR #248)
- `ensure_source_configs` no boot do scheduler (PR #248)
- Cache de `get_wishlist_summaries` com TTL 10s e observabilidade (P2-B e P2-C)
- `_wishlist_eligibility_snapshot` agora usa query SQL por source, não carrega tudo em memória (P2-A)
- Limpeza de arquivos mortos: debug scripts, notification manager, mercado_livre service (P1-B)

---

## EFF-01 — Sender loop: eager-load não confirmado

**O que deveria ter sido feito:**
```python
# claim_queued_notifications deve usar:
.options(
    joinedload(Notification.user),
    joinedload(Notification.car_listing),
)
```

**Como validar:**
```bash
grep -n "joinedload\|selectinload" app/services/notification_delivery_service.py
```

Se não tiver `joinedload`, cada `n.user` e `n.car_listing` no loop do sender gera 1 query adicional. Com batch de 50 e 30 usuários distintos = ~100 queries extras por ciclo.

**Se não estiver implementado:** adicionar em `notification_delivery_service.py::claim_queued_notifications`.

---

## EFF-02 — Cache de limite por usuário no sender

**O que deveria ter sido feito:**
```python
# No sender loop: cache intra-batch de limites por usuário
_limit_cache: dict[UUID, tuple[int, int]] = {}  # user_id -> (sent_today, limit)
```

**Como validar:**
```bash
grep -n "_limit_cache\|batch.*limit\|cache.*limit" app/scheduler/jobs_send.py
```

Se não tiver, `can_send_more_today` é chamado por notificação, gerando 2-3 queries por item.

---

## EFF-03 — `max_overflow` no pool (BUG-01 cruzado)

Ver `07_BUGS.md::BUG-01`. É uma linha de código. Fazer agora.

---

## EFF-04 — `postgresql.conf` no RPi não otimizado

**Arquivo:** `config/raspberry-pi/postgresql.conf`

**Valores recomendados para RPi 4 4GB:**

```conf
max_connections = 25
shared_buffers = 512MB
effective_cache_size = 2GB
work_mem = 8MB
maintenance_work_mem = 128MB
checkpoint_completion_target = 0.9
wal_buffers = 32MB
synchronous_commit = off
```

**Por que `synchronous_commit = off`:** para tabelas de log (`system_logs`, `telemetry_events`, `source_runs`) a perda de 1-2 segundos de logs em caso de crash é aceitável. Elimina a maioria dos fsync no SD card, que é o maior gargalo de I/O no RPi.

**Como aplicar:**
```bash
sudo nano /etc/postgresql/*/main/postgresql.conf
sudo systemctl restart postgresql
```

---

## EFF-05 — Batch sender e tick do scheduler

**Estado atual:**
- `notification_sender_batch_size = 20`
- `scheduler_tick_seconds = 60`

**Recomendado para 100 usuários:**

```env
NOTIFICATION_SENDER_BATCH_SIZE=50
SCHEDULER_TICK_SECONDS=90
```

**Cuidado com Telegram rate limit:** a API do Telegram aceita ~30 mensagens/segundo. Com batch 50 em sequência síncrona:

```python
# No sender, adicionar sleep entre envios:
import asyncio
for notification in batch:
    await send_notification(notification)
    await asyncio.sleep(0.034)  # ~29/segundo, abaixo do limite de 30
```

---

## EFF-06 — Playwright: `max_contexts=2` → `1` para RPi

**Estado atual:** `playwright_max_contexts = 2`

Cada contexto Chromium usa ~200MB. Com 2 contextos + PostgreSQL (~300MB) + Python/bot/scheduler (~200MB) = ~900MB de baseline. Sobra ~3GB de margem, mas Chromium tem picos de uso de memória durante renders JS pesados.

**Recomendado:**
```env
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_QUEUE_MAX_JOBS=10
```

Com `max_contexts=1`, sources browser rodam em série. É mais lento mas mais previsível no RPi.

---

## EFF-07 — Monitoramento de memória em produção

**Falta:** não há alerta automático quando RAM > 80%.

**Implementar em `app/scheduler/monitor_job.py`:**

```python
import psutil

def check_system_health():
    mem = psutil.virtual_memory()
    if mem.percent > 80:
        log_system_event(
            level="warn",
            component="monitor",
            message=f"RAM alta: {mem.percent:.0f}% usados ({mem.used // 1024**2}MB/{mem.total // 1024**2}MB)",
            event_type="ram_pressure"
        )
        # Opcional: notificar admin via Telegram
```

`psutil` já está no requirements? Verificar:
```bash
grep psutil requirements.txt requirements.optional.txt
```

---

## EFF-08 — Cleanup de `scrape_jobs` antigos

**Estado atual:** `cleanup_job.py` existe mas é preciso confirmar que jobs `done` e `failed` estão sendo limpos regularmente. Uma tabela `scrape_jobs` que cresce indefinidamente impacta performance de dequeue.

**Validar retenção:**
```sql
SELECT status, COUNT(*), MIN(created_at), MAX(created_at)
FROM scrape_jobs
GROUP BY status
ORDER BY status;
```

Se houver jobs `done` com mais de 7 dias, o cleanup não está rodando ou o threshold está alto demais.

**Threshold recomendado:**
- `done`: manter 48h (suficiente para diagnóstico)
- `failed`: manter 7 dias (para análise)
- `queued` antigos: alert se > 2h sem processamento

---

## Tabela de impacto

| Item | RAM salva | CPU salva | Queries salvas | Esforço |
|---|---|---|---|---|
| EFF-01 eager-load | — | — | ~80 queries/batch | Baixo |
| EFF-02 limit cache | — | — | ~60 queries/batch | Baixo |
| EFF-03 max_overflow | — | — | Evita crash silencioso | Trivial |
| EFF-04 postgresql.conf | — | ~20% I/O SD | — | Baixo (config) |
| EFF-05 batch 50 + tick 90s | — | ~30% scheduler | — | Trivial |
| EFF-06 max_contexts=1 | ~200MB | ~15% CPU | — | Trivial |
| EFF-07 RAM monitor | — | — | — | Baixo |
| EFF-08 scrape_jobs cleanup | ~5-10% disk | ~10% queries | — | Baixo |
