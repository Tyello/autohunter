# Launch Readiness v1 — Garagem Alvo / AutoHunter

Atualizado em: 2026-08-08.

## 1. Resumo executivo

A auditoria confirma que o Garagem Alvo já tem a espinha dorsal de um produto Telegram-first: bot, criação e gestão de buscas, scheduler, filas persistentes, workers, ingestão, matching, notificações, sender, tracking, planos Free/Premium e piloto controlado de leilões. O principal risco para lançamento público não é a ausência do runtime, mas a confiabilidade operacional em três pontos: qualidade visual dos alertas OLX, atualização FIPE auditável e controle de churn/IO no banco Supabase.

Classificação geral de lançamento:

- **Crítico:** thumbnails OLX sem fallback de detalhe/OG/JSON-LD/galeria; atualização FIPE mensal sem job automático registrado no scheduler; ausência de auditoria dedicada `fipe_update_runs`; ausência de política explícita de retenção para `car_listings`/histórico de atividade de alta cardinalidade.
- **Atenção:** sources v1/v2/dual e browser fallback exigem operação cuidadosa; sender e notifications têm hardening, mas precisam de métrica de backlog em go-live; leilões devem permanecer em piloto/dry-run; billing automático ainda não é fonte de verdade.
- **Estável:** arquitetura Telegram-first, filas persistentes, health/admin, matching/dedupe, tracking básico, digest semanal, gates de leilões e scripts de limpeza operacional já existem.

Recomendação objetiva: tratar os três bloqueadores abaixo como **P0 antes de beta público**. Se não houver tempo para implementar tudo nesta janela, o fallback aceitável é bloquear ou degradar controladamente a source/feature afetada, com comunicação interna e checklist de validação diária.

## 2. Estado atual

### 2.1 Arquitetura e fluxo de produto

O fluxo confirmado no código/documentação viva é:

```text
wishlist -> scheduler tick -> scrape_jobs -> workers http/browser -> scrape+normalização+ingestão -> dedupe -> matching -> notifications -> sender Telegram
```

A API/FastAPI é auxiliar; a jornada de usuário final ocorre no Telegram. Isso significa que falhas em thumbnail, FIPE e sender impactam diretamente a percepção do usuário nos alertas, mesmo quando a API está saudável.

### 2.2 Classificação por área

