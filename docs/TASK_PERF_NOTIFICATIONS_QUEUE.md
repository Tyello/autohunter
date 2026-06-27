# TASK — Otimização do hot path da fila de notificações + saneamento Alembic

> **Para:** Claude Code
> **Repo:** github.com/Tyello/autohunter
> **Stack:** Python 3.13, SQLAlchemy, Alembic, PostgreSQL, Raspberry Pi 4 (4GB)
> **Tipo:** mudança de banco (índice) + saneamento de migrations + tooling de profiling
> **Risco:** baixo. Nenhuma mudança de schema de dados; apenas índice e ferramentas.

---

## 0. Contexto (não re-derivar)

O sender de notificações roda a cada tick e executa esta query de *claim*
(`app/services/notification_delivery_service.py::claim_queued_notifications`):

```sql
SELECT ... FROM notifications
WHERE status = 'queued'
  AND (next_attempt_at IS NULL OR next_attempt_at <= now())
ORDER BY created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT :batch;
```

O índice que serve essa query — `ix_notifications_delivery_queue`
`(status, next_attempt_at, created_at)`, criado na migration
`e8d0d6f4a21b_notification_delivery_hardening.py` — **não é parcial**.
Como ~99% das linhas viram `status='sent'`, o índice acumula histórico morto,
deixa de caber em `shared_buffers` no Pi (I/O lento de SD/USB) e encarece o
autovacuum. O resto do projeto já usa índices parciais (`postgresql_where`) em
8+ lugares; este hot path é a exceção.

**Objetivo:** trocar por um índice **parcial** que indexe só o backlog vivo
(`status IN ('queued','processing')`), aplicado com `CONCURRENTLY` para não
travar a fila durante o deploy.

**Bloqueador a tratar antes:** `alembic heads` retorna múltiplos heads não
mergeados (~15). Um `alembic upgrade head` pode falhar ou aplicar parcialmente.
Resolver isso é pré-requisito da migration de índice.

---

## 1. Pré-flight (não pular)

```bash
# Confirmar branch limpa e backup lógico antes de mexer em migrations/índices
git status
alembic current
alembic heads          # anotar TODOS os heads retornados
alembic history | head -40
```

- [ ] Trabalhar em branch nova: `git checkout -b perf/notifications-delivery-queue`
- [ ] **Fazer backup** antes de aplicar no Pi (ver `docs/BACKUP_RESTORE.md`).
- [ ] Validar primeiro em ambiente de dev/staging com Postgres — **nunca** estrear direto no Pi de produção.

---

## 2. Saneamento Alembic (pré-requisito)

Há múltiplos heads. Mergeá-los em um único antes de encadear a nova migration.

```bash
# Substituir <head1> <head2> ... pela saída real de `alembic heads`
alembic merge -m "merge open heads pre delivery-queue index" <head1> <head2> <head3> ...
alembic heads   # DEVE retornar exatamente 1 head agora
```

- [ ] Após o merge, `alembic heads` retorna **um único** head. Anotar o revision id do merge → chamar de `<MERGE_REV>`.
- [ ] Rodar `alembic upgrade head` em dev e confirmar que sobe limpo.

> Não inventar a ordem dos heads nem editar `down_revision` de migrations antigas
> à mão. Usar `alembic merge`, que é a forma segura.

---

## 3. Migration do índice parcial

Garantir que existe o arquivo
`migrations/versions/p1_notifications_delivery_queue_partial.py` com o conteúdo
abaixo. **Editar `down_revision` para `<MERGE_REV>` do passo 2** (não deixar o
placeholder `e8d0d6f4a21b`, que não é mais o head após o merge).

```python
"""notifications: make delivery-queue index partial (hot claim path)"""
from alembic import op

revision = "p1_notif_dq_partial"
down_revision = "<MERGE_REV>"   # <-- AJUSTAR para o head do passo 2
branch_labels = None
depends_on = None

OLD = "ix_notifications_delivery_queue"
NEW = "ix_notifications_delivery_queue_active"


def upgrade() -> None:
    # CONCURRENTLY não pode rodar dentro de transação -> autocommit_block
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {OLD}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NEW} "
            "ON notifications (next_attempt_at, created_at) "
            "WHERE status IN ('queued','processing')"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {NEW}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {OLD} "
            "ON notifications (status, next_attempt_at, created_at)"
        )
```

Notas de design (não alterar sem motivo):
- `status` saiu da chave do índice de propósito: o `WHERE` parcial já fixa o
  status, então mantê-lo na chave só gastaria espaço. A ordenação
  `(next_attempt_at, created_at)` casa com o `ORDER BY` da query de claim.
- `IF EXISTS`/`IF NOT EXISTS` deixam a migration idempotente e re-rodável.
- Inclui `processing` no filtro para cobrir `reclaim_stale_processing_notifications`.

Aplicar:

```bash
alembic upgrade head
```

---

## 4. Verificação (obrigatória)

Rodar no Postgres alvo:

