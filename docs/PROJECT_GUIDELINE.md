# Garagem Alvo / AutoHunter — Project Guideline (runtime atual)

## 1) Visão geral do produto
Marca pública: Garagem Alvo.
Nome interno/técnico: AutoHunter.

Garagem Alvo é a marca pública do produto Telegram-first; AutoHunter é o runtime interno, no estado atual do código.

O valor entregue não é “rodar scraper manual”: é manter um ciclo recorrente que transforma wishlists em notificações úteis com dedupe, matching e observabilidade operacional.

## 2) Definição objetiva do que ele é hoje
Definição suportada pelo runtime:

- Produto principal: bot no Telegram para jornada de usuário final.
- Operação principal: scheduler + filas persistentes + workers + serviços de ingestão/matching/notificação.
- Estratégia: múltiplas sources via plugins (`app/sources`).
- Confiabilidade: backoff por source, monitor admin, telemetry/runs/logs, retries e digest.
- API FastAPI: superfície **auxiliar** (healthchecks e integrações como Facebook Agent), não web app principal.

## 3) Fluxo ponta a ponta (numerado)
1. Usuário cria/gerencia wishlist no Telegram.
2. Scheduler roda ticks frequentes por source (plugins).
3. Tick valida config DB-driven (`source_configs`), due time e backoff (`source_states`).
4. Tick enfileira `scrape_jobs` (`http` ou `browser`) com dedupe de job ativo.
5. Workers consomem fila e executam source para wishlists elegíveis.
6. Scraper retorna itens; adaptação/normalização passa por caminhos v1/v2/dual quando configurado.
7. Ingestão faz upsert em `car_listings` com dedupe por `(source, external_id)`.
8. Matching avalia compatibilidade listing x wishlist e cria pendências em `notifications`.
9. Sender processa notificações em fila e envia no Telegram com retry/status.
10. Jobs auxiliares mantêm digest semanal, monitor admin, heartbeat, cleanup e autopilot.

## 4) Conceitos centrais do domínio
- **Wishlist:** intenção persistida de busca do usuário.
- **Source:** origem de anúncios (plugin).
- **Car listing:** anúncio normalizado persistido.
- **Scrape job:** unidade de execução em fila persistente.
- **Worker:** consumidor de fila HTTP/browser.
- **Source config/state:** controle operacional (enabled, schedule, cooldown, browser flags, backoff, status).
- **Matching:** regras para decidir se listing combina com wishlist.
- **Notification:** tentativa de envio por usuário/wishlist/listing.
- **Sender:** etapa de entrega (Telegram no caminho principal).
- **Digest:** resumo periódico (usuário/admin).

## 5) Superfícies do sistema
- **Telegram bot (principal):** interação com usuário final e parte da operação admin.
- **Scheduler + workers (núcleo):** execução recorrente do pipeline.
- **FastAPI (auxiliar):** `/health`, `/db-check`, `/listings`, `/admin/health`, onboarding/agent Facebook.
- **Browser service (auxiliar técnico):** endpoint interno para fetch via Playwright quando usado.

## 6) Estrutura técnica do projeto
- `app/bot/`: comandos e UX Telegram (usuário/admin).
- `app/scheduler/`: ticks, workers de fila, sender, monitor, digest, heartbeat.
- `app/services/`: regras de negócio (source execution, ingestão, matching, queue, backoff, telemetry).
- `app/sources/`: framework de plugins e adaptação v1/v2.
- `app/scrapers/`: implementação concreta de scraping por source.
- `app/models/`: entidades persistidas (`source_configs`, `source_states`, `source_runs`, `scrape_jobs`, `notifications`, etc.).
- `app/main.py` + `app/web/`: superfície FastAPI auxiliar.

## 7) Estratégia multi-source
- Sources são registradas como plugins em `app/sources/builtins.py`.
- O scheduler itera plugins e agenda ticks genéricos.
- Configuração efetiva de runtime é **DB-driven**:
  - `source_configs` define enable/schedule/cooldown/rate/proxy/browser/extra;
  - `source_states` guarda saúde/backoff/últimos estados.