| Área | Estado | Evidência técnica | Risco de lançamento | Próxima ação |
|---|---|---|---|---|
| Scheduler | **Atenção** | `app/scheduler/run.py` registra ticks por source, heartbeat, workers HTTP/browser, sender, leilões, digest, monitor admin e limpezas. Não registra job mensal FIPE. | FIPE não atualiza automaticamente; jobs críticos podem parecer saudáveis sem cobrir catálogo/preço. | Adicionar job mensal FIPE e painel admin de última execução. |
| Workers | **Estável** | Filas HTTP/browser persistentes em `scrape_jobs`, com workers separados e caps por configuração. | Backlog pode crescer se source bloqueia ou browser degrada. | Monitorar fila por status/idade no go-live. |
| Sources tradicionais | **Atenção** | Registry suporta OLX, Mercado Livre, Chaves na Mão, WebMotors, TurboClass etc.; operação efetiva é `source_configs`. | Anti-bot e divergência v1/v2 podem afetar cobertura. | Validar source ativa por DB e dual-run antes de flips. |
| OLX | **Crítico** | Scraper extrai thumb só de `images[0].originalWebp/original` no `__NEXT_DATA__` e de `img.src` nos cards. Não há fallback de página de detalhe, `og:image`, `twitter:image`, JSON-LD ou galeria. | Alertas sem foto quando search payload vem sem imagem, lazy image ou CDN em outro atributo. | Implementar fallback robusto e testes com fixtures reais. |
| Matching/dedupe | **Estável** | Dedupe por `(source, external_id)` e notificação por wishlist/listing; leilões têm dedupe lógico por lote. | Baixo, desde que migrations estejam em dia. | Rodar testes e validação de schema. |
| Notifications/sender | **Atenção** | Há fila `notifications`, índice parcial de delivery queue e sender periódico. | Backlog/IO se notificações antigas não forem limpas ou se retries ficarem presos. | Métricas de backlog e retenção agressiva para status final. |
| Tracking | **Atenção** | Tracking por wishlist e alertas controlados por setting; atividade histórica fica em `wishlist_listing_activity`. | Churn alto por atualizações recorrentes; alertas de preço precisam cooldown. | Retenção e índices por `created_at`/wishlist. |
| Admin commands | **Atenção** | `/admin fipe` já cobre coverage/catalog/resolve/plan/apply/history/status, mas não expõe execução mensal automática nem `fipe_update_runs`. | Operação sem resposta rápida sobre falha do job mensal. | Criar `/admin fipe update_status`. |
| Observabilidade | **Atenção** | `system_logs`, `source_runs`, health/admin, monitor e autopilot existem. | Logs de alto volume e falta de métricas de IO/DB. | Adicionar queries de churn e p95 por tabela/índice no runbook. |
| Migrações | **Atenção** | Migrations cobrem source configs, filas, notifications, FIPE staging e índices operacionais; precisa head único validado por ambiente. | Schema drift em Supabase pode causar erro silencioso. | `alembic heads` + `validate_postgres_schema.py` antes de go-live. |
| Testes | **Atenção** | Há testes de admin FIPE, contratos de scrapers, dual-run e bot. Faltam fixtures reais OLX para imagens e teste de job mensal FIPE. | Regressões em parsing e scheduler passam despercebidas. | Adicionar fixtures e testes P0. |
| Configuração DB | **Atenção** | Sources e leilões são DB/AppKV-driven; `.env` é fallback. | Produção pode divergir do código. | Snapshot read-only de configs no checklist. |
| Leilões | **Estável para piloto / Atenção para público** | Gates e dry-run controlado existem; envio real automático não deve ser liberado. | Risco reputacional se lote não-car ou copy incompleta chegar ao usuário. | Manter piloto; não promover para público sem PR específica. |
| Billing/Premium | **Atenção** | Planos e upgrade existem; ativação ainda manual/admin. | Fricção comercial no lançamento. | P1: webhook Mercado Pago ou aprovação admin 1 clique. |

## 3. Diagnóstico dos três bloqueadores

### 3.1 Bloqueador 1 — thumbnails da OLX

#### Fluxo localizado

1. `build_olx_search_url()` monta URL de busca em autos/carros.
2. `scrape_olx()` tenta HTTP híbrido com `curl_cffi`/cookies; se bloqueado, aquece Playwright e tenta browser.
3. `_extract_next_data_json()` lê `__NEXT_DATA__`.
4. `_extract_items_from_next_data()` percorre JSON e preenche `thumbnail_url` a partir de `node["images"][0]["originalWebp"]` ou `node["images"][0]["original"]`.
5. Se `__NEXT_DATA__` não existe, `_fallback_parse_from_cards()` usa `a[data-testid="adcard-link"]` e apenas `img.src` no container.
6. `_items_to_dicts()` chama `finalize_listings("olx", out)`.
7. Ingestão/matching/notificação usa o campo normalizado `thumbnail_url`; se ele estiver vazio, o alerta chega ao Telegram sem foto.

#### Causa raiz provável

A extração atual é estreita demais para o HTML moderno da OLX:

- o caminho principal ignora outras chaves comuns de imagem no payload (`original_webp`, `thumbnail`, `url`, `imageUrl`, arrays aninhados ou `pictures`);
- o fallback de card só lê `img.src`, mas lazy loading frequentemente coloca a imagem em `srcset`, `data-src`, `data-original`, `data-lazy`, `data-testid`/`picture source[srcset]` ou background style;
- não há enriquecimento por página de detalhe quando o card/search payload vem sem imagem;
- não há parser de `meta[property="og:image"]`, `meta[name="twitter:image"]`, JSON-LD (`image`) ou galeria do detalhe;
- não há validação de URL de imagem antes de persistir/enviar, então valores vazios, relativos, placeholders ou tracking pixels podem passar como ausência.

#### Plano técnico P0

Implementar em uma mudança pequena e testável:

