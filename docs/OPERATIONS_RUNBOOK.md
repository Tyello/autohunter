# AutoHunter — Operations Runbook

> Este runbook opera o runtime interno AutoHunter, que sustenta a marca pública Garagem Alvo.

## 1) Objetivo

Runbook de operação diária e triagem inicial de incidentes.

Quem usa:

- operação/dev on-call;
- agentes/IA que precisam diagnosticar sintomas sem depender de contexto informal;
- admin técnico do bot Telegram.

## 2) Blocos críticos do runtime

Para o produto funcionar:

1. Bot Telegram recebendo comandos e enviando mensagens.
2. Scheduler ativo gerando ticks.
3. Filas `scrape_jobs` sem travamento crônico.
4. Workers processando jobs.
5. Sources tradicionais ingerindo/matcheando/listando.
6. Sender drenando `notifications`.
7. Banco acessível e migrations em dia.
8. `source_configs` consistentes.
9. Para leilões: `auction_lots`, source elegível, categorias, runtime settings e dry-run/samples saudáveis.

## 3) Comandos admin essenciais

Saúde geral:

```text
/admin health
/admin health verbose
/admin audit
/admin sources
/admin source <source> ...
```

Leilões:

```text
/admin auctions settings
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
/admin auctions sources
/admin auctions quality
/admin auctions notify-run --source vip --limit-wishlists 5
```

## 4) Checklist de saúde geral

### Scheduler

- heartbeat recente em `system_logs` (`component='scheduler'`, `message='heartbeat'`).
- `source_runs` recentes para sources habilitadas.

### Filas/jobs

- `scrape_jobs` não deve crescer indefinidamente em `queued`.
- Poucos jobs em `running` por longos períodos.

### Workers

- updates em `scrape_jobs.finished_at`.
- ausência de erro recorrente em `http_queue_worker`/`browser_queue_worker`.

### Sources

- `source_states.next_allowed_at` não deve ficar perpetuamente no futuro para várias fontes.
- `consecutive_blocks`/`consecutive_failures` altos indicam regressão ou anti-bot.

### Notifications/sender

- `notifications` deve avançar de `queued` para `sent`.
- alta taxa de `failed/suppressed/discarded` requer investigação.

### Banco/configuração

- `source_configs` deve existir para plugins/registries.
- `is_enabled`, `sched_minutes`, browser flags e `user_eligible` coerentes.

## 5) Diagnóstico rápido — sequência prática

1. Rodar `/admin audit`.
2. Rodar `/admin health`.
3. Rodar `/admin sources`.
4. Verificar fila e últimas runs.
5. Validar source específica antes de mexer em parâmetros.
6. Para leilões, rodar `/admin auctions readiness` antes de qualquer ajuste de scheduler.

Queries úteis:

```sql
-- heartbeat mais recente
select created_at, level, component, message
from system_logs
where component = 'scheduler' and message = 'heartbeat'
order by created_at desc
limit 5;

-- fila por queue/status
select queue, status, count(*)
from scrape_jobs
group by queue, status
order by queue, status;

-- jobs running potencialmente travados
select id, source, queue, status, locked_at, started_at, attempt
from scrape_jobs
where status = 'running'
order by locked_at asc
limit 50;

-- últimas runs por source
select source, status, created_at, duration_ms, items_found, items_ingested, items_matched, notifications_queued, error
from source_runs
order by created_at desc
limit 100;

-- estado operacional por source
select source, next_allowed_at, last_run_at, last_effective_run_at, consecutive_blocks, consecutive_failures, last_status, last_error
from source_states
order by source;

-- configuração efetiva por source
select source, source_type, is_enabled, user_eligible, status, sched_minutes, cooldown_minutes, extra
from source_configs
order by source;

-- funil de notificações
select status, count(*)
from notifications
group by status
order by status;
```

## 6) Operação de leilões — piloto atual

Referência completa: `docs/AUCTION_RUNTIME.md`.

### Estado seguro esperado

```text
enabled=true
dry_run=true
categoria permitida: car
source user_eligible: vip_auctions
```

Envio real automático não deve ser ativado nesta fase.

### Configurar piloto via Telegram

```text
/admin auctions settings set enabled true
/admin auctions settings set dry_run true
/admin auctions settings set min_score 60
/admin auctions settings set max_lot_age_hours 48
/admin auctions settings set max_wishlists_per_run 20
/admin auctions settings set max_per_wishlist 1
/admin auctions settings set max_per_user_per_day 3
```

Garantir source/categoria:

```text
/admin source vip enable
/admin source vip user-enable
/admin source vip categories set car
```