- Defaults dos plugins servem como seed inicial (quando linha ainda não existe no banco).

### Sources implementadas no código atual
Pelo registry atual, existem plugins para:
`mercadolivre`, `olx`, `chavesnamao`, `webmotors`, `gogarage`, `icarros`, `mobiauto`, `kavak`, `facebook_marketplace`, `turboclass`.

**Importante:** quais estão efetivamente ativas em produção depende do banco (`source_configs.is_enabled`) e não pode ser inferido só do código estático.

## 8) Operação e confiabilidade
- Fila persistente de scraping com lock/requeue de jobs travados.
- Separação de workers HTTP e browser.
- Backoff automático por source para bloqueios/erros.
- Logs estruturados (`system_logs`), runs (`source_runs`) e eventos (`telemetry_events`).
- Monitor admin com alertas de erro/stale e digest de logs.
- Heartbeat do scheduler e avaliação de staleness por source/global.
- Retry/control de estado no envio de notificações.
- Cleanup periódico para evitar crescimento infinito de dados operacionais.

## 9) Qualidade do produto (matching, dedupe, envio, limites)
- **Dedupe de listing:** `(source, external_id)` na ingestão.
- **Dedupe de notificação:** evita requeue duplicado para mesmo par wishlist/listing.
- **Matching:** tokens + regras semânticas/filtros; pipeline roda no conjunto raspado da execução.
- **Envio:** sender marca status (`queued/processing/sent/failed/suppressed/discarded`) e aplica retry.
- **Limites e plano:** há serviços e comandos de plano/limite; comportamento exato depende de dados/configuração vigente.

## 10) Resumo executivo final
Hoje o AutoHunter é um sistema **Telegram-first** de monitoramento recorrente, com API auxiliar e runtime orientado a scheduler+filas+workers.

O que é oficial e ativo: pipeline de monitoramento por wishlist, integração multi-source via plugins, dedupe/matching/notificação, e camada operacional (backoff/health/admin monitor).

Há coexistência de caminhos de compatibilidade (v1/v2/dual e UX antiga/nova) que exigem evolução incremental, sem remoções impulsivas.

## 11) Tracking de anúncios por wishlist (estado atual)
- Cada wishlist pode rastrear até 3 anúncios (`wishlist_tracked_listings`, slots 1..3).
- O tracking agora mantém snapshot de preço/status por slot (preço inicial, último preço observado, direção da última mudança, última vez visto).
- A listagem no Telegram (`/wishlist_track_list <n>`) faz refresh leve do snapshot e exibe preço atual/inicial, variação e status.
- Alerta de queda é **opt-in por slot** via `/wishlist_track_alert_on <n> <slot>` e desativação via `/wishlist_track_alert_off <n> <slot>`.
- O alerta considera **somente queda** (não alerta aumento/não alteração), com thresholds default: **R$ 500** ou **1%**.
- Cooldown anti-spam default: **24h** por slot/preço.
- Execução do job `tracking_alerts_job` permanece **default off** via `tracking_price_alerts_enabled=false`.

## 12) Roadmap (próximo passo de UX)
- **Salvar resultado de `/buscar` em wishlist via fluxo guiado**.
- Descrição: no futuro, o `/buscar` poderá oferecer um fluxo guiado para salvar um resultado em uma wishlist específica. Por enquanto, para evitar rastrear na wishlist errada e reduzir confusão, o tracking inline fica restrito às notificações automáticas de wishlist.

---

## Notas de incerteza explícitas
- Sem acesso ao banco de produção neste escopo, não é possível afirmar “quais sources estão ligadas agora”; apenas o que está implementado e como é controlado.
- Fluxos auxiliares (ex.: Facebook Agent/admin deploy) estão presentes no runtime, mas a criticidade operacional de cada um pode variar por ambiente.