1. Criar helpers em `app/scrapers/olx.py`:
   - `_normalize_olx_image_url(value, base_url) -> str | None`;
   - `_pick_olx_image_from_obj(obj, base_url) -> str | None` percorrendo dict/list e priorizando URL real de CDN/imagem;
   - `_extract_olx_detail_thumbnail(html, detail_url) -> str | None` com prioridade: `og:image`, `twitter:image`, JSON-LD `image`, galeria (`img`, `source[srcset]`, lazy attrs), background-image;
   - `_is_valid_telegram_photo_url(url) -> bool` com `http/https`, sem `data:`, sem SVG/logo conhecido/placeholder, extensão ou host de imagem aceito.
2. No `__NEXT_DATA__`, substituir a leitura fixa por `_pick_olx_image_from_obj(node, url)`.
3. No fallback de cards, coletar `src`, `srcset`, `data-src`, `data-original`, `data-lazy`, `source[srcset]` e background-image.
4. Adicionar enriquecimento controlado para OLX: para os primeiros N itens sem thumbnail, buscar a página de detalhe no mesmo contexto HTTP/browser e aplicar `_extract_olx_detail_thumbnail()`; limitar N por run para não aumentar IO/rede.
5. Validar antes de persistir: se URL inválida, manter `None`; se a página de detalhe possui foto válida, preencher obrigatoriamente.
6. Garantir que o sender só tente `send_photo` quando a URL passar validação leve; caso contrário, enviar mensagem texto e registrar warning com source/listing para auditoria.

#### Testes P0

- Fixture OLX com `__NEXT_DATA__` contendo `images.originalWebp`.
- Fixture OLX com payload sem `images`, mas detalhe com `og:image`.
- Fixture OLX com JSON-LD `image` como string e como lista.
- Fixture OLX com galeria lazy (`data-src`, `srcset`, `picture/source`).
- Fixture OLX com placeholder/logo para garantir rejeição.
- Teste de contrato: anúncio OLX com página contendo foto nunca sai de `scrape_olx()` com `thumbnail_url=None` quando fallback de detalhe está disponível.

#### Critério de aceite

- Em uma amostra real de pelo menos 20 anúncios OLX com imagem na página, 100% devem gerar `thumbnail_url` válido.
- O fallback de detalhe deve ser limitado e logado para evitar aumento inesperado de IO/rede.
- Alertas Telegram da OLX devem usar foto quando `thumbnail_url` válido existir.

### 3.2 Bloqueador 2 — atualização automática da FIPE

#### Fluxo localizado

O repositório já possui staging/serviços para FIPE:

- `FipeSyncRun` registra execuções de importação de catálogo em `fipe_sync_runs`.
- `run_monthly_fipe_sync()` carrega arquivo CSV/JSON, normaliza, faz upsert em `fipe_catalog_entries`, calcula coverage/resolver e aplica plano em `fipe_prices` quando `apply=True`.
- `scripts/run_monthly_fipe_sync.py` executa o pipeline manualmente.
- `/admin fipe` já tem comandos de coverage, catalog, resolver, plan, apply, apply_history e apply_status.

#### Lacuna confirmada

O scheduler principal registra heartbeat, ticks por source, workers, sender, leilões, digest, admin monitor, Facebook healthcheck, autopilot, cleanup, filesystem cleanup e expiração Premium. Não há `add_job()` para `run_monthly_fipe_sync()` nem job mensal de FIPE.

Além disso, a tabela existente é `fipe_sync_runs`, mas o bloqueador pede auditoria de execução em `fipe_update_runs` com última execução, linhas atualizadas, duração e erro. Hoje parte dessas informações existe, mas:

- `FipeSyncRun` não armazena duração explícita;
- `run_monthly_fipe_sync()` só cria `FipeSyncRun` quando `apply=True` e após validar/importar dados;
- falhas antes de `start_fipe_sync_run()` dependem de `system_logs`, não de uma tabela dedicada;
- não há comando admin único que responda “o job mensal automático rodou?”;
- o pipeline depende de `input_path`, então a automação precisa de uma fonte operacional explícita (arquivo dropado, URL/download controlado ou job externo que gere o arquivo).

#### Causa raiz provável

O projeto implementou a capacidade manual/operacional de sincronizar FIPE, mas ainda não conectou essa capacidade a um job automático recorrente com auditoria própria. Portanto, a atualização “mensal” aparentemente não executa porque não existe agendamento mensal no scheduler atual.

#### Plano técnico P0

