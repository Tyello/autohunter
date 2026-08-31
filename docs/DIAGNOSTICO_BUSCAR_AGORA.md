# Diagnóstico — "Buscar agora" pendurado/lento (READ-ONLY)

**Status:** Diagnóstico apenas. Nenhum código, schema, config ou serviço foi alterado.
**Data:** 2026-08-30

---

## Veredito

**H1 confirmado, com alta confiança, sem precisar de runtime.** O botão de menu "🔎 Buscar agora"
(callback `MENU:SEARCH`) **não** usa o motor de busca facetada no banco (`app/services/facet_search_service.py`,
implementado na spec `018-buscar-agora-bot-flow`). Ele continua ligado ao fluxo antigo `quick_search_conversation`,
que dispara **scraping ao vivo** (Playwright/HTTP a marketplaces reais) antes de qualquer leitura no banco. Isso é
uma divergência **conhecida e documentada** — não uma regressão nova — registrada em `docs/DESIGN_BUSCAR_AGORA.md`
(2026-08-29, seção 0, item 1) e explicitamente adiada pela própria spec 018 (`REQ-006`, "NÃO modificar
`quick_search_conversation`" — o cutover do menu é uma etapa/PR separada, ainda não feita).

H3 (parser "até" ambiguidade ano/preço) foi investigada e **descartada**: o parser já trata isso corretamente.
H2 (índices/round-trips) não se aplica ao caminho realmente executado hoje, mas foi verificada como correta na
implementação nova.

---

## Cadeia de execução real (com arquivo:linha)

1. Usuário toca "🔎 Buscar agora" no menu → callback `MENU:SEARCH`.
   Botão definido em `app/bot/handlers_core.py:783`.
2. Handler registrado: `CallbackQueryHandler(cb_quick_search_start, pattern=r"^MENU:SEARCH$")`
   — `app/bot/handlers.py:411`.
3. `cb_quick_search_start` (`app/bot/handlers.py:381-388`) só responde com o texto de exemplos e entra no
   estado `QUICK_SEARCH_QUERY` da `quick_search_conversation()` (`app/bot/handlers.py:408`). **Nenhum
   toque no banco aqui ainda** — a demora não é neste passo.
4. Usuário digita a query (ex.: `Honda CR-V até 2004`) → `quick_search_on_text`
   (`app/bot/handlers.py:391-399`) chama `start_manual_search_flow(update, context, query=query, sources=None)`.
5. `start_manual_search_flow` (`app/bot/handlers.py:330-341` até `:378`) envia um ack rápido ("Busca recebida…")
   e agenda `asyncio.create_task(_run_background_search())` — não bloqueia o event loop, mas o usuário fica
   esperando os resultados chegarem depois, sem noção de quanto tempo vai levar.
6. `_run_background_search` (`app/bot/handlers.py:341-378`) chama, via `asyncio.to_thread`,
   `_run_manual_search_sync` (`app/bot/handlers.py:89-140+`).
7. `_run_manual_search_sync` chama `manual_search(db, query=cleaned_query, limit=30, sources=None,
   force_scrape=False)` — `app/bot/handlers.py:97`, implementado em `app/services/search_service.py:25`.
8. **Aqui está o ponto de divergência do design pretendido.** `manual_search`
   (`app/services/search_service.py:25-…`):
   - garante configs de fontes (`ensure_source_configs`, linha 27);
   - **itera todas as fontes registradas** (`list_sources()`, linha 32) e, para cada uma que suporta busca
     manual e não está em backoff, **executa `plugin.scrape()` de verdade** — Playwright para fontes com
     `fetch_mode == "browser"` (linha 50, gate por `settings.enable_playwright`), HTTP para as demais;
   - só depois de raspar é que existe uma leitura no banco (query simples com `ILIKE` em título/localização,
     conforme já documentado em `docs/DESIGN_BUSCAR_AGORA.md`).
   - Cada fonte tem seu próprio custo de rede/anti-bot (PerimeterX etc.) e cooldown/backoff — com múltiplas
     fontes ativas, a espera percebida pelo usuário é a soma (ou quase) do tempo de scraping de cada uma.

Ou seja: o caminho realmente executado quando o usuário usa "Buscar agora" pelo menu é
`menu → conversation → manual_search() → scrape ao vivo por fonte → (só então) SELECT no banco`,
e não `menu → GROUP BY no Postgres → facetas`.

### O motor correto existe, mas está desconectado do menu

- `app/services/facet_search_service.py:177` (`compute_facet_counts`) e `:90` (`build_search_conditions`)
  implementam exatamente o design pretendido: busca só-leitura no Postgres, facetas via `UNION ALL` em
  **1 round-trip**, sem scraping.
- `app/bot/handlers_buscar_agora.py` (`buscar_agora_conversation`, linha 629) usa esse motor corretamente
  (`asyncio.to_thread` + `compute_facet_counts`/`build_search_conditions`, sem scraping em nenhum ponto do
  arquivo — confirmado por leitura completa).
- Esse fluxo novo está registrado em `app/bot/run.py:136`, mas seu **entry point é o comando `/buscar_agora`**
  (`CommandHandler("buscar_agora", cmd_buscar_agora)`, `handlers_buscar_agora.py:633`) — **não** o botão de
  menu nem o comando `/buscar`. Um usuário que digita `/buscar_agora` diretamente teria a experiência rápida
  esperada; um usuário que toca no botão do menu (o caso relatado) cai no fluxo antigo de scraping.
- A spec `specs/018-buscar-agora-bot-flow/spec.md` confirma isso como decisão deliberada: **REQ-006** proíbe
  explicitamente tocar em `quick_search_conversation`/`start_manual_search_flow`/`cmd_buscar` nesta etapa; o
  cutover do menu para o motor novo é uma etapa/PR futura (mencionada como "PR6" no design doc), ainda não
  executada.

---

## H2 — verificado, não é a causa (no caminho ativo)

- `compute_facet_counts`/`build_search_conditions` fazem 1 round-trip via `UNION ALL` para todas as facetas
  — não há N+1.
- Existem índices dedicados às facetas: migração `4b89ead23dfb_car_listings_facet_indexes_price_*` cria
  `idx_car_listings_price`, `idx_car_listings_mileage_km`, `idx_car_listings_status_active`.
- Não encontrei nenhum liveness check (verificação de anúncio "vivo" via rede) implementado em
  `facet_search_service.py` nem em `handlers_buscar_agora.py` — o design de liveness check no top-N descrito
  no brief ainda **não existe no código**; não é causa da lentidão porque nunca chega a rodar, mas é um gap
  em relação ao design pretendido.

## H3 — investigado e descartado

- `parse_wishlist_query_with_implicit_filters` (`app/services/wishlists_service.py:795-809`) chama
  `_extract_year_directives` (linha 317) **antes** de `_extract_price_directives` (linha 261), sobre a
  string original.
- `_extract_year_directives` usa `_YEAR_MAX_PATTERNS` que casam `(?:ate|até)\s+<ano de 4 dígitos 1900-2100>`
  e removem o trecho da query antes que a extração de preço rode. Testei mentalmente contra
  `"Honda CR-V até 2004"`: o padrão `até 2004` é capturado como `year_max=2004` e removido da string; a
  extração de preço, que roda depois sobre a string já limpa, não vê mais o "2004".
- Conclusão: `"CR-V até 2004"` é interpretado corretamente como `ano <= 2004`, não como `preço <= 2004`.
  H3 não contribui para o sintoma relatado.

## H4 — não encontrado

- Não há `await` a fila externa, job do APScheduler, ou lock que bloqueie a resposta ao usuário. O handler
  usa `asyncio.to_thread` (para `_run_manual_search_sync`) e `asyncio.create_task` (fire-and-forget para
  enviar resultados) corretamente do ponto de vista de não travar o event loop do bot — o problema não é
  um await pendurado, é que o trabalho despachado para a thread é, ele mesmo, lento (scraping de rede),
  conforme H1.

---

## Correções mínimas para voltar ao design pretendido (descritas, não aplicadas)

1. **Rewire do entry point do menu.** Trocar o handler do callback `MENU:SEARCH` (`app/bot/handlers.py:411`)
   e do comando `/buscar` (linha ~430, se aplicável) para apontar para o fluxo
   `buscar_agora_conversation()` / `compute_facet_counts` (`app/bot/handlers_buscar_agora.py`) em vez de
   `quick_search_conversation` / `manual_search()`. Isso é exatamente o "PR6 / cutover" já previsto no design
   doc e deliberadamente fora de escopo da spec 018 atual.
2. **Decidir o destino de `manual_search()`/`quick_search_conversation`**: deprecar, ou manter só como
   comando administrativo/explícito de "forçar raspagem agora" (ex.: `sources=[...]`, `force_scrape=True`),
   nunca mais como default do botão de menu.
3. **Implementar o liveness check no top-N** (ainda ausente) antes de considerar a Etapa 2/3 da spec 018
   completa, se esse comportamento for parte do contrato esperado pelo usuário.
4. Nenhuma mudança de índice ou de query é necessária — a implementação nova já está correta nesse quesito.

---

## Suposições que só um log/inspeção em runtime confirmaria

- Se a máquina puder ser inspecionada: `ps aux | grep -i chromium` durante uma busca via menu deve mostrar
  processo(s) Chromium ativos enquanto a busca "trava" — confirmaria H1 empiricamente. Não fiz essa checagem
  (fora do escopo desta leitura de código / sem acesso à máquina neste momento).
- `journalctl -u <unit-do-bot> -n 100` mostraria os logs de `record_run(...)` por fonte (sucesso/erro/backoff)
  durante a janela de espera relatada, e o tempo entre o ack ("Busca recebida") e o primeiro `send_message`
  de resultado — daria o tempo real gasto em scraping por fonte.
- Quantas fontes estão com `is_enabled=True` e fora de backoff no momento do teste do usuário afeta
  diretamente quanto tempo o scraping leva (mais fontes ativas = mais espera).
