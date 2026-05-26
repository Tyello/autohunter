# Eficiência operacional — Raspberry Pi 4 (4GB)

Atualizado em: 2026-05-25.  
Estado confrontado com a `main` após os merges recentes de eficiência, backup, backup health, tracking e `/admin metrics`.

Documento operacional para manter o AutoHunter/Garagem Alvo estável 24/7 em Raspberry Pi 4 com 4GB.

---

## Escopo

Este documento cobre eficiência e operação do runtime:

- sender e fila de notificações;
- tuning de scheduler, PostgreSQL e Playwright;
- monitoramento de RAM/disco/cache;
- retenção e limpeza de dados operacionais;
- backup observável no admin health;
- validação mínima de carga no Raspberry.

Este documento **não** é roadmap de billing, growth, UX ou assinatura. Esses temas ficam em `02_FLUXO.md`, `04_LAUNCH_PLAN.md`, `05_PLAN.md` e `06_SUBSCRIPTION.md`.

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
- `/admin metrics` v1 para leitura operacional de usuários, buscas, alertas, backlog e conversão.
- Índice `ix_notifications_user_sent_today` resolvido e validado em PostgreSQL/Supabase.

### Ainda aberto neste eixo

- Teste de carga controlado no Raspberry real: 50 usuários / 24h.
- Coleta de baseline real de RAM, backlog, duração de runs, sender e Playwright sob carga.

### Fora deste documento

- Pagamento/ativação Premium sem intervenção manual.
- Trial e Founders.
- Digest semanal v2 como experiência do usuário.
- Growth/beta/founders.

---

## EFF-01 — Sender eager-load ✅

**Status:** resolvido.

`claim_queued_notifications` carrega relacionamentos com:

- `selectinload(Notification.user)`;
- `selectinload(Notification.car_listing)`.

Regra: não trocar para `joinedload` sem benchmark.

Referência: `app/services/notification_delivery_service.py`.

---

## EFF-02 — Cache de limite por usuário no sender ✅

**Status:** resolvido.

`app/scheduler/jobs_send.py` usa `user_budget_cache` para reduzir consultas repetidas de limite/uso diário durante o batch.

---

## EFF-03 — SQLAlchemy `max_overflow` ✅

**Status:** resolvido.

`app/db/session.py` aplica `max_overflow=settings.db_max_overflow` e demais parâmetros compatíveis com backend.

---

## EFF-04 — Profile PostgreSQL para Raspberry Pi ✅

**Status:** implementado/documentado.

Arquivo de referência:

```text
config/raspberry-pi/postgresql.conf
```

Parâmetros recomendados:

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

Nota: `synchronous_commit = off` melhora previsibilidade em SD card, mas aceita perda de poucos segundos de dados em crash abrupto.

---

## EFF-05 — Tuning sender/scheduler + pacing Telegram ✅

**Status:** implementado.

Profile recomendado:

```env
SCHEDULER_TICK_SECONDS=90
NOTIFICATION_SENDER_BATCH_SIZE=50
NOTIFICATION_SENDER_SLEEP_SECONDS=0.04
```

Comportamento atual:

- sleep entre envios bem-sucedidos;
- sem sleep para notificações bloqueadas por limite;
- sem sleep para notificações sem destino;
- sem sleep antes do primeiro envio;
- valores inválidos/negativos tratados de forma conservadora.

---

## EFF-06 — Profile Playwright para RPi ✅

**Status:** implementado/documentado.

Profile recomendado:

```env
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_QUEUE_MAX_JOBS=10
```

Racional:

- menor paralelismo de browser;
- menor pressão de RAM;
- operação contínua mais previsível;
- adequado ao Raspberry Pi 4GB.

---

## EFF-07 — Monitoramento automático de RAM/disco/cache ✅

**Status:** implementado.

Cobre:

- RAM usada acima de `RAM_ALERT_THRESHOLD`;
- uso de `/` acima de `DISK_ALERT_ROOT_USED_PCT`;
- cache acima de `DISK_ALERT_CACHE_LIMIT_GB`.

Throttle:

```env
RESOURCE_ALERT_THROTTLE_SECONDS=1800
```

Regras:

- alertas somente para chat/admin;
- cooldown por chave;
- falha de leitura não derruba scheduler.

---

## EFF-08 — Cleanup granular de `scrape_jobs` ✅

**Status:** implementado.

Retenção:

```env
OPERATIONAL_RETENTION_SCRAPE_JOBS_DONE_HOURS=48
OPERATIONAL_RETENTION_SCRAPE_JOBS_FAILED_DAYS=7
```

Comportamento:

- remove `done` após 48h;
- remove `failed` após 7 dias;
- não remove `queued` por padrão;
- detecta `queued` com mais de 2h;
- dry-run apenas imprime diagnóstico;
- `--apply` registra warning em `system_logs` quando houver `queued` antigo.