1. Criar migration `fipe_update_runs` com:
   - `id uuid pk`;
   - `reference_month text not null`;
   - `source text not null default 'external_pipeline'`;
   - `status text not null` (`running|completed|failed|skipped`);
   - `started_at timestamptz not null`;
   - `finished_at timestamptz`;
   - `duration_ms integer`;
   - `rows_seen integer default 0`;
   - `rows_inserted integer default 0`;
   - `rows_updated integer default 0`;
   - `fipe_prices_inserted integer default 0`;
   - `fipe_prices_updated integer default 0`;
   - `input_uri text`;
   - `error text`;
   - `payload jsonb`;
   - índices por `(reference_month, started_at desc)` e `(status, started_at desc)`.
2. Criar model `FipeUpdateRun` e service wrapper `fipe_update_job_service.py`:
   - resolve mês vigente/anterior conforme regra operacional;
   - resolve `input_path`/`input_uri` via settings ou AppKV;
   - cria `fipe_update_runs` antes de qualquer IO;
   - chama `run_monthly_fipe_sync(... apply=True ...)`;
   - copia contadores de catálogo e `price_plan` para a auditoria;
   - grava falha e duração sempre.
3. Registrar job em `app/scheduler/run.py`:
   - cron mensal, por exemplo dia 2 às 04:00 UTC ou horário configurável;
   - `max_instances=1`, `coalesce=True`;
   - kill switch `fipe_monthly_update_enabled` default `False` até configurar input em produção;
   - logar `skipped` quando sem input configurado, para ficar auditável sem quebrar scheduler.
4. Criar comando admin:
   - `/admin fipe update_status` ou `/admin fipe auto_status`;
   - mostra última execução, status, competência, linhas vistas/inseridas/atualizadas, duração, input e erro;
   - inclui recomendação objetiva: configurar input, rodar dry-run, rodar apply, ou investigar erro.
5. Testes:
   - scheduler registra job quando setting habilitado;
   - service grava `completed` com duração e contadores;
   - service grava `failed` mesmo com erro antes/depois do pipeline;
   - comando admin renderiza ausência, sucesso e erro.

#### Critério de aceite

- `/admin fipe update_status` responde em menos de 2s com última execução e erro quando existir.
- Uma execução automática cria linha em `fipe_update_runs` mesmo quando pula por falta de input.
- `fipe_prices` recebe novos registros para a competência alvo quando há catálogo/input válido.
- Falhas não matam o scheduler e ficam visíveis no admin.

### 3.3 Bloqueador 3 — Supabase Disk IO Budget

#### Tabelas com maior churn provável

Sem acesso direto aos dashboards Supabase nesta auditoria, a análise abaixo é inferida a partir do runtime e das queries/caminhos de escrita.

| Tabela | Churn provável | Motivo |
|---|---:|---|
| `scrape_jobs` | Alto | Ticks recorrentes por source criam jobs; workers atualizam status, lock, tentativas, payload e erro. |
| `source_runs` | Alto | Cada execução/skip/falha gera run para observabilidade. |
| `system_logs` | Alto | Scheduler, source execution, monitor, cleanup e erros suprimidos registram eventos. |
| `telemetry_events` | Médio/alto | Eventos operacionais e de source podem crescer com cadência de workers. |
| `notifications` | Alto | Cada match cria notificação; sender atualiza status/retry/sent_at. |
| `car_listings` | Alto | Ingestão faz upsert por source/external_id e reconciliação de atividade/sold. |
| `wishlist_listing_activity` | Alto | Atividade por wishlist/listing/run gera cardinalidade alta. |
| `auction_lots` | Médio | Piloto de leilões com upserts por lote/source. |
| `fipe_catalog_entries` | Mensal alto em rajada | Upsert mensal pode tocar milhares de linhas. |
| `fipe_prices` | Mensal médio | Planejamento/aplicação FIPE por keys cobertas. |

#### Índices e queries relevantes

Pontos positivos já existentes:

- `scrape_jobs` tem índice por fila/status/run_at e unique parcial para job ativo por source/fila.
- `notifications` tem índices de delivery queue e índices parciais para enviados por wishlist/sent_at.
- `source_runs`, `system_logs`, `auction_lots`, `fipe_catalog_entries` e `wishlist_tokens` têm índices básicos para caminhos operacionais.
- Existe script `scripts/cleanup_operational_data.py` com retenção para `system_logs`, `telemetry_events`, `scrape_jobs`, `source_runs`, `notifications` e `wishlist_listing_activity`.