- Tracking de wishlist: alerta de queda de preço é opt-in por slot (/wishlist_track_alert_on|off), com cooldown anti-spam e limite de 3 slots preservado.

## 13) UX operacional de comandos e criação de wishlist
- O autocomplete de `/` é intencionalmente enxuto para reduzir ruído operacional: foco em `/start`, `/menu`, `/help` e `/cancelar`.
- Comandos rápidos/legados continuam suportados por handlers para compatibilidade (ex.: `/wishlist_add`, `/buscar`, `/wishlist_track_list`), mesmo quando não aparecem no escopo público.
- Comandos administrativos ficam fora do escopo default e devem ser registrados apenas em escopo admin/chat específico, incluindo também os comandos básicos nesse escopo.
- O Telegram **não faz merge automático** entre escopo default e escopos específicos; por isso, o escopo admin precisa receber a união (básicos + admin).
- Ao criar wishlist, a primeira busca não roda inline no handler: o sistema agenda job inicial em `scrape_jobs` e retorna confirmação imediata no Telegram.
- A queue da primeira busca é resolvida por metadata/policy da source plugin (override opcional em `default_extra.queue`, senão `fetch_mode`), evitando listas hardcoded por nome de source.
- A execução efetiva da primeira varredura acontece depois pelo scheduler/workers do pipeline oficial.


## 14) Métrica notifications_24h_count (wishlist summary)
- O resumo de wishlists agrega `notifications_24h_count` contando registros em `notifications` com `status='sent'` e `sent_at` nas últimas 24h por wishlist.
- Há índice operacional para suportar essa consulta por wishlist/status/sent_at (parcial em PostgreSQL para `status='sent'`; composto de fallback em SQLite para testes rápidos).
- A validação completa da migration de índice deve ser feita na lane PostgreSQL (`pytest -m postgres` com `TEST_DATABASE_URL`).

## 15) Modelo comercial mínimo (Free vs Premium)
- Planos oficiais para UX: **Free** e **Premium**.
- Operação admin pública deve expor apenas `/setplan free` e `/setplan premium`; códigos legados ficam somente para compatibilidade interna de dados históricos.
- **Free**: até 2 buscas ativas, até 1 anúncio rastreado no total, sem alertas automáticos de tracking, acompanhamento manual por `/wishlist_track_list`, referência comercial de 5 notificações/dia por busca.
- **Premium**: até 15 buscas ativas, até 5 anúncios rastreados no total, limite técnico de 3 slots por wishlist preservado, alertas automáticos de queda de preço, suporte a alertas de anúncio inativo quando disponível no pipeline, referência comercial de 200 notificações/dia por busca.
- Preço comunicado no upgrade: lançamento **R$ 5,99/mês** e preço futuro **R$ 9,99/mês**.
- Billing integrado fica para PR separada; enquanto não estiver disponível, `/upgrade` deve apenas preparar o usuário para esse fluxo sem prometer link.
- Fora de escopo desta tranche: gateway de pagamento, dashboard de billing, alteração de frequência de busca por plano.

## 16) Roadmap de evolução incremental (schema e produto)
- Validar registro de `admin_deploy_audits` e criar `/admin deploy history`.
- Evoluir Autopilot v2.
- Implementar filtros avançados usando campos ricos de `car_listings`.
- Usar `fipe_prices` e `market_stats_cohorts` para score e preço justo.
- Manter Facebook Marketplace/Auth como investigação futura.
- Manter Leilões/Oportunidades especiais como futura expansão.

