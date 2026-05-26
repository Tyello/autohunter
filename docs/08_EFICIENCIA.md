# Eficiência operacional — Raspberry Pi 4 (4GB)

Atualizado em: 2026-05-25.

> Documento dono de eficiência, carga, recursos do Raspberry, sender, cleanup, backup e métricas operacionais.  
> Não detalhar aqui UX, assinatura, pricing, bugs ou arquitetura.

---

## Escopo deste documento

Este documento cobre:

- sender e fila de notificações;
- tuning de scheduler, PostgreSQL e Playwright;
- monitoramento de RAM/disco/cache;
- retenção e limpeza operacional;
- backup health;
- `/admin metrics` como leitura operacional;
- teste de carga no Raspberry.

| Assunto relacionado | Documento dono |
|---|---|
| Bugs e validações técnicas | `07_BUGS.md` |
| Arquitetura/refactor | `03_ARQUITETURA.md` |
| Pagamento e assinatura | `06_SUBSCRIPTION.md` |
| Trial, Founders, limites | `05_PLAN.md` |
| UX/digest/copy | `01_UX.md` |
| Beta/go-to-market | `04_LAUNCH_PLAN.md` |

---

## Estado consolidado da `main`

### Pronto / não reabrir

- Sender com eager-load e cache intra-batch de limite por usuário.
- SQLAlchemy pool com `max_overflow` configurável.
- Pacing entre envios Telegram.
- Profile RPi para scheduler, sender e Playwright.
- Monitoramento admin de RAM/disco/cache com throttle.
- Cleanup granular de `scrape_jobs`.
- Filesystem cleanup diário seguro.
- Backup PostgreSQL via `pg_dump`.
- Verificação de frescor de backup via script e `/admin health`.
- `/admin metrics` v1.
- Índice `ix_notifications_user_sent_today` resolvido e validado.

### Aberto neste eixo

- Teste de carga controlado no Raspberry real: 50 usuários / 24h.
- Baseline real de RAM, backlog, duração de runs, sender e Playwright sob carga.

---

## Componentes concluídos

### EFF-01 — Sender

**Status:** resolvido.

Inclui:

- eager-load com `selectinload`;
- cache de budget por usuário no batch;
- lote configurável;
- pacing configurável entre envios.

Regra: não trocar `selectinload` por `joinedload` sem benchmark.

### EFF-02 — Banco e índices

**Status:** resolvido.

Inclui:

- pool SQLAlchemy ajustado;
- índice parcial de notifications validado;
- compatibilidade SQLite em testes.

Detalhes de bug/validação: `07_BUGS.md`.

### EFF-03 — Playwright RPi

**Status:** resolvido.

Profile recomendado:

```env
PLAYWRIGHT_MAX_CONTEXTS=1
PLAYWRIGHT_QUEUE_MAX_JOBS=10
```

### EFF-04 — Monitoramento de recursos

**Status:** implementado.

Cobre RAM, disco raiz e cache, com throttle por chave e alertas somente ao admin.

### EFF-05 — Cleanup operacional

**Status:** implementado.

Inclui:

- retenção granular de `scrape_jobs`;
- cleanup de filesystem;
- dry-run seguro;
- `--apply` recusando SQLite;
- `queued` antigo tratado como sinal operacional, não lixo.

Observação: cleanup de filesystem atua apenas em artifacts/debug permitidos; `pw-browsers`, profiles e storage Playwright não são limpos automaticamente.

### EFF-06 — Backup health

**Status:** implementado.

Inclui:

- `scripts/backup_db.sh`;
- `scripts/check_latest_backup.sh`;
- `app/services/backup_health_service.py`;
- bloco de backup em `/admin health`.

Restore continua manual e destrutivo. Não há restore automático via bot.

### EFF-07 — `/admin metrics` v1

**Status:** implementado.

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

Evoluções futuras de funil/cohort devem ser incrementais, não reimplementação do v1.

---

## EFF-08 — Teste de carga Raspberry real

**Status:** aberto.

Objetivo: validar que as melhorias sustentam operação realista no Raspberry Pi 4GB.

Cenário mínimo:

```bash
python scripts/load_test_seed.py --users 50 --wishlists-per-user 2
```

Monitoramento por 24h:

```bash
watch -n 300 "free -h && ps aux | grep playwright | wc -l && psql -c 'SELECT status, count(*) FROM scrape_jobs GROUP BY status;'"
```

Acompanhar também:

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
FILESYSTEM_CLEANUP_ENABLED=true
FILESYSTEM_CLEANUP_ARTIFACTS_DAYS=7
FILESYSTEM_CLEANUP_DEBUG_DAYS=3
FILESYSTEM_CLEANUP_MAX_DELETE_PER_RUN=500
AUTOHUNTER_BACKUP_DIR=/var/backups/autohunter
AUTOHUNTER_BACKUP_MAX_AGE_HOURS=30
AUTOHUNTER_BACKUP_RETENTION_DAYS=14
```

---

## Operação e validação rápida

```bash
python scripts/cleanup_operational_data.py
python scripts/cleanup_operational_data.py --apply
bash -n scripts/backup_db.sh
bash -n scripts/check_latest_backup.sh
pytest -q tests/test_admin_metrics_command.py
pytest -q tests/test_backup_health_service.py tests/test_admin_health_command.py
pytest -q tests/test_cleanup_operational_data.py tests/test_resource_monitor.py
pytest -q tests/test_sender_daily_limit.py
```

Admin:

```text
/admin health
/admin metrics
/admin sources
```

---

## Não reabrir como eficiência sem evidência nova

- trocar `selectinload` por `joinedload`;
- recriar cache de budget do sender;
- reimplementar `max_overflow`;
- recriar índice de notifications;
- apagar `queued` antigo automaticamente;
- restore pelo Telegram;
- aumentar paralelismo Playwright no Raspberry sem métrica;
- tornar WebMotors requisito de saúde global;
- reimplementar `/admin metrics`.