Lacunas prováveis:

- Retenção operacional existe em script, mas precisa estar agendada no ambiente Supabase/produção; no scheduler atual há `cleanup_notifications`, não está evidente um job para `cleanup_operational_data.py` completo.
- `car_listings` não aparece na política de retenção operacional. Para produto, não deve apagar agressivamente listings ativos/rastreados, mas listings antigos/sold/inativos precisam política de arquivamento ou limpeza.
- UPSERTs em `car_listings` e `auction_lots` podem atualizar linhas mesmo quando payload não mudou, gerando WAL/IO desnecessário.
- Logs e runs podem ser escritos para skips/backoff frequentes, aumentando IO durante incidentes de source.
- Índices em tabelas de alta escrita ajudam leitura, mas também aumentam custo de escrita; índices redundantes precisam auditoria real via `pg_stat_user_indexes`.

#### Queries de auditoria recomendadas no Supabase

Executar read-only no SQL editor ou psql:

```sql
-- 1) Churn por tabela desde último reset de stats
select
  schemaname,
  relname,
  n_tup_ins,
  n_tup_upd,
  n_tup_del,
  n_dead_tup,
  seq_scan,
  idx_scan,
  vacuum_count,
  autovacuum_count
from pg_stat_user_tables
order by (n_tup_ins + n_tup_upd + n_tup_del) desc
limit 30;

-- 2) Tamanho de tabelas e índices
select
  relname,
  pg_size_pretty(pg_total_relation_size(relid)) as total,
  pg_size_pretty(pg_relation_size(relid)) as table_only,
  pg_size_pretty(pg_total_relation_size(relid) - pg_relation_size(relid)) as indexes
from pg_catalog.pg_statio_user_tables
order by pg_total_relation_size(relid) desc
limit 30;

-- 3) Índices pouco usados e caros
select
  schemaname,
  relname,
  indexrelname,
  idx_scan,
  pg_size_pretty(pg_relation_size(indexrelid)) as index_size
from pg_stat_user_indexes
order by pg_relation_size(indexrelid) desc, idx_scan asc
limit 50;

-- 4) Backlog de filas/notificações
select queue, status, count(*), min(created_at), max(updated_at)
from scrape_jobs
group by queue, status
order by queue, status;

select status, count(*), min(created_at), max(updated_at)
from notifications
group by status
order by status;

-- 5) Listings por source/atividade
select source, count(*) as total, count(*) filter (where is_sold is true) as sold, min(created_at), max(updated_at)
from car_listings
group by source
order by total desc;
```

#### Plano de mitigação priorizado

P0:

1. Confirmar se `cleanup_operational_data.py --apply` roda diariamente em produção; se não, agendar.
2. Reduzir retenção inicial de alta-churn:
   - `scrape_jobs done`: 24–48h;
   - `scrape_jobs failed`: 7 dias;
   - `system_logs`: 7 dias, exceto erros críticos agregados;
   - `source_runs`: 14–30 dias;
   - `notifications` finalizadas: 30–90 dias conforme necessidade de suporte;
   - `wishlist_listing_activity`: 30–60 dias.
3. Adicionar relatório admin/read-only de IO com contagem de backlog e tabelas grandes.
4. Revisar writes repetidos: só atualizar `car_listings` quando preço/status/thumb/campos relevantes mudarem.

P1:

1. Política para `car_listings`:
   - manter ativos/rastreados/notificados recentes;
   - arquivar ou limpar sold/inativos com mais de 90–180 dias;
   - nunca apagar listings rastreados pelo usuário sem preservar snapshot mínimo.
2. Introduzir agregados diários para métricas e reduzir scans em tabelas brutas.
3. Auditar índices com `pg_stat_user_indexes` antes de remover qualquer índice.

P2:

1. Particionar ou arquivar tabelas de logs/runs se o volume crescer no beta.
2. Limitar payloads grandes em `scrape_jobs.payload`, `source_runs.payload` e `system_logs.payload`; armazenar amostras compactas.
3. Criar job de VACUUM/maintenance recomendado pelo Supabase ou ajustar autovacuum em tabelas de maior churn.

#### Estimativa de impacto