## 17) POC de leilões (fase atual)
- Source experimental **Copart Brasil** com chave `copart_auctions` retorna HTTP 200, porém sem cards públicos estáticos no `vehicleFinder`; status operacional: `needs_js_or_endpoint_study` (reason técnica atual: `requires_js_or_internal_endpoint`).
- Source experimental **VIP Leilões** ativa na POC com chave `vip_auctions`, com HTML público acessível e parser inicial validado no Raspberry.
- Refinamento atual do parser VIP: agrupamento por URL de anúncio (`/evento/anuncio/<slug-id>`) e `external_id` estável (ID numérico final da URL, com fallback para slug).
- Validação operacional recente no Raspberry para VIP: dry-run com 12 lotes únicos e persistência com `fetched=12`, `inserted=12`, `updated=0`, `errors=0`.
- Campos já observados persistidos na POC VIP: `external_id` estável, `title`, `make`, `item_type`, `status`, `year`, `mileage_km`, `url`; `total_bids` permanece `None` quando não há campo explícito.
- Escopo atual restrito a coleta/normalização/persistência em `auction_lots`; sem notificação para usuário final.
- Próxima camada de preview operacional: comandos admin `/admin auctions` (somente leitura), ainda sem exposição para usuário final.
- Execução manual admin-only via Telegram habilitada na POC: `/admin auctions run vip --limit 10 --enrich` (alias `vip` -> `vip_auctions`), sem scheduler nesta ação pontual.
- Fora de escopo nesta tranche: usuário final, matching com wishlists, scheduler de leilões e notificações.
- Parser de detalhe VIP evoluído para tentar capturar também `auction_start_at` e `auction_end_at` por labels e JSON embutido quando disponível.
- `/admin auctions upcoming` passa a ser o comando operacional recomendado para validar próximos encerramentos capturados na POC VIP.
- Se a página VIP não expuser encerramento confiável no HTML atual, o fallback continua explícito no comando admin sem impacto para usuário final.
- Matching com wishlists permanece fora de escopo nesta fase.
- Sem login e sem bypass anti-bot nesta etapa; evolução para browser automation fica para fase posterior, se necessária.


## Leilões (POC admin-only)
- Além da source `vip_auctions`, a POC agora inclui `mega_auctions` (Mega Leilões), iniciando em motos (`/veiculos/motos`).
- A ingestão de Mega alimenta `auction_lots` e roda via `/admin auctions run mega` (alias para `mega_auctions`).
- A POC também inclui `win_auctions` (Win Leilões) como terceira source experimental via HTML público estático (home/listagens).
- A POC inclui também `sodre_auctions` (Sodré Santoro) como source experimental via HTML público estático quando houver cards/lotes disponíveis.
- A POC inclui `superbid_auctions` (Superbid) como source experimental via HTML público estático quando disponível.
- `win_auctions` permanece admin-only nesta fase: sem scheduler, sem notificação para usuário final, sem alteração de wishlist; objetivo é popular `auction_lots` e participar do matching via `/admin auctions match win`.
- A source também pode ser inspecionada por `/admin auctions source mega` e considerada em `/admin auctions match mega`.
- Continua sem scheduler/notificação/usuário final neste estágio; a frente de leilões permanece admin-only.
- Leilões seguem admin-only, sem notificação para usuário final nesta etapa.

## Auction source registry

- Novas fontes de leilão devem ser registradas em `app/sources/auctions/registry.py`.
- Handlers admin, runners e services não devem manter aliases manuais duplicados.
- Status atual:
  - `vip_auctions`: `active`
  - `mega_auctions`: `experimental`
  - `win_auctions`: `experimental`
  - `sodre_auctions`: `experimental`
  - `superbid_auctions`: `experimental`
  - `copart_auctions`: `needs_js_or_endpoint_study`

## Auction quality report

- Antes de qualquer ativação de leilões para usuário final, cada source deve ser avaliada via `/admin auctions quality` (todas) e `/admin auctions quality <source>` (detalhe por fonte).
- Nesta etapa, leilões seguem **admin-only**: sem scheduler dedicado, sem notificação automática e sem inclusão direta na jornada de usuário final.
- Critérios mínimos recomendados para uma source avançar de fase:
  - cobertura alta de URL (idealmente próxima de 100%);
  - cobertura suficiente de `title` e `year` para entendimento básico do item;
  - presença de `current_bid` ou `initial_bid` para decisão econômica;
  - copy de risco obrigatória em qualquer superfície de preview de leilão;
  - idealmente `auction_end_at` quando houver componente de urgência temporal.
