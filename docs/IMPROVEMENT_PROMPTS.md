# AutoHunter — Prompts de Melhoria (Claude Code)

> Gerados a partir de análise do código real (`app/`, ~57k linhas). Cada bloco é um prompt independente, pronto para colar no Claude Code. Prioridade: **P0** = maior impacto/menor risco. Formato alinhado ao fluxo spec-kit do repo (`specs/`, `SPEC-LESSONS.md`).

---

## PERFORMANCE

### P0-1 — Auditoria e criação de índices no banco (maior ganho, menor risco)
**Evidência:** `app/models/car_listing.py` declara `source` e `external_id` como `Text` sem `index=True`; o hot-path de dedupe em `car_listings_repo.py` (l.178) filtra por `(source, external_id)` + `order_by(created_at)`, e o upsert usa `ON CONFLICT (source, external_id)`. Só 7 de N modelos declaram `Index()`.

```
Faça uma auditoria de índices de banco em todo o app/models e migrations. Objetivo: garantir cobertura de índice para TODAS as queries quentes.
1. Rode EXPLAIN (ANALYZE) nas queries mais executadas: dedupe/upsert de car_listings por (source, external_id), matching de listings ativas, notifications_queue por (wishlist_id, car_listing_id, status), auction_lots e fipe_catalog_entry.
2. Liste índices que EXISTEM no DB vs. os que o código pressupõe. Aponte full scans.
3. Gere uma migration Alembic adicionando os índices faltantes (unique em source+external_id se ainda não houver; composto para matching; parcial para status pendente em notifications).
4. Não altere modelos sem migration correspondente. Entregue: relatório antes/depois com custo estimado das queries e a migration testada.
```

### P0-2 — Paralelizar execução de sources dentro do tick
**Evidência:** `app/services/source_execution_service.py` (l.406) itera `for url, g in groups.items():` chamando `scrape_ingest_match` de forma **sequencial**. O scheduler já tem `ThreadPoolExecutor` (http=3), mas dentro de uma execução os grupos de URL rodam um após o outro.

```
Em app/services/source_execution_service.py, o loop `for url, g in groups.items()` executa scrapes sequencialmente. Paralelize a execução dos grupos de URL respeitando: (a) rate-limit/backoff por source (source_states), (b) um teto de concorrência configurável (settings), (c) isolamento de sessão SQLAlchemy por thread (não compartilhar Session entre threads). Use ThreadPoolExecutor com semáforo por-source. Meça latência do tick antes/depois num cenário com N wishlists. Não mude o resultado do matching/ingestão — só a ordem/concorrência. Adicione teste que garante que 1 source falhando não bloqueia as outras.
```

### P1-3 — Consolidar gerenciamento de sessão SQLAlchemy
**Evidência:** 126 usos diretos de `SessionLocal()` espalhados pelo `app/`. Sem unit-of-work consistente → churn de conexões, risco de sessão vazando entre threads, commits implícitos difíceis de rastrear.

```
Há 126 usos diretos de SessionLocal() no app/. Introduza um padrão único de unit-of-work: um context manager `with session_scope() as db:` que faz commit/rollback/close corretos, e injeção de Session nas camadas de serviço. Migre os call-sites incrementalmente começando pelos hot-paths (scheduler/jobs.py, source_execution_service, notifications_queue_service, matching). Garanta que nenhuma Session cruze fronteira de thread. Entregue: o helper, migração dos 10 arquivos mais quentes, e teste que detecta Session compartilhada entre threads.
```

### P1-4 — Cache do FIPE on-demand e revisão do rate limiter bloqueante
**Evidência:** `fipe_on_demand_lookup_service.py` (833 l.) + `fipe_rate_limiter.py`/`fipe_api_client.py` usam `time.sleep` para backoff dentro de threads. Lookups repetidos custam I/O e prendem worker.

```
Analise o caminho FIPE on-demand (fipe_on_demand_lookup_service, fipe_api_client, fipe_rate_limiter). Objetivo: reduzir chamadas externas e tempo preso em sleep. 1) Adicione cache com TTL para lookups (marca/modelo/ano) usando fipe_catalog_entry como fonte quente antes de bater na API. 2) Revise o rate limiter: o time.sleep bloqueia o worker inteiro — avalie mover para uma fila dedicada com backoff sem prender o pool http/browser. 3) Reporte hit-rate do cache e redução de chamadas externas em um cenário de bootstrap. Mantenha os testes de contrato FIPE passando.
```

---

## FUNCIONAMENTO / ROBUSTEZ

### P0-5 — Automatizar ativação Premium (webhook Mercado Pago)
**Evidência:** README aponta este como o **principal bloqueador comercial**: ativação Premium hoje é manual pelo admin. `/upgrade` já tem links configuráveis do Mercado Pago.