Segurança:

- `python scripts/cleanup_operational_data.py` é dry-run;
- `--apply` recusa SQLite;
- `queued` antigo é sinal de operação/scheduler, não lixo para apagar automaticamente.

---

## EFF-09 — Backup observável no admin health ✅

**Status:** implementado.

Backup real:

- `scripts/backup_db.sh`;
- dump completo via `pg_dump`;
- saída `.sql.gz`;
- arquivo temporário antes do final;
- retenção via `AUTOHUNTER_BACKUP_RETENTION_DAYS`.

Check de frescor:

- `scripts/check_latest_backup.sh`;
- `app/services/backup_health_service.py`;
- `/admin health`.

Variáveis:

```env
AUTOHUNTER_BACKUP_DIR=/var/backups/autohunter
AUTOHUNTER_BACKUP_MAX_AGE_HOURS=30
AUTOHUNTER_BACKUP_RETENTION_DAYS=14
```

Estados em `/admin health`:

- `OK`: backup recente;
- `WARNING`: backup antigo;
- `FAIL`: diretório ausente ou nenhum backup encontrado.

Restore continua manual e destrutivo. Não há restore automático via bot.

---

## EFF-10 — Filesystem cleanup seguro ✅

**Status:** implementado.

Agendamento:

- `app/scheduler/run.py`;
- job id `filesystem_cleanup_daily`;
- cron diário às 03:00 UTC.

Execução:

- `app/scheduler/filesystem_cleanup_job.py::job_filesystem_cleanup_daily`;
- `app/services/filesystem_cleanup_service.py::run_filesystem_cleanup`.

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

## EFF-11 — `/admin metrics` v1 ✅

**Status:** implementado.

Embora seja também uma ferramenta de produto/beta, ela ajuda eficiência operacional ao mostrar backlog e volume de alertas.

Arquivo:

```text
app/bot/admin_handlers_metrics.py
```

Dispatcher:

```text
app/bot/handlers_admin.py
```

Métricas atuais:

- usuários ativos totais;
- novos usuários 7d;
- usuários com busca ativa;
- usuários que receberam alerta 7d;
- buscas criadas 7d;
- buscas ativas;
- alertas enviados hoje/7d;
- backlog atual;
- Free/Premium;
- sources 7d.

**Ação:** não reabrir `/admin metrics` como pendência de eficiência. Evoluções futuras devem ser incrementais.

---

## EFF-12 — Teste de carga Raspberry real

**Status:** aberto.

Objetivo: validar que as melhorias anteriores sustentam operação realista no Raspberry Pi 4GB.

Cenário mínimo:

```bash
python scripts/load_test_seed.py --users 50 --wishlists-per-user 2
```

Monitoramento por 24h:

```bash
watch -n 300 "free -h && ps aux | grep playwright | wc -l && psql -c 'SELECT status, count(*) FROM scrape_jobs GROUP BY status;'"
```

Durante o teste, acompanhar também:

```text
/admin health
/admin metrics
/admin sources
```

Critérios:

- RAM estável;
- backlog não cresce continuamente;
- sender sem atraso maior que 5 minutos;
- Playwright sem processo zumbi;
- cleanup não remove dados indevidos;
- backup health permanece visível.

---

## Profile recomendado Raspberry Pi 4 — produção

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

### Cleanup operacional — apply em produção PostgreSQL

```bash
python scripts/cleanup_operational_data.py --apply
```

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

### Health e métricas admin

```text
/admin health
/admin metrics
```

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
pytest -q tests/test_cleanup_operational_data.py tests/test_resource_monitor.py
pytest -q tests/test_sender_daily_limit.py
pytest -q tests/test_admin_metrics_command.py
```

---

## Itens que não devem voltar como tarefa de eficiência

Não abrir nova PR apenas para reavaliar estes itens sem evidência nova:

- trocar `selectinload` por `joinedload`;
- recriar cache de budget do sender;
- reimplementar `max_overflow`;
- recriar índice `ix_notifications_user_sent_today`;
- apagar `queued` antigo automaticamente;
- rodar restore pelo Telegram;
- aumentar paralelismo Playwright no Raspberry sem métrica de RAM;
- tornar WebMotors requisito de saúde global;
- reimplementar `/admin metrics` v1.

---

## Pendências que pertencem ao lançamento, não à eficiência

As próximas tarefas importantes estão em outros documentos:

- pagamento/ativação Premium sem gargalo manual;
- trial 7 dias;
- Founders;
- digest semanal v2;
- copy pública honesta sobre cobertura real das sources;
- beta/growth.

Essas tarefas podem usar métricas/health desta doc, mas não devem reabrir o pacote de eficiência operacional já fechado.
