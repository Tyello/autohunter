# Eficiência operacional — Raspberry Pi 4 (4GB)

Atualizado em: 2026-05-25.  
Estado confrontado com a `main` após os merges recentes de eficiência, backup, backup health e tracking.

Documento operacional para manter o AutoHunter/Garagem Alvo estável 24/7 em Raspberry Pi 4 com 4GB.

## Escopo

Este documento cobre somente eficiência e operação do runtime:

- sender e fila de notificações;
- tuning de scheduler, PostgreSQL e Playwright;
- monitoramento de RAM/disco/cache;
- retenção e limpeza de dados operacionais;
- backup observável no admin health.

Este documento **não** é roadmap de produto, billing, growth ou UX de lançamento. Esses temas ficam em `docs/ROADMAP.md`, `docs/LAUNCH_PLAN.md` e `docs/USER_FLOWS.md`.

---

## Estado consolidado da `main`

### Pronto / não reabrir

- Eager-load no sender com `selectinload`.
- Cache intra-batch de limite por usuário no sender.
- SQLAlchemy pool com `max_overflow` configurável.
- Pacing entre envios Telegram.
- Profile RPi para scheduler, sender e Playwright.
- Monitoramento admin de RAM/disco/cache com throttle.
- Cleanup granular de `scrape_jobs`.
- Filesystem cleanup diário seguro.
- Backup PostgreSQL via `pg_dump`.
- Verificação de frescor de backup via script e `/admin health`.

### Ainda fora deste documento

As próximas frentes relevantes para lançamento são:

- `/admin metrics` v1;
- pagamento/ativação Premium sem gargalo manual;
- teste de carga 50 usuários/24h;
- digest semanal v2;
- confirmação do índice `ix_notifications_user_sent_today` se ainda não houver evidência no banco/migration.

Essas frentes não devem ser misturadas aqui, exceto quando gerarem impacto direto de performance/operabilidade.

---

## Resolvido — não reabrir

### EFF-01 — Sender eager-load

**Status:** resolvido.

`claim_queued_notifications` já carrega relacionamentos com:

- `selectinload(Notification.user)`;
- `selectinload(Notification.car_listing)`.

A implementação atual usa **selectinload**, não `joinedload`.

Regra: **não trocar para `joinedload` sem benchmark ou necessidade comprovada**.

Referência: `app/services/notification_delivery_service.py`.

---

### EFF-02 — Cache de limite por usuário no sender

**Status:** resolvido.

`app/scheduler/jobs_send.py` já usa `user_budget_cache` para reduzir consultas repetidas de limite/uso diário por usuário durante o batch.

Referência: `app/scheduler/jobs_send.py`.

---

### EFF-03 — SQLAlchemy `max_overflow`

**Status:** resolvido.

`app/db/session.py` aplica `max_overflow=settings.db_max_overflow`.

`docs/07_BUGS.md` também marca BUG-01 como corrigido.

Referências:

- `app/db/session.py`;
- `docs/07_BUGS.md`.

---

## Implementado neste ciclo operacional

### EFF-04 — Profile PostgreSQL para Raspberry Pi

**Status:** implementado/documentado.

Arquivo de referência: `config/raspberry-pi/postgresql.conf`.

Parâmetros recomendados para RPi 4 4GB:

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

Nota operacional:

- `synchronous_commit = off` reduz fsync e melhora previsibilidade em SD card;
- usar apenas se for aceitável perder poucos segundos de logs/eventos em crash abrupto;
- produção em banco gerenciado/Supabase pode exigir decisão diferente.

---

### EFF-05 — Tuning sender/scheduler + pacing Telegram

**Status:** implementado.

Profile recomendado para produção RPi 4:

```env
SCHEDULER_TICK_SECONDS=90
NOTIFICATION_SENDER_BATCH_SIZE=50
NOTIFICATION_SENDER_SLEEP_SECONDS=0.04
```

Comportamento atual:

- sender dorme antes do próximo envio real quando já houve pelo menos um envio bem-sucedido;
- não dorme para notificações bloqueadas por limite diário;
- não dorme para notificações sem destino;
- não dorme antes do primeiro envio;
- valor inválido/negativo é tratado de forma conservadora.

Referência: `app/scheduler/jobs_send.py`.

---

### EFF-06 — Profile Playwright para RPi

**Status:** implementado/documentado.

Profile recomendado para produção RPi 4:

```env
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_QUEUE_MAX_JOBS=10
```

Racional:

