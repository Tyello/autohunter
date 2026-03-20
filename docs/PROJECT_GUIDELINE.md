# AutoHunter — Project Guideline

## 1. Visão geral do projeto
O AutoHunter, no código atual, é um sistema de monitoramento contínuo de anúncios automotivos com foco primário em Telegram (bot como interface principal com usuário) e execução recorrente por scheduler. O objetivo prático é transformar interesse do usuário (wishlist) em notificações úteis quando aparecem anúncios compatíveis, com deduplicação, controle de envio e operação contínua (monitoramento, saúde de fonte e alertas administrativos).

Proposta de valor atual (confirmada no runtime):
- reduzir esforço de busca manual;
- reagir rapidamente a novos anúncios relevantes;
- operar em múltiplas fontes com estratégia resiliente (HTTP/browser, filas e backoff);
- manter trilha operacional (source runs, telemetry, admin monitor, digest semanal).

Canal principal: Telegram (comandos de usuário, notificação, administração).

Público provável (inferência): usuários que acompanham mercado de carros usados e querem alertas personalizados sem varrer marketplaces manualmente.

## 2. Definição objetiva do produto
Definição objetiva suportada pelo código:
- plataforma **Telegram-first**;
- monitoramento recorrente de anúncios de veículos;
- multi-source via plugins (`app/sources`);
- matching por wishlist com filtros/regras semânticas;
- dedupe por anúncio e por notificação;
- fila persistente de jobs de scraping (HTTP e browser);
- camada operacional/admin integrada (health, alertas, staleness, controle por source).

Ponto importante: o sistema **não** é apenas “um scraper”. O scraping é um estágio de um pipeline maior de ingestão, matching e entrega.

## 3. Fluxo ponta a ponta do sistema
1. **Entrada do usuário (Telegram)**
   - Usuário cria/gerencia wishlists (`/wishlist`, fluxo assistido em `handlers_wishlist_ui`).
   - Usuário pode fazer busca manual (`/buscar`) que também passa por ingestão.

2. **Scheduler tick por source**
   - O scheduler registra ticks frequentes por plugin de source.
   - O tick valida config DB-driven, due time e backoff.

3. **Enqueue de scrape jobs**
   - Se permitido, o tick enfileira job em `scrape_jobs` (`queue=http` ou `queue=browser`).
   - Há dedupe de job ativo por `(source, queue)` e caps de fila.

4. **Workers de fila**
   - Workers HTTP e browser consomem fila com lock e retry.
   - Worker chama execução de source para todas as wishlists elegíveis.

5. **Scraping + adaptação/normalização**
   - Source plugin escolhe caminho v1/v2/dual (quando configurado).
   - Resultado é adaptado para formato de listing normalizado.

6. **Ingestão**
   - Listings são sanitizados e upsertados em `car_listings`.
   - Deduplicação de listing ocorre por `source + external_id`.

7. **Matching**
   - Matching é avaliado contra wishlists elegíveis (token AND + regras semânticas + filtros).
   - Pipeline atual privilegia matching sobre conjunto do scrape (não só IDs recém-inseridos).

8. **Enfileiramento de notificações**
   - `notifications` recebe linhas `queued` para pares `(wishlist_id, car_listing_id)` ainda não notificados.
   - Há score v2 opcional persistido por notificação.

9. **Envio de notificações**
   - Sender job reclama notificações pendentes, envia no Telegram e marca status.
   - Erros são classificados em transitórios/terminais com retry/backoff de delivery.

10. **Digest**
   - Job semanal monta resumo por usuário com base em `wishlist_listing_activity` + listings ativos.

11. **Observabilidade/admin**
   - Source run, telemetry events, logs e source state são atualizados.
   - Monitor admin avalia erros/bloqueios/staleness e alerta admins no Telegram.

Variações relevantes:
- Busca manual (`/buscar`) roda scraping fora do loop de fila e grava `source_runs` do tipo `manual`.
- Fontes sem monitoramento por wishlist (ex.: feed de manutenção) podem executar sem wishlists.

## 4. Conceitos centrais do domínio
### Wishlist
Consulta persistida por usuário com estado ativo/inativo e filtros opcionais.

### Source
Provedor de anúncios (plugin declarativo com URL builder, scrape fn e defaults operacionais).

### Listing / car listing
Anúncio normalizado em `car_listings` com campos comuns (preço, localização, ano etc.) e `extras/raw_payload`.

### Source execution
Execução operacional de uma source em um ciclo (manual ou scheduler), com coleta de métricas e status.

### Scrape job
Job persistente em `scrape_jobs`, com queue (`http`/`browser`), lock, tentativa e resultado.

### Queue worker
Consumidor de `scrape_jobs` que executa pipeline de source de forma controlada.

### Matching
Regras que conectam listing a wishlist (tokens, semântica e filtros estruturados).

### Notification
Entidade de envio por `(user, wishlist, listing)` com estado (`queued`, `processing`, `sent`, `failed`, `discarded` etc.).

