# AutoHunter — Operations Runbook (curto)

## 1) Objetivo do runbook
Este runbook serve para operação diária e triagem inicial de incidentes do AutoHunter.

Quem usa:
- pessoas de operação/dev on-call;
- IAs/agentes que precisam diagnosticar sintomas básicos sem depender de contexto informal.

## 2) Visão rápida da operação
Para o produto funcionar (Telegram-first), estes blocos precisam estar saudáveis:

1. Bot Telegram recebendo comandos e disponível para envio.
2. Scheduler ativo gerando ticks.
3. Filas `scrape_jobs` (`http`/`browser`) sem travamento crônico.
4. Workers processando jobs e atualizando `source_runs` / `source_states`.
5. Ingestão + matching criando `notifications` quando há anúncios compatíveis.
6. Sender drenando `notifications` e marcando status.
7. Banco acessível, com `source_configs` consistentes.

## 3) Checklist de saúde

### Scheduler
- heartbeat recente em `system_logs` (`component='scheduler'`, `message='heartbeat'`).
- `source_runs` recentes para sources habilitadas.

### Filas/jobs
- `scrape_jobs` não pode ficar crescendo indefinidamente em `queued`.
- Poucos jobs em `running` por longos períodos (stuck).

### Workers
- presença de updates em `scrape_jobs.finished_at`.
- ausência de erro recorrente em `http_queue_worker`/`browser_queue_worker`.

### Sources
- `source_states.next_allowed_at` não deve ficar perpetuamente no futuro para várias fontes.
- `consecutive_blocks`/`consecutive_failures` altos indicam regressão ou anti-bot.

### Notifications/sender
- `notifications` deve avançar de `queued` -> `sent`.
- taxa alta de `failed/suppressed/discarded` requer investigação.

### Banco/configuração
- `source_configs` deve existir para plugins registrados.
- `is_enabled`, `sched_minutes`, `force_browser`, `browser_fallback_enabled` coerentes.

### Telegram/admin
- comandos admin funcionando (`/admin health`, `/admin sources`).
- alertas do monitor chegando nos chats admin configurados.

## 4) Sinais de problema
- Source sem execução efetiva há tempo acima de `sched_minutes * fator_stale`.
- Source com `blocked/error` recorrente em `source_runs`.
- Backoff contínuo em `source_states.next_allowed_at`.
- Fila acumulando (`scrape_jobs.status='queued'` crescendo).
- Sem notificações novas quando há ingestão/match esperados.
- Sender com retries excessivos ou muitos `failed`.
- Grande diferença entre `items_ingested` e `items_matched` por longos períodos (sintoma de drift em matching/query/filtros).

## 5) Diagnóstico rápido (sequência prática)
1. **Checar heartbeat e stale global**
   - olhar `/admin/health` e logs `admin_monitor`/`scheduler`.
2. **Checar fila**
   - contar jobs por status e queue.
3. **Checar última execução por source**
   - `source_runs` (status, erro, duração, items_*).
4. **Checar estado operacional por source**
   - `source_states` (backoff, consecutive_*).
5. **Checar config efetiva**
   - `source_configs` (enabled, schedule, browser flags).
6. **Checar notificação**
   - evolução de `notifications` por status e `next_attempt_at`.
7. **Só então** mexer em parâmetros (enable/sched/cooldown/force_browser).

Consultas SQL úteis (PostgreSQL):

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
select source, is_enabled, sched_minutes, cooldown_minutes, rate_limit_seconds, force_browser, browser_fallback_enabled
from source_configs
order by source;

-- funil de notificações
select status, count(*)
from notifications
group by status
order by status;
```

## 6) Recovery básico (ações seguras)
1. Confirmar que scheduler está de pé.
2. Corrigir config inválida (ex.: `sched_minutes=0` acidental em source crítica).
3. Ajustar source específica (não todas):
   - reduzir agressividade;
   - habilitar/desabilitar `force_browser` conforme sintoma;
   - esperar janela de backoff quando aplicável.
4. Deixar workers drenarem fila e reavaliar métricas.
5. Se job travou, usar caminho seguro já previsto (requeue de stale running via serviço).
6. Registrar ação e impacto para não perder contexto.

### O que não fazer impulsivamente
- Não desligar múltiplas sources sem diagnóstico mínimo.
- Não zerar/limpar tabelas de fila/notificação em produção.
- Não remover caminho “legacy” no meio do incidente.

## 7) Sources frágeis / anti-bot
O código já trata bloqueios (403/429/challenge) e possui backoff progressivo por source.

Implicação operacional: parte das falhas é estrutural da origem (anti-bot, variação de HTML/JS), não necessariamente bug interno imediato.

Em fontes JS-heavy, alternância HTTP/browser pode ser necessária conforme contexto da execução.

## 8) Quando escalar investigação
Escalar para investigação mais profunda quando houver:
- stale global persistente mesmo com scheduler ativo;
- muitas sources bloqueadas simultaneamente por período prolongado;
- crescimento de fila sem drenagem apesar de workers ativos;
- sender sem progresso por longo período;
- regressão contínua de matching (ingere mas não notifica) sem explicação de produto.

## 9) Referências
- `README.md`
- `AGENTS.md`
- `docs/PROJECT_GUIDELINE.md`
- `docs/LEGACY_INVENTORY.md`

## 10) Validação pós-migration (tracking de wishlist)
Quando subir migration de `wishlist_tracked_listings`, rode:

```bash
python scripts/check_tracking_post_migration.py
```

Esse check falha (`exit 1`) se houver:
- tabela de tracking ausente;
- slots fora do intervalo 1..3;
- wishlists com mais de 3 rastreados;
- vínculos órfãos com `wishlists`;
- vínculos órfãos com `car_listings` quando `car_listing_id` não for nulo.

Queries úteis de triagem:

```sql
-- rastreados por wishlist (top)
select wishlist_id, count(*) as tracked
from wishlist_tracked_listings
group by wishlist_id
order by tracked desc
limit 20;

-- wishlists com mais de 3 rastreados (não esperado)
select wishlist_id, count(*) as tracked
from wishlist_tracked_listings
group by wishlist_id
having count(*) > 3;

-- slots fora da faixa operacional
select id, wishlist_id, slot
from wishlist_tracked_listings
where slot < 1 or slot > 3;

-- linhas de tracking sem anúncio associado (esperado em casos de remoção de listing)
select count(*) as tracking_sem_listing
from wishlist_tracked_listings
where car_listing_id is null;

-- wishlists legadas sem filtros novos (city/state/color)
select count(*) as wishlists_sem_filtros_novos
from wishlists w
where not exists (
  select 1 from wishlist_filters wf
  where wf.wishlist_id = w.id
    and wf.field in ('color', 'city', 'state')
);
```