- Limpeza diária e retenção adequada devem reduzir crescimento de storage e IO de scans em tabelas operacionais em dias, com baixo risco.
- Evitar updates idempotentes em `car_listings`/`auction_lots` reduz WAL/IO imediatamente nos ciclos recorrentes.
- Arquivamento de `car_listings` tem maior impacto, mas exige cuidado por dedupe, tracking e histórico de preço.

## 4. Plano técnico consolidado

### P0 técnico — menor intervenção segura

1. **OLX thumbnails**
   - Implementar parser/fallback de imagem no scraper OLX.
   - Adicionar fixtures reais sanitizadas em `tests/fixtures/olx/`.
   - Validar com teste unitário e amostra manual.

2. **FIPE automática auditável**
   - Criar `fipe_update_runs`.
   - Criar service/job wrapper com auditoria antes/depois.
   - Registrar cron mensal no scheduler com kill switch e skip auditável.
   - Adicionar comando `/admin fipe update_status`.

3. **Supabase IO**
   - Confirmar/agendar limpeza operacional completa.
   - Adicionar query/runbook de churn por tabela e backlog.
   - Reduzir updates sem mudança em ingestion onde confirmado por teste.

### Validação local recomendada

```bash
pytest -q tests/test_olx_thumbnail_extraction.py tests/test_admin_fipe_command.py
pytest -q tests/test_scrapers_contract.py tests/test_source_dual_run_report.py
alembic heads
python scripts/validate_postgres_schema.py
python scripts/cleanup_operational_data.py
```

## 5. Roadmap atualizado de lançamento

### P0 (48h)

| Item | Impacto no usuário | Risco | Esforço | Critério de aceite |
|---|---|---|---:|---|
| Corrigir thumbnails OLX | Alertas mais confiáveis e clicáveis; reduz percepção de produto quebrado. | Médio: fallback de detalhe pode aumentar latência/requests. | M | 20/20 anúncios OLX com foto na página saem com URL válida; testes de fixtures passam. |
| Job FIPE mensal auditável | Score/contexto de preço deixa de depender de operação manual invisível. | Médio: input mensal precisa configuração segura. | M | `fipe_update_runs` registra completed/failed/skipped; `/admin fipe update_status` mostra última execução. |
| Agendar/validar cleanup operacional | Reduz alertas Supabase Disk IO Budget e risco de degradação. | Baixo/médio: retenção mal calibrada pode apagar suporte histórico. | P/M | Dry-run revisado; apply diário confirmado; backlog antigo reduzido. |
| Checklist DB/migrations produção | Evita schema drift no lançamento. | Baixo. | P | `alembic heads` head único e `validate_postgres_schema.py` OK/WARNING conhecido. |
| Congelar leilões em piloto | Evita risco reputacional no público. | Baixo. | P | `dry_run=true`, categorias só `car`, source user_eligible revisada. |

### P1 (1 semana)

| Item | Impacto no usuário | Risco | Esforço | Critério de aceite |
|---|---|---|---:|---|
| `/admin metrics` de funil | Operação enxerga usuários, buscas, alertas, conversão e retenção. | Baixo. | M | Comando mostra métricas comerciais/produto dos últimos 7/30 dias. |
| Billing Mercado Pago webhook ou aprovação 1 clique | Remove gargalo manual de Premium. | Médio/alto por pagamento/webhook. | M/G | Pagamento aprovado ativa Premium com auditoria; fallback manual mantido. |
| IO audit report automatizado | Diagnóstico recorrente de churn sem entrar no Supabase. | Baixo. | M | Relatório diário com top tables/backlog/retention. |
| Hardening de sender backlog | Menos alertas atrasados. | Médio. | M | Métrica de oldest queued e retry rate no admin; fila drena em carga beta. |
| Teste de carga mínimo | Confiança para beta. | Médio. | M | Simulação com N usuários/buscas sem backlog crônico. |

### P2 (beta fechado)