### Sender
Camada de despacho (atualmente Telegram é a principal no runtime).

### Digest
Resumo periódico por usuário (semanal) com visão de listings ativos por wishlist.

### Source config
Config DB-driven por source (`is_enabled`, schedule, cooldown, rate limit, proxy, flags browser, extra).

### Source health
Estado operacional por source (`source_states`) + runs + telemetry.

### Backoff
Controle automático de pausa por bloqueio/erro com progressão e jitter.

### Admin commands
Comandos `/admin ...` para inspeção, ajustes e execução operacional.

### Telemetry / source runs / monitoramento
Eventos e snapshots persistidos (`telemetry_events`, `source_runs`, `system_logs`) para diagnóstico e alertas.

## 5. Superfícies do sistema
- **Telegram bot (principal)**: interação com usuário final (wishlists, busca manual, alertas, plano) e com operação/admin.
- **Scheduler + workers (núcleo operacional)**: recorrência do monitoramento, filas, scraping, ingestão, matching, notificação.
- **FastAPI/web (auxiliar)**: healthchecks, listagem simples e rotas de integração Facebook Agent.
- **Integração FB Agent (confirmada no código)**: fluxo “bring your own browser” para Facebook Marketplace com sessão pareada por código/token.
- **Admin/operação**: comandos via Telegram + monitor job + alertas de erro/staleness.

## 6. Estrutura técnica do projeto
Mapeamento das áreas principais observadas:

- `app/bot/`
  - Handlers Telegram de usuário, admin, debug, wishlist UI, envio de mídia/mensagem.
  - Ponto de entrada do bot: `app/bot/run.py`.

- `app/scheduler/`
  - Bootstrap do APScheduler, ticks por source, workers de fila, sender, digest semanal, monitor admin, heartbeat.

- `app/services/`
  - Núcleo de regras de negócio: source execution, matching, ingestão, notificações, backoff, staleness, limits, telemetry etc.

- `app/sources/`
  - Framework de plugin de source (tipos, registry, builtins, adaptação/normalização v1/v2/dual).

- `app/scrapers/`
  - Implementações concretas por fonte e utilitários de fetch/parsing.
  - Coexistem caminhos “legacy” e “sources v2” (ver seção 10).

- `app/models/`
  - Entidades SQLAlchemy (wishlists, listings, notifications, source configs/states/runs, scrape jobs, sessões FB etc.).

- `app/web/` e `app/main.py`
  - Superfície FastAPI (health e integração Facebook Agent).

- `app/notifications/`
  - Formatação/envio em canais (Telegram ativo; outros canais existem mas uso atual não confirmado).

- `docs/`
  - Histórico técnico do projeto, patches e guias específicos.

- `tests/`
  - Testes de API, contratos e regras críticas (conforme README).

## 7. Fontes e estratégia multi-source
Como sources entram no sistema:
- plugins registrados em `app/sources/builtins.py` via `SourcePlugin`;
- scheduler itera `list_sources()` e agenda tick genérico por plugin.

Configuração/registro:
- defaults vivem no plugin;
- comportamento operacional efetivo é `source_configs` (DB-driven);
- `ensure_source_configs` semeia linhas quando necessário.

Modos de execução:
- `fetch_mode=http` ou `fetch_mode=browser` por plugin;
- flags `force_browser`/`browser_fallback_enabled` na config;
- pipelines v1/v2/dual controlados por flags em `source_configs.extra`.

Cuidados com fontes frágeis (evidência no código):
- tratamento explícito de bloqueio (`FetchBlocked`, 403/429/challenge);
- backoff progressivo por source;
- filas separadas HTTP/browser e caps;
- diagnósticos e captura de auditoria para parse regressions.

## 8. Operação e confiabilidade
Elementos confirmados no código:
- **Health:** heartbeat periódico, endpoint `/admin/health` com snapshot OLX, avaliação de staleness.
- **Backoff:** `source_states.next_allowed_at`, contadores de bloqueio/falha, jitter, retry de bug separado.
- **Retries:** `scrape_jobs` (tentativas/requeue), delivery de notificação (retry com delay progressivo).
- **Telemetry:** `source_runs`, `telemetry_events`, `system_logs`.
- **Alertas:** job `admin_monitor` envia alertas para admins em status críticos e stale global.
- **Digest operacional:** existe digest semanal de usuário e digest de erros admin.
- **Comandos administrativos:** `/admin sources`, `/admin runall`, `/admin health`, `/admin errors`, `/admin deploy`, entre outros.
- **Staleness/monitoramento:** cálculo por `sched_minutes * fator` com mínimo global e estado global do scheduler.

Pontos de deploy/admin:
- Há artefatos para Raspberry Pi em `config/raspberry-pi/`.
- Há serviço de deploy admin no bot; fluxo exato de produção é **não confirmado integralmente** sem ambiente externo.

## 9. Conceitos de qualidade do produto
### Matching
- Combina wishlist com anúncio por tokens efetivos (com remoção de stopwords), extrações auxiliares (ano, combinações alfanuméricas), regras semânticas e filtros.