- O score de qualidade do comando admin é um semáforo operacional (não substitui validação de produto/compliance).

## 17) Auction opt-in per wishlist
- Leilões são **opt-in por busca** via campo persistente `wishlists.include_auctions`.
- Valor padrão: `false` (incluindo buscas existentes e novas, salvo ativação explícita admin).
- Nesta fase, o opt-in afeta apenas o matching admin de leilões (`/admin auctions match ...`).
- Ainda **não** há notificação automática de leilões para usuário final.
- Antes de notificar usuários finais, será criado fluxo de preview/admin de alerta e copy de risco operacional (edital/taxas/vistoria).

## Auction alert preview

- O comando `/admin auctions preview` é **admin-only** e de **somente leitura**.
- Objetivo: validar copy e qualidade do futuro alerta de leilão antes da notificação para usuário final.
- O preview **não envia mensagem para usuário final**.
- O preview pode exibir lotes sem lance para diagnóstico, porém ordena priorizando matches com lance.
- O preview **não cria Notification**.
- Por padrão usa apenas buscas com `include_auctions=true`.
- Para diagnóstico, `/admin auctions preview wishlist <id> --force` ignora esse opt-in sem persistir alteração.
- Nos comandos admin, `wishlist <id>` também aceita `wishlist <index>` da lista do próprio chat admin.
- Use `/admin auctions wishlists [texto]` para listar índices e UUIDs (com filtro textual opcional por contains/ILIKE).
- Próximo passo (futuro): notificação controlada de leilões para usuários finais.

## Controlled auction notification

- O comando `/admin auctions notify ...` é **admin-only** e **manual** (sem scheduler).
- Comandos com alvo de wishlist aceitam `<wishlist_id|index>`:
  - `/admin auctions wishlist <wishlist_id|index> <enable|disable>`
  - `/admin auctions match wishlist <wishlist_id|index> [--force]`
  - `/admin auctions preview wishlist <wishlist_id|index> [--force]`
  - `/admin auctions notify wishlist <wishlist_id|index> ...`
- Por padrão, alerta real/manual (`notify --confirm`) só envia match com `current_bid` ou `initial_bid`.
- Quando nenhum match tiver lance, o envio padrão é bloqueado com mensagem de elegibilidade.
- `--allow-no-bid` libera uso diagnóstico (dry-run e envio real com `--confirm`) para lotes sem lance.
- Envio real exige `--confirm` explícito.
- Sem `--confirm`, o comando roda em **dry-run**: mostra resumo/prévia e **não envia mensagem real**.
- `--force` isolado **não envia**; para ignorar opt-in (`include_auctions=false`) e enviar real, é obrigatório usar `--force --confirm`.
- Não existe envio automático de leilões nesta fase.
- Há dedupe por lote para a mesma busca, evitando reenvio do mesmo `auction_lot` para a mesma wishlist.
- Recurso experimental/controlado para operação assistida por admin.

## Auction ingestion quality gate

Fontes experimentais de leilão podem capturar HTML ruidoso (páginas institucionais, navegação e resultados de busca). Para evitar poluir `auction_lots`, a ingestão aplica um quality gate central antes do upsert.

Regras práticas:
- candidatos fracos (URL inválida, título institucional, sem sinais mínimos de lote) não devem ser persistidos;
- o summary de ingestão pode incluir `skipped_reasons` para diagnosticar rapidamente o parser por source;
- somente sources com qualidade mínima de dados devem avançar para etapas posteriores (matching/notify).