Validar:

```text
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
```

### Dry-run manual

```text
/admin auctions notify-run --source vip --limit-wishlists 5
```

Depois revisar:

```text
/admin auctions notify-samples
```

Critérios de aceite:

- samples com source amigável;
- somente automóveis;
- score >= mínimo;
- lote com lance;
- lote recente;
- copy contém `Lance não é preço final.`;
- sem moto/caminhão/imóvel/outros;
- volume aceitável.

### Status e readiness

```text
/admin auctions notify-status
/admin auctions readiness
```

Interpretação:

- `enabled=false`: scheduler de leilões desligado.
- `enabled=true + dry_run=true`: simulação automática ativa; nenhum alerta real.
- `kill_switch ativo`: env bloqueou efetivamente `enabled`.
- `fail` no readiness: não avançar.
- `warn` no readiness: revisar antes de prosseguir.

### Rollback rápido de leilões

Desligar scheduler de leilões via runtime:

```text
/admin auctions settings set enabled false
```

Remover elegibilidade da source:

```text
/admin source vip user-disable
```

Desligar source:

```text
/admin source vip disable
```

Kill switch por env em emergência:

```text
AUCTION_NOTIFICATIONS_KILL_SWITCH=true
```

Depois reiniciar scheduler/bot se alteração foi no `.env`.

### O que não fazer

- Não tentar `/admin auctions settings set dry_run false`: comando deve bloquear nesta fase.
- Não permitir categorias além de `car` no piloto sem decisão explícita.
- Não tornar source experimental user_eligible sem validar qualidade.
- Não enviar alerta real automático sem nova PR/revisão.

## 7) Sources frágeis / anti-bot

Bloqueios 403/429/challenge podem ser estruturais da origem.

### WebMotors

- Bloqueio anti-bot recorrente, incluindo challenge com HTTP 200.
- Se outras sources prioritárias estiverem saudáveis, WebMotors bloqueada não deve ser incidente crítico diário.
- Ação padrão: monitorar, manter backoff e despriorizar.
- Não aumentar agressividade e não tentar burlar challenge/captcha.

## 8) Recovery básico

1. Confirmar que scheduler está de pé.
2. Corrigir config inválida em uma source específica.
3. Aguardar backoff quando aplicável.
4. Deixar workers drenarem fila.
5. Se job travou, usar caminho seguro de requeue previsto.
6. Registrar ação e impacto.

### O que não fazer impulsivamente

- Não desligar múltiplas sources sem diagnóstico.
- Não zerar/limpar fila/notificações em produção.
- Não remover caminho legado no meio de incidente.
- Não ligar envio real automático de leilões.

## 9) Storage / Disk pressure

Diagnóstico rápido:

```bash
df -h
journalctl --disk-usage
du -xh --max-depth=2 /var/lib/autohunter /var/cache/autohunter /var/log/autohunter
python scripts/disk_audit.py
```

Ações:

1. Rodar `python scripts/disk_audit.py`.
2. Verificar `journalctl --disk-usage`.
3. Confirmar `FILESYSTEM_CLEANUP_ENABLED=true`.
4. Reduzir TTLs de artifacts/debug temporariamente se necessário.

O cleanup diário remove artefatos antigos de audit/debug, mas não remove storage persistente sensível como Playwright storage/profile sem ação explícita.

## 10) Backup / restore

Referência: `docs/BACKUP_RESTORE.md`.

Nunca rodar restore real sem dry-run, validação e janela operacional.

## 11) Alembic

- Manter head único.
- Rodar `alembic heads` antes de PR com migration.
- Validar migrations reais em PostgreSQL/Supabase quando houver alteração de schema.

## 12) Premium manual

Fluxo atual:

- usuário clica/recebe link Mercado Pago;
- admin valida comprovante ou painel Mercado Pago;
- admin ativa manualmente:

```text
/admin premium activate <chat_id> monthly
/admin premium activate <chat_id> annual
/admin premium status <chat_id>
```

## 13) Quando escalar investigação

Escalar quando houver:

- stale global persistente;
- muitas sources bloqueadas simultaneamente;
- fila crescendo sem drenagem;
- sender sem progresso;
- regressão contínua de matching;
- leilões gerando samples ruins repetidamente mesmo com gates.

## 14) Referências

- `README.md`
- `AGENTS.md`
- `docs/PROJECT_GUIDELINE.md`
- `docs/AUCTION_RUNTIME.md`
- `docs/LEGACY_INVENTORY.md`
- `docs/BACKUP_RESTORE.md`