### Dedupe
- Ingestão deduplica listing por `(source, external_id)`.
- Notificação deduplica por `(wishlist_id, car_listing_id)` e evita reenvio mesmo com reruns.

### Evitar reenvio
- `notifications_queue_service` consulta existentes antes de criar novas.
- Sender marca estados finais e controla retries para não duplicar envio indevido.

### Limite diário / controle de envio
- Há serviço de limites por usuário/plano usado em comandos (`/plan`) e sender (confirmado no README e serviços associados).
- Detalhes completos de política por plano podem mudar; tratar regras de produto como **DB/config-driven** quando aplicável.

### Notificação + digest
- Notificação imediata captura oportunidade nova/relevante.
- Digest semanal fornece visão consolidada de listings ativos por wishlist.

## 10. Runtime oficial vs legado vs histórico
### 10.1 Oficial / aparentemente ativo
- Telegram bot (`app/bot/run.py`, handlers core/admin/wishlist).
- Scheduler APScheduler com ticks, enqueue e workers de `scrape_jobs`.
- Pipeline `source_execution_service` + matching + queue de notificações + sender.
- Source framework em `app/sources/*` com configs DB-driven.
- Operação: `source_runs`, `source_states`, `admin_monitor_job`, digest semanal.

### 10.2 Compatibilidade / legado provável
- Coexistência de caminhos v1/v2/dual de scraping/adaptação.
- Wrappers e compat layers em serviços de ingest/matching para evitar quebra com versões anteriores.
- Comandos “modo antigo” de wishlist coexistindo com UX nova (`handlers_wishlist_ui`).

### 10.3 Suspeito de obsolescência
(sem remoção; apenas suspeita)
- Parte dos docs `docs/PATCH_*.md` parecem histórico de migração.
- Alguns canais de notificação além Telegram existem em código (`email`, `whatsapp`, `webhook`), porém uso no runtime principal atual **não confirmado** nesta inspeção.
- Há múltiplos módulos de scrapers com sobreposição (`app/scrapers/*.py` e `app/scrapers/sources/*`), indicando transição em andamento.

### 10.4 Não remover sem validação
- Qualquer trecho ligado a `dual`, `adapter v2`, `fb_agent`, `admin deploy`, `source audit`, `autopilot`, `cleanup`.
- Scripts/configs de deploy Raspberry Pi e rotas web auxiliares.
- Campos/entidades aparentemente “sobrando” no banco podem ser necessários para observabilidade/compatibilidade.

## 11. Como uma IA deve interpretar este repositório
- Trate **código atual** como fonte de verdade principal.
- Use docs históricas como contexto, não como contrato.
- Não assuma projeto web-first: o produto é Telegram-first com backend operacional.
- Não proponha reescrita total sem necessidade explícita.
- Preserve pipeline: scheduler -> queue -> worker -> ingest -> match -> notify.
- Antes de remover legado, confirme import, chamada, dados e uso operacional.
- Em propostas, separar explicitamente:
  - bug real;
  - risco operacional;
  - melhoria técnica;
  - melhoria de produto.

## 12. Como evoluir o projeto com segurança
- Fazer mudanças incrementais e reversíveis.
- Preservar contratos de entidades e fluxos de fila/notificação.
- Refatorar por bordas (adapter/service), evitando ruptura em handlers/jobs.
- Evitar aumentar acoplamento entre bot, scheduler e scrapers.
- Reforçar testes ao mexer em:
  - source execution;
  - matching;
  - notifications/sender;
  - schema de `scrape_jobs` e `source_states`.
- Tratar fontes frágeis com cuidado operacional (backoff, rate limit, diagnóstico).

## 13. Glossário
- **Wishlist:** intenção de busca persistida do usuário.
- **Source:** origem de anúncios (Mercado Livre, OLX etc.).
- **Listing:** anúncio normalizado no banco.
- **Scrape job:** unidade persistente de execução de scraping.
- **Worker:** processo lógico que consome jobs da fila.
- **Matching:** processo que decide se listing combina com wishlist.
- **Notification:** tentativa/registro de envio para usuário.
- **Sender:** etapa que entrega notificações no canal.
- **Digest:** resumo periódico de resultados ativos.
- **Source config/state:** configuração + estado operacional de uma source.
- **Backoff:** pausa progressiva após bloqueios/erros.

## 14. Resumo executivo final
Hoje, o AutoHunter é uma plataforma Telegram-first de monitoramento contínuo de anúncios automotivos, com operação multi-source orientada por scheduler e filas persistentes. O valor central está em transformar wishlists em alertas acionáveis com dedupe, matching e observabilidade operacional. Os principais riscos ficam em fragilidade de fontes externas (anti-bot, parse drift) e coexistência de caminhos legacy/v2. A forma correta de trabalhar neste repositório é evoluir incrementalmente, validar no código real e preservar o pipeline operacional atual.