| Item | Impacto no usuário | Risco | Esforço | Critério de aceite |
|---|---|---|---:|---|
| Beta founders com cohort controlado | Feedback real com blast radius pequeno. | Médio. | M | 20–50 usuários monitorados; incidentes triados em até 24h. |
| Paridade sources v1/v2 por source crítica | Melhor manutenção sem quebrar cobertura. | Médio. | M/G | Dual-run report sem regressão material antes de flip. |
| Política de retenção de `car_listings` | Reduz IO/storage mantendo tracking. | Alto se apagar dado usado. | M/G | Arquivamento preserva rastreados/notificados recentes; testes de dedupe/tracking passam. |
| Observabilidade de qualidade de alerta | Mede alertas com foto, preço, localização, score e CTR. | Baixo/médio. | M | Dashboard/admin mostra qualidade por source. |

### P3 (lançamento público)

| Item | Impacto no usuário | Risco | Esforço | Critério de aceite |
|---|---|---|---:|---|
| Operação de suporte e incident response | Resposta rápida a falhas de source/pagamento. | Médio. | M | Runbook com responsáveis, SLAs e mensagens padrão. |
| Growth/onboarding público | Conversão e retenção. | Médio. | M | Funil medido de `/start` -> busca criada -> primeiro alerta -> upgrade. |
| Revisão legal/copy de leilões | Reduz risco de interpretação errada sobre lance. | Médio. | P/M | Todo alerta de leilão contém disclosure antes do CTA. |
| Otimização de custos Supabase | Margem e estabilidade. | Médio. | M | IO budget estável por 2 semanas de tráfego beta. |

## 6. Checklist de go-live

### Produto/UX

- [ ] Nome público em copy user-facing é **Garagem Alvo**.
- [ ] `/start`, `/menu`, criar busca, revisar filtros, buscar agora e minhas buscas validados em Telegram real.
- [ ] Alertas de classificados têm título, preço, localização/source, score/contexto conservador e CTA.
- [ ] Alertas OLX com foto na página chegam com foto no Telegram.
- [ ] Digest semanal v2 comunica monitoramento mesmo sem anúncios ativos.
- [ ] `/plan` e `/upgrade` mostram limites/benefícios corretos e estado real de pagamento/ativação.

### Operação

- [ ] Scheduler com heartbeat recente.
- [ ] `scrape_jobs` sem backlog antigo em `queued`/`running`.
- [ ] Workers HTTP/browser drenando filas.
- [ ] Sender sem notification queued antiga.
- [ ] `/admin health`, `/admin health verbose`, `/admin audit`, `/admin sources` sem críticos desconhecidos.
- [ ] `/admin metrics` ou relatório equivalente disponível para beta.
- [ ] Backup/restore mínimo validado.

### FIPE

- [ ] `fipe_update_runs` existe e tem última execução auditável.
- [ ] Job mensal FIPE registrado ou skip auditável por kill switch/config ausente.
- [ ] `/admin fipe update_status` mostra última execução, linhas atualizadas, duração e erro.
- [ ] `fipe_prices` da competência atual/anterior tem cobertura mínima definida.
- [ ] Falha FIPE gera log/admin action, mas não quebra scheduler.

### Banco/Supabase

- [ ] `alembic heads` retorna head único esperado.
- [ ] `scripts/validate_postgres_schema.py` OK ou warnings conhecidos.
- [ ] Retenção operacional diária ativa para logs/jobs/runs/notifications/activity.
- [ ] Auditoria `pg_stat_user_tables` revisada para top churn.
- [ ] Índices de filas/notificações presentes.
- [ ] Política de `car_listings` antigos definida antes de escala pública.

### Sources

- [ ] `source_configs` revisada: enabled/user_eligible/status/sched por source.
- [ ] WebMotors não é tratada como incidente global sem decisão explícita.
- [ ] TurboClass marcada conforme estado experimental real.
- [ ] OLX validada com fixtures e amostra real.
- [ ] Nenhum flip v1/v2 amplo sem dual-run/paridade.

### Leilões

- [ ] Leilões permanecem em piloto controlado.
- [ ] `dry_run=false` automático não habilitado.
- [ ] Somente `car` permitido para usuário no piloto.
- [ ] Todo alerta user-facing de leilão contém `Lance não é preço final.` antes do CTA/link.
- [ ] Admin validou `/admin auctions readiness`, `/admin auctions notify-status` e samples.

### Decisão de lançamento

- [ ] P0 concluído ou mitigado por kill switch/degradação controlada.
- [ ] Plano de suporte do beta definido.
- [ ] Métricas de sucesso e rollback definidas.
- [ ] Dono operacional acompanhando primeiras 48h.