- Quality gate v2 de leilões: títulos institucionais/genéricos (ex.: home/categoria/footer) e URLs institucionais/PDF/blog devem ser rejeitados antes da persistência.
- Para `win_auctions` e `superbid_auctions`, city/state sozinhos não qualificam lote; é obrigatório ao menos um sinal forte (`year`, `current_bid`, `initial_bid`, `auction_end_at` ou `lot_number`).
- `sodre_auctions` com HTTP 403 deve ser tratado como bloqueio controlado (`forbidden_403`), classificado como `needs_study` operacional sem ruído de falha inesperada.

## Auction source eligibility policy

- Sources com status `active` entram no fluxo padrão voltado ao usuário (match/preview/notify).
- Sources `experimental` só devem ser usadas em diagnóstico admin explícito (ex.: `--all-sources` / `--allow-experimental`).
- Sources `needs_study`/bloqueadas não devem chegar ao usuário final por padrão.
- Estado atual no runtime: apenas `vip_auctions` (alias `vip`) é elegível por padrão para preview e envio.

- Auction sources: `app/sources/auctions/registry.py` define implementação técnica; `source_configs` define disponibilidade operacional (`enabled`, `user_eligible`, `admin_only`, `status`, `source_type=auction`).
- Usuário final continua sem escolher source específica: apenas `include_auctions`; administração controla via comandos `/admin auctions sources` e `/admin auctions source-config ...`.

## User-facing auction opt-in
- O usuário decide **por busca** se aceita oportunidades de leilão (campo persistente `wishlists.include_auctions`).
- Sources/leiloeiras são detalhe operacional de backoffice e continuam sob controle admin (`source_configs` e comandos `/admin auctions ...`).
- `include_auctions=true` **não garante alerta**: habilita elegibilidade da busca para fluxos que respeitam opt-in.
- Alertas dependem de source elegível para usuário, lote com dados mínimos (ex.: lance inicial/atual), dedupe e limites operacionais.
- Toda copy user-facing de leilão deve incluir aviso de risco (edital, taxas, comissão, documentação e vistoria).

## Auction notification pilot job

- Existe um job piloto de notificação de leilões com defaults seguros e **desligado por padrão** (`auction_notifications_enabled=false`).
- O job considera apenas buscas ativas com `include_auctions=true`.
- O envio usa apenas sources de leilão com `enabled=true` e `user_eligible=true`.
- Lotes sem `current_bid` e sem `initial_bid` são ignorados por padrão.
- Dedupe reaproveita a chave `auction:{wishlist_id}:{source}:{lot_external_id}` para evitar repetição.
- Limite diário por usuário reduz ruído operacional (`auction_notifications_max_per_user_per_day`).
- Envio automático só deve ser habilitado após validação operacional (`auction_notifications_enabled=true` e `auction_notifications_dry_run=false`).

## Auction notification scheduler hook

- O scheduler central registra um hook recorrente para notificações de leilão (`auction_notification_scheduler_job`) com frequência configurável via `AUCTION_NOTIFICATIONS_SCHEDULER_MINUTES` (padrão: 60 minutos).
- O comportamento padrão é seguro: nasce desabilitado com `AUCTION_NOTIFICATIONS_ENABLED=false`.
- Envio automático real só ocorre quando **ambos** estiverem ativos: `AUCTION_NOTIFICATIONS_ENABLED=true` e `AUCTION_NOTIFICATIONS_DRY_RUN=false`.
- Com `AUCTION_NOTIFICATIONS_ENABLED=true` e `AUCTION_NOTIFICATIONS_DRY_RUN=true`, o hook roda em simulação (dry-run) para validar volume sem envio.
- O hook respeita os limites operacionais (`max_wishlists`, `max_per_wishlist`, `max_per_user_per_day`), lock de execução única por processo e logs de tick (started/skipped/finished/failed).
- As fontes continuam DB-driven por `source_configs` e filtro de elegibilidade (`user_eligible`).
- O usuário só entra no fluxo quando `include_auctions=true`.
- Dedupe por wishlist/source/lote e limite diário por usuário continuam obrigatórios.
- Lotes sem lance continuam bloqueados por padrão.