```
Implemente a ativação automática do plano Premium via webhook do Mercado Pago, como spec-kit (crie specs/0XX-mp-webhook-activation). Requisitos: endpoint FastAPI seguro (validação de assinatura/idempotência), mapear pagamento->telegram_chat_id, transição de plano com auditoria, mensagem de confirmação automática no Telegram, e fallback de aprovação manual de 1 clique para o admin quando o webhook falhar. Cubra: pagamento aprovado, recusado, estorno, e duplicado (idempotente). Não libere ativação sem pagamento confirmado. Entregue spec + implementação + testes de webhook.
```

### P1-6 — Resiliência e observabilidade dos scrapers
**Evidência:** 8 scrapers (`olx`, `mercadolivre`, `webmotors`, `icarros`, etc.) + `parse_failure.py`. Sites mudam layout; falhas silenciosas viram blind spots de matching.

```
Faça um hardening de resiliência dos scrapers em app/scrapers/. 1) Padronize detecção de "parse degradado" (título/preço vazios, 0 resultados súbito) usando decide_parse_failure, disparando alerta operacional e marcando source_state. 2) Adicione um "canary/golden sample" por source: um teste que roda contra HTML fixo em tests/fixtures e falha o CI se o seletor quebrar. 3) Exponha no /admin metrics a taxa de parse-failure por source nas últimas 24h. Priorize olx e mercadolivre (maiores). Não quebre scrapers que já funcionam.
```

### P2-7 — Refatorar handlers_admin.py (3319 linhas)
**Evidência:** `app/bot/handlers_admin.py` = 3319 linhas num único arquivo; `handlers_core.py` = 1470. Alto custo de manutenção e risco de regressão.

```
handlers_admin.py tem 3319 linhas. Refatore por domínio (sources, fipe, auctions, health, metrics, deploy) em módulos coesos sob app/bot/admin/, mantendo os mesmos comandos e callbacks registrados (sem mudança de comportamento observável). Faça em passos pequenos com os testes passando a cada extração. Entregue mapa antes/depois e cobertura de teste dos comandos admin críticos.
```

---

## EXPERIÊNCIA DO USUÁRIO (UX)

### P1-8 — Feedback de latência no bot (typing/progresso)
**Evidência:** só 20 usos de `chat_action` em todo `app/bot`. Ações longas (buscar agora, criar busca, digest) podem parecer travadas.

```
Melhore o feedback de latência no bot Telegram. Em toda operação que leva >1s (buscar agora, ingest de filtros, digest, admin metrics), envie chat_action "typing" e, quando fizer sentido, uma mensagem de progresso editável ("procurando em N fontes..."). Centralize num helper para não repetir. Meça: nenhuma ação longa sem indicador. Não altere a lógica de negócio.
```

### P1-9 — Consistência e clareza do /buscar
**Evidência:** `handlers.py`: mensagem promete "até 5 resultados", mas `manual_search(..., limit=30)`; usuário não vê progresso nem de quais fontes veio o resultado.

```
Reveja o fluxo /buscar (app/bot/handlers.py, search_service.manual_search). 1) Alinhe a promessa da UI com o limite real (mensagem diz "até 5", código busca 30). 2) Mostre de quais fontes vieram os resultados e quantas foram consultadas. 3) Se vazio, sugira variações do termo automaticamente (ex.: sem cidade, sinônimos de versão). 4) Ofereça CTA de "salvar como busca monitorada" ao final. Mantenha a execução em background (to_thread) e não bloqueie o loop async.
```

### P2-10 — Onboarding de primeira busca em 1 fluxo
**Evidência:** `/start`, `/menu`, criar busca via passos (`handlers_core.py`, `handlers_wishlist_ui.py`). Muitos passos até o primeiro valor entregue.

```
Desenhe um onboarding "time-to-first-alert" mais curto. Objetivo: do /start até a primeira busca salva em o mínimo de passos, com exemplos clicáveis (chips) e valores padrão inteligentes por filtro. Faça como spec (specs/0XX-onboarding). Entregue: fluxo proposto (antes/depois em nº de mensagens), protótipo dos handlers e teste de conversa simulada. Não remova o fluxo avançado de filtros para quem quiser.
```

---

## Como priorizar
1. **P0-1 (índices)** e **P0-2 (paralelizar sources)** — ganho de performance direto, baixo risco.
2. **P0-5 (webhook MP)** — desbloqueia receita/lançamento.
3. Depois P1 (sessão, FIPE, resiliência, UX de latência e /buscar), por fim P2 (refactor e onboarding).