- menor paralelismo de browser;
- menor pressão de RAM;
- operação contínua mais previsível;
- adequado ao baseline Raspberry Pi 4 4GB.

---

### EFF-07 — Monitoramento automático de RAM/disco/cache

**Status:** implementado.

O monitor admin cobre:

- RAM usada acima de `RAM_ALERT_THRESHOLD`;
- uso de `/` acima de `DISK_ALERT_ROOT_USED_PCT`;
- cache acima de `DISK_ALERT_CACHE_LIMIT_GB`.

Throttle:

```env
RESOURCE_ALERT_THROTTLE_SECONDS=1800
```

Regras:

- alertas vão somente para chat/admin;
- alertas usam cooldown por chave;
- falha de leitura de recurso não deve derrubar o scheduler.

Fluxo relacionado:

- `job_admin_monitor`;
- `send_admin_text`.

---

### EFF-08 — Cleanup granular de `scrape_jobs`

**Status:** implementado.

Retenção separada:

```env
OPERATIONAL_RETENTION_SCRAPE_JOBS_DONE_HOURS=48
OPERATIONAL_RETENTION_SCRAPE_JOBS_FAILED_DAYS=7
```

Comportamento:

- remove `done` após 48h;
- remove `failed` após 7 dias;
- **não remove `queued` por padrão**;
- detecta `queued` com mais de 2h;
- em dry-run, apenas imprime diagnóstico;
- em `--apply`, registra warning em `system_logs` quando houver `queued` antigo.

Segurança:

- `python scripts/cleanup_operational_data.py` é dry-run e não deve alterar banco;
- `--apply` recusa SQLite;
- `queued` antigo é sinal de operação/scheduler, não lixo para apagar automaticamente.

Referência: `scripts/cleanup_operational_data.py`.

---

### EFF-09 — Backup observável no admin health

**Status:** implementado.

Backup real:

- script: `scripts/backup_db.sh`;
- dump completo via `pg_dump`;
- saída `.sql.gz`;
- arquivo temporário antes do arquivo final;
- retenção via `AUTOHUNTER_BACKUP_RETENTION_DAYS`.

Check de frescor:

- script: `scripts/check_latest_backup.sh`;
- serviço Python: `app/services/backup_health_service.py`;
- admin: `/admin health`.

Variáveis oficiais:

```env
AUTOHUNTER_BACKUP_DIR=/var/backups/autohunter
AUTOHUNTER_BACKUP_MAX_AGE_HOURS=30
AUTOHUNTER_BACKUP_RETENTION_DAYS=14
```

Precedência importante:

- `backup_health_service.py` prioriza `AUTOHUNTER_BACKUP_DIR` e `AUTOHUNTER_BACKUP_MAX_AGE_HOURS` para ficar alinhado aos scripts shell;
- `settings.backup_dir` e `settings.backup_max_age_hours` são fallback, não fonte principal quando env oficial existe.

Estados exibidos no `/admin health`:

- `OK`: backup recente;
- `WARNING`: backup existe, mas está antigo;
- `FAIL`: diretório ausente ou nenhum backup encontrado.

Restore continua manual e destrutivo. Não há restore automático via bot.

Referência: `docs/BACKUP_RESTORE.md`.

---

### EFF-10 — Filesystem cleanup seguro

**Status:** implementado.

Agendamento:

- `app/scheduler/run.py`;
- job id `filesystem_cleanup_daily`;
- cron diário às 03:00 UTC.

Execução:

- job: `app/scheduler/filesystem_cleanup_job.py::job_filesystem_cleanup_daily`;
- service: `app/services/filesystem_cleanup_service.py::run_filesystem_cleanup`.

Configurações:

```env
FILESYSTEM_CLEANUP_ENABLED=true
FILESYSTEM_CLEANUP_ARTIFACTS_DAYS=7
FILESYSTEM_CLEANUP_DEBUG_DAYS=3
FILESYSTEM_CLEANUP_MAX_DELETE_PER_RUN=500
```

Escopo seguro:

- runtime cache/debug;
- artefatos operacionais temporários;
- não apaga banco;
- não apaga cookies/perfis persistentes;
- não apaga diretórios fora do runtime esperado.

---

## Profile recomendado Raspberry Pi 4 — produção

Aplicar via `.env`, `/etc/default/autohunter` ou systemd, conforme o padrão do host.

