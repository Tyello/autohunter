# AutoHunter — Project Guideline (runtime atual)

## 1) Visão geral do produto
AutoHunter é, no estado atual do código, uma plataforma **Telegram-first** de monitoramento contínuo de anúncios de carros usados.

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
`mercadolivre`, `olx`, `chavesnamao`, `webmotors`, `gogarage`, `icarros`, `mobiauto`, `kavak`, `facebook_marketplace`, `turboclass`, `turboclass_vendidos`.

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

---

## Notas de incerteza explícitas
- Sem acesso ao banco de produção neste escopo, não é possível afirmar “quais sources estão ligadas agora”; apenas o que está implementado e como é controlado.
- Fluxos auxiliares (ex.: Facebook Agent/admin deploy) estão presentes no runtime, mas a criticidade operacional de cada um pode variar por ambiente.

- Tracking de wishlist: alerta de queda de preço é opt-in por slot (/wishlist_track_alert_on|off), com cooldown anti-spam e limite de 3 slots preservado.
