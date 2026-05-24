# Eficiência operacional — Raspberry Pi 4 (4GB)

Documento operacional para manter o AutoHunter estável 24/7 no Raspberry Pi.

## Escopo

- Este documento **não reabre** itens já corrigidos no código.
- Foco: tuning de runtime, previsibilidade de envio Telegram, monitoramento e retenção de dados.

---

## Resolvido (não reabrir)

### EFF-01 — Sender eager-load

**Status:** resolvido.

- `claim_queued_notifications` já carrega relacionamentos com `selectinload(Notification.user)` e `selectinload(Notification.car_listing)`.
- A implementação atual usa **selectinload** (não joinedload).
- **Não trocar para joinedload** sem benchmark/necessidade comprovada.

Referência: `app/services/notification_delivery_service.py`.

### EFF-02 — Cache de limite por usuário no sender

**Status:** resolvido.

- `app/scheduler/jobs_send.py` já usa cache intra-batch (`user_budget_cache`) para reduzir consultas repetidas de limite/uso diário.

Referência: `app/scheduler/jobs_send.py`.

### EFF-03 — SQLAlchemy `max_overflow`

**Status:** resolvido.

- `app/db/session.py` já aplica `max_overflow=settings.db_max_overflow`.
- `docs/07_BUGS.md` já marca BUG-01 como corrigido.

Referências: `app/db/session.py`, `docs/07_BUGS.md`.

---

## Pendências reais (implementadas neste ciclo)

### EFF-04 — Profile PostgreSQL para Raspberry Pi

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

**Nota operacional importante:**

- `synchronous_commit = off` reduz fsync e melhora previsibilidade em SD card.
- Use apenas se for aceitável perder poucos segundos de logs/eventos em crash abrupto.

### EFF-05 — Tuning sender/scheduler + pacing Telegram

Profile recomendado para produção RPi 4:

```env
SCHEDULER_TICK_SECONDS=90
NOTIFICATION_SENDER_BATCH_SIZE=50
NOTIFICATION_SENDER_SLEEP_SECONDS=0.04
```

Implementação:

- Sender aplica sleep **somente entre envios bem-sucedidos** (não bloqueados/sem destino).
- Objetivo: evitar burst sem pacing quando batch aumenta.

### EFF-06 — Consolidar profile Playwright RPi

Profile recomendado para produção RPi 4:

```env
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_QUEUE_MAX_JOBS=10
```

Racional: menor paralelismo browser em troca de estabilidade de RAM e operação contínua.

### EFF-07 — Monitoramento automático de RAM/disco

Monitor admin já existente foi estendido para recursos:

- alerta de RAM por `ram_alert_threshold`;
- alerta de uso de `/` por `disk_alert_root_used_pct`;
- alerta de tamanho de cache por `disk_alert_cache_limit_gb`.

Throttle:

- `resource_alert_throttle_seconds` (default 1800s), aplicado por chave de alerta.

Alerta é enviado apenas para chats de admin via `send_admin_text` (fluxo do `job_admin_monitor`).

### EFF-08 — Cleanup granular de `scrape_jobs`

Retenção agora separada:

- `operational_retention_scrape_jobs_done_hours=48`
- `operational_retention_scrape_jobs_failed_days=7`

Comportamento:

- remove `done` após 48h;
- remove `failed` após 7 dias;
- **não remove `queued` por padrão**.

Diagnóstico operacional:

- detecta `queued` com mais de 2h;
- registra warning em `system_logs` durante o cleanup.

---

## Defaults DEV vs profile RPi produção

### Defaults seguros (desenvolvimento)

Manter defaults conservadores em `app/core/settings.py`.

### Profile recomendado Raspberry Pi 4 (produção)

Aplicar via `.env`/systemd:

```env
SCHEDULER_TICK_SECONDS=90
NOTIFICATION_SENDER_BATCH_SIZE=50
NOTIFICATION_SENDER_SLEEP_SECONDS=0.04
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_QUEUE_MAX_JOBS=10
RAM_ALERT_THRESHOLD=85
DISK_ALERT_ROOT_USED_PCT=85
DISK_ALERT_CACHE_LIMIT_GB=5
RESOURCE_ALERT_THROTTLE_SECONDS=1800
OPERATIONAL_RETENTION_SCRAPE_JOBS_DONE_HOURS=48
OPERATIONAL_RETENTION_SCRAPE_JOBS_FAILED_DAYS=7
```

---

## Operação e validação rápida

### Cleanup operacional (dry-run)

```bash
python scripts/cleanup_operational_data.py
```

### Cleanup operacional (apply em produção PostgreSQL)

```bash
python scripts/cleanup_operational_data.py --apply
```

> O script recusa `--apply` em SQLite por segurança.

### Filesystem cleanup

Já implementado no scheduler (`filesystem_cleanup_daily`) usando:

- `filesystem_cleanup_enabled`
- `filesystem_cleanup_artifacts_days`
- `filesystem_cleanup_debug_days`
- `filesystem_cleanup_max_delete_per_run`

Escopo seguro: somente diretórios de runtime cache/debug (sem apagar DB/cookies/perfis persistentes).

---

## Fora de escopo deste documento

- Mudanças de arquitetura v1/v2/dual-run.
- Liberação de envio automático real de leilões fora dos gates atuais.
- Billing automático (webhook Mercado Pago) ainda depende de implementação específica.