```env
# Scheduler / sender
SCHEDULER_TICK_SECONDS=90
NOTIFICATION_SENDER_BATCH_SIZE=50
NOTIFICATION_SENDER_SLEEP_SECONDS=0.04

# Playwright
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_QUEUE_MAX_JOBS=10

# Resource monitor
RAM_ALERT_THRESHOLD=85
DISK_ALERT_ROOT_USED_PCT=85
DISK_ALERT_CACHE_LIMIT_GB=5
RESOURCE_ALERT_THROTTLE_SECONDS=1800

# Operational cleanup
OPERATIONAL_RETENTION_SCRAPE_JOBS_DONE_HOURS=48
OPERATIONAL_RETENTION_SCRAPE_JOBS_FAILED_DAYS=7

# Filesystem cleanup
FILESYSTEM_CLEANUP_ENABLED=true
FILESYSTEM_CLEANUP_ARTIFACTS_DAYS=7
FILESYSTEM_CLEANUP_DEBUG_DAYS=3
FILESYSTEM_CLEANUP_MAX_DELETE_PER_RUN=500

# Backup
AUTOHUNTER_BACKUP_DIR=/var/backups/autohunter
AUTOHUNTER_BACKUP_MAX_AGE_HOURS=30
AUTOHUNTER_BACKUP_RETENTION_DAYS=14
```

---

## Operação e validação rápida

### Cleanup operacional — dry-run

```bash
python scripts/cleanup_operational_data.py
```

Esperado:

- imprime contagens;
- não executa `DELETE`;
- não escreve `system_logs`;
- exibe `scrape_jobs_queued_old_2h` quando houver fila antiga.

### Cleanup operacional — apply em produção PostgreSQL

```bash
python scripts/cleanup_operational_data.py --apply
```

Esperado:

- remove dados operacionais conforme retenção;
- recusa SQLite;
- registra warning de `queued` antigo se houver.

### Backup manual

```bash
DATABASE_URL='postgresql://user:<redacted>@host:5432/autohunter' \
AUTOHUNTER_BACKUP_DIR='/var/backups/autohunter' \
bash scripts/backup_db.sh
```

### Check de backup recente

```bash
AUTOHUNTER_BACKUP_DIR='/var/backups/autohunter' \
AUTOHUNTER_BACKUP_MAX_AGE_HOURS=30 \
bash scripts/check_latest_backup.sh
```

### Health admin

```text
/admin health
```

Esperado:

- mostra bloco `Backup` com `OK`, `WARNING` ou `FAIL`;
- mostra idade e diretório quando aplicável;
- não executa backup;
- não executa restore;
- não imprime `DATABASE_URL`.

---

## Validações recomendadas ao mexer nesta área

```bash
pytest -q
python -m compileall app scripts
bash -n scripts/backup_db.sh
bash -n scripts/check_latest_backup.sh
python scripts/cleanup_operational_data.py
```

Validações direcionadas úteis:

```bash
pytest -q tests/test_backup_health_service.py tests/test_admin_health_command.py
pytest -q tests/test_db_backup_shell_scripts.py
pytest -q tests/test_operational_cleanup.py tests/test_resource_monitor.py
pytest -q tests/test_sender_daily_limit.py
```

Ajustar os nomes dos testes se forem reorganizados, mas manter cobertura para:

- dry-run sem escrita;
- backup health OK/WARNING/FAIL;
- pacing entre envios;
- resource alert com throttle;
- cleanup granular de `scrape_jobs`.

---

## Itens que não devem voltar como tarefa de eficiência

Não abrir nova PR apenas para reavaliar estes itens sem evidência nova:

- trocar `selectinload` por `joinedload`;
- recriar cache de budget do sender;
- reimplementar `max_overflow`;
- apagar `queued` antigo automaticamente;
- rodar restore pelo Telegram;
- aumentar paralelismo Playwright no Raspberry sem métrica de RAM;
- tornar WebMotors requisito de saúde global.

---

## Pendências que pertencem ao lançamento, não à eficiência

As próximas tarefas importantes estão em `docs/LAUNCH_PLAN.md` e `docs/ROADMAP.md`:

- `LAUNCH-PAY-01`: Mercado Pago webhook ou aprovação admin em 1 clique;
- `LAUNCH-METRICS-01`: `/admin metrics` v1;
- `LAUNCH-PERF-01`: confirmar/criar índice `ix_notifications_user_sent_today`;
- `LAUNCH-LOAD-01`: teste de carga 50 usuários/24h;
- `LAUNCH-DIGEST-01`: digest semanal v2;
- `LAUNCH-COPY-01`: copy pública honesta sobre cobertura real das sources.

Essas tarefas podem usar métricas/health desta doc, mas não devem reabrir o pacote de eficiência operacional já fechado.