```sql
-- 4.1 O índice novo existe e é PARCIAL (deve aparecer o WHERE no indexdef)
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'notifications'
  AND indexname = 'ix_notifications_delivery_queue_active';

-- 4.2 O índice antigo NÃO existe mais
SELECT indexname FROM pg_indexes
WHERE tablename = 'notifications'
  AND indexname = 'ix_notifications_delivery_queue';

-- 4.3 O planner USA o índice parcial na query de claim
EXPLAIN (ANALYZE, BUFFERS)
SELECT id FROM notifications
WHERE status = 'queued'
  AND (next_attempt_at IS NULL OR next_attempt_at <= now())
ORDER BY created_at ASC
LIMIT 20;
```

Critérios de aceite:
- [ ] 4.1 retorna 1 linha e o `indexdef` contém `WHERE (status = ANY ...'queued'...'processing'...)`.
- [ ] 4.2 retorna 0 linhas.
- [ ] 4.3 mostra `Index Scan using ix_notifications_delivery_queue_active` (não `Seq Scan`, não o índice antigo) e `Buffers` baixo.
- [ ] `pytest` passa (rodar a suíte; ver `pytest.ini`).
- [ ] `alembic heads` continua com 1 head; `alembic downgrade -1 && alembic upgrade head` funciona (testa o downgrade do índice).

---

## 5. Tooling: probe de RAM/I/O para o load test no Pi

O teto real de carga no Pi 4 é RAM dos workers de browser (Chromium), não SQL.
Criar `scripts/pi_load_probe.sh` para medir durante o teste de ~50 users/24h.

```bash
#!/usr/bin/env bash
# Uso: ./scripts/pi_load_probe.sh [intervalo_seg] [arquivo_csv]
# Amostra RAM disponível, pressão de I/O e nº de processos chromium ao longo do tempo.
set -euo pipefail
INTERVAL="${1:-15}"
OUT="${2:-pi_load_probe_$(date +%Y%m%d_%H%M%S).csv}"

echo "ts,mem_total_mb,mem_avail_mb,swap_used_mb,load1,chromium_procs,chromium_rss_mb" > "$OUT"
echo "Coletando a cada ${INTERVAL}s em ${OUT} (Ctrl-C para parar)"

while true; do
  ts=$(date -Iseconds)
  mem_total=$(awk '/MemTotal/{printf "%.0f",$2/1024}' /proc/meminfo)
  mem_avail=$(awk '/MemAvailable/{printf "%.0f",$2/1024}' /proc/meminfo)
  swap_used=$(awk '/SwapTotal/{t=$2}/SwapFree/{f=$2} END{printf "%.0f",(t-f)/1024}' /proc/meminfo)
  load1=$(awk '{print $1}' /proc/loadavg)
  chromium_procs=$(pgrep -c -f 'chrom(e|ium)' || echo 0)
  chromium_rss=$(ps -C chrome,chromium -o rss= 2>/dev/null | awk '{s+=$1} END{printf "%.0f", s/1024}' || echo 0)
  echo "${ts},${mem_total},${mem_avail},${swap_used},${load1},${chromium_procs},${chromium_rss}" >> "$OUT"
  sleep "$INTERVAL"
done
```

```bash
chmod +x scripts/pi_load_probe.sh
```

- [ ] Criar o script e marcá-lo executável.
- [ ] Documentar no `docs/OPERATIONS_RUNBOOK.md`: rodar este probe em paralelo ao load test; se `mem_avail_mb` cair perto de 0 ou `swap_used_mb` subir, o gargalo é browser, não banco.

---

## 6. Concorrência de browser (investigar, NÃO chutar)

Se o probe mostrar pressão de RAM, reduzir concorrência de browser para 1 rende
mais que qualquer tuning de SQL.

- [ ] Localizar o knob real de concorrência de browser worker em `app/core/settings.py` e/ou `app/scheduler/browser_queue_job.py` (procurar por algo como `browser_*concurrency*`, `*workers*`, limites de fila de browser).
- [ ] **Não** alterar o default às cegas. Reportar o nome exato da setting + valor atual e propor o valor (provavelmente `1`) como item separado, com evidência do probe. Deixar essa mudança fora deste PR a menos que o load test comprove necessidade.

---

## 7. Entregáveis / Definition of Done

- [ ] Branch `perf/notifications-delivery-queue` com:
  - [ ] migration de merge dos heads Alembic
  - [ ] `migrations/versions/p1_notifications_delivery_queue_partial.py` com `down_revision` correto
  - [ ] `scripts/pi_load_probe.sh`
  - [ ] nota no `docs/OPERATIONS_RUNBOOK.md`
- [ ] Todos os critérios de aceite das seções 4 e 5 marcados.
- [ ] `pytest` verde.
- [ ] PR com descrição curta: o que muda, por quê (índice parcial no hot path do sender), e o `EXPLAIN ANALYZE` antes/depois colado.

## 8. Guardrails

- Não mexer em schema de dados, FKs ou outras tabelas. Escopo é índice + tooling.
- Não estrear no Pi de produção sem backup e sem validar em dev.
- Não editar `down_revision` de migrations antigas à mão — usar `alembic merge`.
- Se `alembic merge` revelar conflito real de schema entre heads (e não só branching paralelo), **parar e reportar** em vez de forçar.
