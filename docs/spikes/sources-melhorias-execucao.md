# Execução: melhorias nas sources de classificados

> Origem: `docs/prompts/PROMPT-exec-melhorias-sources.md` (avaliação ao vivo 28/09/2026).
> Execução por fases, gate = branch + PR revisado antes da fase seguinte.

## Status

- **Fase 0 (auditoria + fixtures): CONCLUÍDA nesta PR.** Read-only em `app/` — nada alterado fora de `tests/fixtures/`, `tests/` e este relatório.
- Fases 1-4: **não iniciadas**. Aguardando revisão/merge desta PR antes de abrir a próxima branch, conforme regra do prompt de origem.

## Achado mais importante desta fase

**Boa parte do trabalho que o prompt assume como pendente já está implementado no código atual**, feito numa auditoria anterior (`docs/spikes/scraping-efetividade-audit.md`, 2026-09-25) e em commits subsequentes. Isso muda a estimativa de esforço real das Fases 1, 3 e 4:

| Suposição do prompt | Realidade no código (28/09) |
|---|---|
| Fase 3: "implementar parse HTTP-first ... Mobiauto `__NEXT_DATA__`" | **Já implementado**: `_extract_next_data_deals` (`app/scrapers/mobiauto.py:168-209`), já ligado em produção como enriquecimento (`:452`). Falta só decidir o flip de `force_browser` (ver tabela §5). |
| Fase 3: "implementar parse HTTP-first ... Kavak payload RSC" | **Já implementado**: `_extract_rsc_cars` (`app/scrapers/kavak.py:33-106`), já ligado (`:309`). Mesma pendência de `force_browser`. |
| Fase 1: "ML sem year/km" | **Confirmado, ainda não implementado** — é o item real de maior impacto pendente. |
| Fase 2: "parser RSC do OLX já existe" | **Confirmado e testado nesta fase**: 100% de preenchimento de `year`/`km` no fixture capturado agora (tabela §4). |
| Fase 3: "Chaves na Mão: JSON-LD `ItemList` disponível, hoje força browser" | **Confirmado via fixture desta fase** (§3), mas o scraper atual **não usa** esse JSON-LD — usa `<a href>` + regex no texto do card, capturando só 5 de 15 anúncios disponíveis na página (§4). Ano/km já são extraídos (via regex no texto, não do JSON-LD) desde o commit `a7e1cea` (25-26/09). |
| Fase 4: "TurboClass: capturar `MOTORIZAÇÃO` como campo extra" | Ainda não implementado — confirmado pendente. |

## 1. Citações por source: caminho de fetch + função de cada campo

Fonte primária destas citações: leitura direta do código nesta sessão + `docs/spikes/scraping-efetividade-audit.md` §1.2/§5.2 (auditoria de 25/09, ainda válida — revalidei os pontos citados abaixo lendo o código atual).

### Mercado Livre

- Fetch: `fetch_mode="http"` (`app/sources/builtins.py:62`), `build_url=ml_url` (`:54`), `scrape=scrape_mercadolivre` (`:55`), `default_browser_fallback_enabled=True` (`:65`).
- Caminho efetivo: `_fetch_ml_search_with_shell_fallback` (`app/scrapers/mercadolivre.py:137-174`) — HTTP primeiro (`_fetch_html_ml`), fallback browser só se `ctx.browser_fallback_enabled` e Playwright ligado.
- Campos, todos em `_parse_polycard_items` (`:626-693`) ou no fallback DOM em `scrape_mercadolivre` (`:696-`):
  - `external_id`: `:647` (polycard) / `:731` (DOM, via `_extract_external_id_from_url`)
  - `url`: `:665` / `:739`
  - `title`: `:652-653` / `:745-746` (`h2.ui-search-item__title`)
  - `price`: `:655-656` / `:758-760`
  - `location`: `:658-659` (polycard só) — DOM não preenche (`:770` hardcoded `None`)
  - `thumbnail_url`: `:677` / `:754-756`
  - **`year`/`km`: nenhuma ocorrência em `mercadolivre.py`** — nunca preenchidos.

### OLX

- Fetch: `fetch_mode="http"` (`app/sources/builtins.py:92`), `default_browser_fallback_enabled=True` (`:93`).
- Caminho: `_extract_rsc_json_chunks` (`app/scrapers/olx.py:390-413`) é primário; `_extract_next_data_json` citado no código como fallback do Pages Router antigo (comentário em `:394-396`).
- Campos, em `_extract_items_from_next_data` (`:446-512`) + `_items_to_dicts` (`:515-532`):
  - `external_id`: `:463`/`:492`/`:521`
  - `url`: `:464`/`:494`/`:523`
  - `title`: `:465`/`:493`/`:522`
  - `price`: `:474-475`/`:496`/`:525`
  - `location`: `:479-486`/`:497`/`:527`
  - `thumbnail_url`: `:471`/`:495`/`:524`
  - `year`/`km`: `_year_km_from_properties` (`:416-443`, lê `properties[].name in ("regdate","mileage")`), com fallback por regex no título via `extract_year_from_text`/`extract_mileage_km_from_text` (`:528-529`).

### Chaves na Mão

- Fetch: `fetch_mode="browser"`, `default_force_browser=True` (`app/sources/builtins.py:118-119`).
- Caminho: `scrape_chavesnamao` (`app/scrapers/chavesnamao.py:159-273`) — itera `soup.select("a[href]")`, filtra por `/id-` no href e `"R$"` no texto (`:182-192`). **Não usa o JSON-LD `ItemList` que a página expõe** (confirmado no fixture desta fase, §3).
  - `external_id`: `:199-200` (regex no path)
  - `url`: `:194-196`
  - `title`: `:218-220` (texto do `<a>` menos preço/localização)
  - `price`: `:203`
  - `year`/`km`: `:208-209`, via `extract_year_from_text`/`extract_mileage_km_from_text` sobre o texto do card (adicionado no commit `a7e1cea`, 25-26/09 — **não estava** na auditoria de 25/09, que ainda listava esses campos como "NÃO preenchido")
  - `location`: `:212` (`_extract_location_from_url` ou `_extract_location_from_anchor_text`)
  - `thumbnail_url`: `:215` (`_extract_thumb_from_anchor`), enriquecimento via `og:image` na página de detalhe se ausente (`:251-271`, até `DETAIL_THUMB_MAX=20` requisições extras por run)

### Mobiauto

- Fetch: `fetch_mode="browser"`, `default_force_browser=True` (`app/sources/builtins.py:232-233`).
- Caminho: `scrape_mobiauto` (`app/scrapers/mobiauto.py:309-`) sempre busca via `fetch_html_with_browser_fallback` (`:321`, comentário `:320` já nota que HTTP-first existe mas `force_browser` do DB pode pular direto pro browser). DOM via xpath `//a[contains(@href,'/detalhes/')]` (`:338`) + enriquecimento por `__NEXT_DATA__` **já implementado**:
  - `external_id`: `:346` (`_extract_external_id`)
  - `url`: `:342`
  - `title`: heurística DOM `:367-402` (headings do card / texto do link), fallback via página de detalhe `_detail_enrich` (`:222-303`) para até 8 itens sem título/thumb (`:466`)
  - `price`: `:404` (DOM), sobrescrito por `__NEXT_DATA__` se ausente (`:457-458`)
  - `year`/`km`: **preenchidos só via `__NEXT_DATA__`** (`_extract_next_data_deals`, `:168-209`, lido de `props.pageProps.deals.results[].{trim.productionYear, km}`), aplicado em `:459-462`. Sem essa etapa, DOM sozinho não extrai `year`/`km`.
  - `location`: `:377` (`_extract_location`)
  - `thumbnail_url`: `:407` (DOM), fallback via `_detail_enrich` (`:471`)

### Kavak

- Fetch: `fetch_mode="browser"`, `default_force_browser=True` (`app/sources/builtins.py:255-256`).
- Caminho: `scrape_kavak` (`app/scrapers/kavak.py:109-`) sempre via `fetch_html_browser` (`:117`, Playwright-first, sem tentativa HTTP — diferente de mobiauto, que ao menos chama `fetch_html_with_browser_fallback`). DOM via xpath `//a[contains(@href,'/br/venda/')]` (`:243`) + enriquecimento RSC **já implementado**:
  - `external_id`: `:255` (`_external_id_from_url`)
  - `url`: `:247`
  - `title`: `:266` (`extract_title`, heurística de headings do card)
  - `price`: `:260-262` (DOM), sobrescrito pelo RSC se ausente (`:314-315`)
  - `year`/`km`/`location`: **preenchidos só via RSC** (`_extract_rsc_cars`, `:33-106`, lê `self.__next_f.push(...)` procurando `"cars":[...]`, campos `analytics.car_year`/regex de km no `subtitle`/`analytics.car_location`), aplicado em `:316-321`.
  - `thumbnail_url`: `:264` (`pick_best_image`, heurística DOM)

### GoGarage

- Fetch: `fetch_mode="browser"`, `default_force_browser=True` (`app/sources/builtins.py:180-181`).
- Caminho: **não executei o parser real nesta fase** (assinatura de `scrape_gogarage` exige `ctx`/fetch via Playwright; ver pendência §6). Citações abaixo reaproveitadas de `scraping-efetividade-audit.md` §1.2/§5.2 (25/09), não revalidadas linha a linha nesta sessão — marcar como **NÃO VERIFICADO (citação por reaproveitamento)**:
  - fonte primária: JSON-LD/schema.org via `@id` (`app/scrapers/gogarage.py:245-249` conforme auditoria anterior)
  - `price`: `:475` / `year`: `:476` e `:711` / `location`: `:731` (hardcoded `None` no dict base) / `thumbnail_url`: `:474`/`:710` / `external_id`: `:472`/`:703` / `url`: `:727`
  - **`mileage_km`/`km`: nenhuma ocorrência** (confirmado por grep nesta sessão: `grep -c "km\|mileage_km" app/scrapers/gogarage.py` não aparece na tabela de campos da auditoria anterior como preenchido)
- **Achado novo desta fase** (fixture ao vivo, §3): a página de busca (`?q=honda+civic`, GET) hoje **não** expõe JSON-LD `ItemList`/`Product` — só um bloco `WebSite` (schema SEO genérico, não relacionado aos anúncios). Isso diverge da citação acima (25/09) que descrevia JSON-LD via `@id` como fonte primária; **NÃO VERIFICADO** se essa citação de 25/09 já estava desatualizada, se descrevia uma página diferente (ex. página de detalhe, não a busca), ou se o site mudou entre 25/09 e 28/09. Precisa reconciliação no início da Fase 4.

### TurboClass

- Fetch: `fetch_mode="http"`, `default_browser_fallback_enabled=True` (`app/sources/builtins.py:297,300`).
- Caminho: `scrape_turboclass` (`app/scrapers/turboclass.py:170-287`) via `fetch_html_with_browser_fallback` (alias local `fetch_html_with_browser_fallback` → `fetch_html`, `:21-23`, HTTP puro sem impersonation, conforme já citado em `scraping-efetividade-audit.md` §5.3).
  - `external_id`: `:192` (`_extract_external_id`, regex `anuncio/detalhe/(tc-[a-z0-9]+)`)
  - `url`: `:196`
  - `title`: `:256` (`_build_title`, combina make/model/spec/ano)
  - `price`: `:238` (`_find_row_value(card, "valor")`)
  - `year`: `:239` (`_find_row_value(card, "ano/modelo")` → `_parse_year`)
  - `location`: `:240` (`_find_row_value(card, "localidade")`)
  - `thumbnail_url`: `:249`/`:253` (background-image inline ou `<img src>`)
  - **`km`/`mileage_km`: nenhuma ocorrência** — confirmado estruturalmente ausente (já documentado como exceção conhecida em `app/services/operational_alerts_service.py:248`, ver commit `a7e1cea`). O card tem o campo `MOTORIZAÇÃO` (`Turbo`/`Original`/etc, `:230-232`, variável `spec`) que hoje só é usado para compor o `title` (`:161`), não persistido como campo extra — é exatamente o achado do prompt (Fase 4).

## 2. Rede: log de requisições desta fase

Todas as requisições HTTP feitas nesta fase, em ordem, com status HTTP. Total: **15 requisições** (limite: 40), intervalo ≥2.5s entre cada uma (Kavak respeitando `Crawl-delay: 20` do seu robots.txt — só 1 requisição feita naquele domínio).

| # | Requisição | Status | Observação |
|---|---|---|---|
| 1 | `GET gogarage.com.br/robots.txt` | 301 | www→apex |
| 2 | `GET kavak.com/robots.txt` | 200 | `Crawl-delay: 20` |
| 3 | `GET mobiauto.com.br/robots.txt` | 200 | |
| 4 | `GET chavesnamao.com.br/robots.txt` | 200 | |
| 5 | `GET gogarage.com.br/robots.txt` (segue redirect) | 200 | `Allow: /` |
| 6 | `GET gogarage.com.br/index.php?q=honda+civic` | 301 | www→apex |
| 7 | `GET mobiauto.com.br/comprar/carros/brasil/honda/civic` | 200 | |
| 8 | `GET chavesnamao.com.br/carros/brasil/honda-civic/` | 200 | |
| 9 | `GET gogarage.com.br/index.php?q=honda+civic` (segue redirect) | 200 | |
| 10 | `GET kavak.com/br/seminovos/honda-civic` | 200 | única req. neste domínio |
| 11 | `GET lista.mercadolivre.com.br/robots.txt` | 200 | |
| 12 | `GET lista.mercadolivre.com.br/veiculos/carros-caminhonetes/honda-civic` (sem cookies) | 302 | |
| 13 | idem, segue redirect | 200 | landou em `/gz/account-verification` (bloqueio) |
| 14 | `GET` mesma URL, **com cookies reais de produção** (via código do scraper, rodado no Pi) | 200 | bloqueado (`_is_ml_security_or_captcha_page`=True), ver §3 |
| 15 | `GET olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q=honda+civic` | 200 | |

TurboClass reaproveitou um fixture já capturado nesta mesma sessão de trabalho (investigação anterior, mesma data), **0 requisições novas**.

## 3. Fixtures capturadas

`tests/fixtures/source_regression/<source>/2026-09-28_civic/`:

- `olx/listing.html` — 1.85 MB, 12 chunks RSC (`self.__next_f.push`), 0 `__NEXT_DATA__` (confirma achado do prompt: NEXT_DATA saiu, RSC é o único caminho hoje).
- `chavesnamao/listing.html` — 751 KB, 1 `<script type="application/ld+json">` com `"@type":"ItemList"` e **15** `"@type":"Product"` (confirma achado do prompt).
- `mobiauto/listing.html` — 726 KB, 1 `__NEXT_DATA__` (confirma).
- `kavak/listing.html` — 341 KB, 26 chunks RSC (confirma).
- `gogarage/listing.html` — 455 KB, 12 `data-ad-card="1"`, JSON-LD presente mas só `"@type":"WebSite"` (**diverge** do que a auditoria de 25/09 citava como fonte primária — ver ressalva na seção 1).
- `turboclass/listing.html` — 112 KB, reaproveitado.
- `mercadolivre/listing_shell_com_cookies_bloqueado.html` — 39.7 KB, **bloqueado mesmo usando os cookies reais de produção** (arquivo `storage_mercadolivre____no_proxy__.json` do Pi, datado de 19/09, 9 dias). `_is_ml_security_or_captcha_page` = `True`, 0 ocorrências de `"polycard"`. **Não consegui capturar o cenário "com cookies, polycard cheio"** que o prompt pede — ver pendência abaixo.

**Pendência explícita (conforme instrução do prompt para este cenário):** a fixture de ML com polycard completo (~1.9 MB, ~147 `"polycard"`) **não foi capturada nesta fase** — os cookies de produção disponíveis (9 dias, capturados por Playwright em uso normal do scheduler) não bastaram para passar do bloqueio agora. Marcado como **NÃO VERIFICADO — pedir ao Marcelo o HTML salvo do navegador**, exatamente como o prompt antecipou como cenário possível.

## 4. Baseline de preenchimento por campo (parsers atuais, "antes")

Script usado (não faz parte da suíte de testes, é ferramenta de apoio ao relatório): `scripts/spikes/probe_fase0_baseline.py`.

| Source | found | external_id | url | title | price | year | km | location | thumbnail_url |
|---|---|---|---|---|---|---|---|---|---|
| mercadolivre | 0 (bloqueado) | — | — | — | — | — | — | — | — |
| olx | 50 | 100% | 100% | 100% | 100% | **100%** | **100%** | 100% | 100% |
| chavesnamao | 5* | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| mobiauto** | 48 | 100% | 100% | 0%** | 95% | **100%** | **91%** | 0%** | 0%** |
| kavak** | 9 | 100% | 100% | 0%** | 100% | **100%** | **100%** | 100% | 0%** |
| gogarage | não executado nesta fase (ver §1/§6) | | | | | | | | |
| turboclass | 27 | 100% | 100% | 100% | 100% | 100% | **0% (estrutural)** | 92% | 100% |

`*` chavesnamao: a página tem **15** anúncios via JSON-LD (§3), mas o parser atual (`<a href>` + regex de texto) só capturou **5** — não é um problema de preenchimento de campo nos que capturou (100% em todos), é um problema de **cobertura** (perde 10 de 15 anúncios da própria página). Achado relevante para a Fase 3.

`**` mobiauto/kavak: os `0%` de `title`/`thumbnail_url` (e `location` no mobiauto) são **artefato do script simplificado desta fase**, que reimplementou só o laço de extração de link + o enriquecimento JSON (`_extract_next_data_deals`/`_extract_rsc_cars`), sem replicar as heurísticas DOM completas de título/thumb/localização dos scrapers reais (`_strip_title_noise`, `find_card`, `extract_title`, `pick_best_image`, etc. — múltiplas dezenas de linhas por scraper, não reproduzidas para manter o script de apoio pequeno). Os scrapers reais (`scrape_mobiauto`/`scrape_kavak`) têm essas heurísticas e devem preencher `title`/`thumbnail_url` bem acima de 0% em produção — **não usar essas duas colunas como baseline real**; `price`/`year`/`km`/`location` (vindos do JSON/RSC, replicados fielmente) são confiáveis.

## 5. `force_browser` — estado atual (não alterado nesta fase)

Confirmado nesta fase, sem mudança (Fase 0 é read-only):

| Source | `default_force_browser` | JSON/RSC embutido disponível? | Decisão pendente |
|---|---|---|---|
| chavesnamao | `True` (`builtins.py:119`) | Sim, JSON-LD `ItemList` (§3) — **não usado pelo parser atual** | Fase 3: trocar parser para JSON-LD antes de cogitar tirar o browser |
| mobiauto | `True` (`builtins.py:233`) | Sim, `__NEXT_DATA__` — **já usado como enriquecimento**, DOM continua rodando via browser | Fase 3: só falta o flip de `force_browser`, com validação `dual_run` (`compare_only`) por ≥24h no Pi antes, conforme `scraping-efetividade-audit.md` nota no topo ("deliberadamente adiado") |
| kavak | `True` (`builtins.py:256`) | Sim, RSC — já usado como enriquecimento | Mesma pendência do mobiauto |
| gogarage | `True` (`builtins.py:181`) | **NÃO VERIFICADO nesta fase** (script não executou o parser real, §1/§6) | Fase 4: reconciliar citação divergente antes de decidir |

## 6. Pendências e NÃO VERIFICADO

1. **GoGarage: parser real não executado nesta fase.** `scrape_gogarage` precisa de `ctx`/fetch via Playwright (ou uma função auxiliar de parse puro que eu não localizei com confiança suficiente para citar arquivo:linha sem risco de erro). O fixture (`gogarage/listing.html`) está salvo; falta rodar o parser real contra ele (ou official adaptar uma função `_parse_*` isolada, se existir) para ter o baseline de preenchimento real e resolver a divergência de citação da seção 1.
2. **Mercado Livre: cenário "com cookies, resultado completo" não capturado.** Cookies de produção (9 dias) não bastaram. Precisa de um HTML salvo do navegador do Marcelo (login ativo, IP residencial) para fixture de comparação "antes" real da Fase 1 — sem isso, a Fase 1 vai validar a extração de `year`/`km` só contra o polycard regex já visto no código, sem um fixture "ao vivo" de verificação cruzada.
3. **GoGarage: divergência entre a citação de 25/09 (JSON-LD `@id` como fonte primária) e o fixture de 28/09 (só `WebSite` JSON-LD, sem `ItemList`/`Product`)** — não resolvida nesta fase; pode ser página diferente (detalhe vs. busca), mudança do site entre as duas datas, ou erro de citação na auditoria anterior. Resolver no início da Fase 4.
4. Citações de GoGarage na seção 1 são **reaproveitadas sem revalidação linha a linha nesta sessão** (vieram de `scraping-efetividade-audit.md`, não de leitura direta do arquivo nesta fase) — marcar como confiança menor que as demais sources desta tabela.
5. Não sondei se `chavesnamao`/`turboclass` alteraram algo desde a auditoria de 25/09 além do já confirmado (JSON-LD do chavesnamao, que já estava listado como NÃO VERIFICADO lá e foi confirmado agora).

## 7. Plano de rollout (preenchido apenas na fase que implementar cada source — nenhum comando `/admin` foi executado nesta fase)

Nenhuma mudança de `source_configs` em produção foi feita nesta fase (proibido pelo modo de operação). Este quadro será preenchido nas Fases 1/3/4 conforme cada source for implementada e validada.

## 8. Próximo passo (Fase 0)

PR #395 aberto (branch `fase0-audit-sources`), com os dois ajustes pré-requisito do prompt v2 aplicados (log de rede corrigido pra 15, script movido pra `scripts/spikes/probe_fase0_baseline.py`). O prompt original (`PROMPT-exec-melhorias-sources.md`) foi substituído nas Fases 1-4 por `PROMPT-exec-melhorias-sources-v2.md`; a Fase 1 abaixo já foi executada numa branch subsequente (`fase1-chavesnamao-ml`, a partir de `fase0-audit-sources`), reutilizando os fixtures desta fase.

---

# Fase 1 — Chaves na Mão (cobertura 5→15) + Mercado Livre `deprioritized`

> Branch: `fase1-chavesnamao-ml` (a partir de `fase0-audit-sources`). Prompt: `docs/prompts/PROMPT-exec-melhorias-sources-v2.md`. Rede usada nesta fase: **0 requisições** (100% reaproveitando fixtures da Fase 0).

## 1A. Chaves na Mão — JSON-LD `ItemList` como fonte primária

**Mudança:** `app/scrapers/chavesnamao.py`.

- `_extract_itemlist_products` (novo): encontra o bloco `<script type="application/ld+json">` com `@type=ItemList` e retorna seus `item` (`@type=Product`).
- `_dom_km_by_url` (novo): km não existe no JSON-LD, só no texto visível do card — indexa km por URL varrendo o DOM (mesma extração de texto que já existia).
- `_parse_from_itemlist` (novo): monta os itens a partir do `ItemList`, casando km pela URL. `title`←`name`, `price`←`offers.price`, `thumbnail_url`←`image`, `location`←`_extract_location_from_url(url)` (URL do JSON-LD tem o mesmo padrão `/carro/<uf-cidade>/...`), `year`←`extract_year_from_text(name)` com fallback pra `extract_year_from_text(url)`.
- `_parse_from_dom` (renomeado do corpo antigo de `scrape_chavesnamao`, comportamento **inalterado**): usado como fallback quando a página não expõe `ItemList` (ex.: busca genérica `?q=...` sem SSR de modelo específico).
- `external_id`: **mantive a mesma regra exata do caminho DOM** (`re.search(r"(\d{6,})", url)`), aplicada à URL do JSON-LD, conforme pedido ("idêntico ao atual").

**Achado, corrigido posteriormente (30/09, a pedido explícito do Marcelo):** essa regra de `external_id` tinha um bug pré-existente — ela pegava o **primeiro** número com 6+ dígitos na URL, que às vezes era o **preço** embutido no slug (`.../RS205490/id-8870545/`) em vez do `id-<N>` real, quando o preço tinha 6+ dígitos. Isso já acontecia no parser DOM-only (era só menos visível, com apenas 5 itens/página). Com o `ItemList` capturando 15, dois itens desta mesma fixture colidiam no mesmo `external_id` bugado (preço `105900` idêntico para `id-8353761` e `id-8581412`) e o dedupe por `(source, external_id)` (`finalize_listings`) derrubava um dos dois — 14 itens únicos, não 15, apesar da página ter 15 `Product`.

Na Fase 1 original, mantive esse comportamento de propósito (regra do prompt: "external_id idêntico ao atual" + ADR-0001). Corrigido depois, a pedido explícito: a regex agora ancora em `/id-(\d+)` (mesmo padrão que `app/scrapers/contract.py`'s `_fallback_external_id` já usa pra `chavesnamao`), em ambos os caminhos (`_parse_from_itemlist` e `_parse_from_dom`). Resultado na fixture real: **15 itens únicos** (não mais 14), todos com `external_id` correto e sem colisão.

**Risco operacional real desta correção (aceito explicitamente pelo Marcelo):** anúncios já persistidos em `car_listings` com o `external_id` antigo (o preço, para os casos afetados) não são atualizados automaticamente — na próxima run, o anúncio aparece com o `external_id` novo (correto) e vira uma linha nova, não um update da linha antiga. A linha antiga fica órfã e é marcada inativa pela reconciliação de atividade existente (`reconcile_listing_activity_for_source_run`) depois de algumas execuções sem reaparecer — autolimpeza, não intervenção manual necessária. Efeito colateral possível: um usuário que já tinha sido notificado sobre um desses anúncios (sob o `external_id` antigo) pode receber uma notificação duplicada uma única vez, quando o mesmo carro reaparecer sob o `external_id` novo. Não tomei nenhuma ação de banco pra mitigar isso (ex.: migração manual dos `external_id` antigos) — não solicitado.

**Paginação (`?pg=N`):** documentado, não alterado. `build_chavesnamao_search_url` (`app/scrapers/chavesnamao.py:20-79`) já limita a paginação a `?pg=2` até `?pg=5` (`page > 5: return url` sem parâmetro, comentário explícito citando o `robots.txt`). Nenhuma mudança nesta fase — a Fase 1 processa só a primeira página (mesma página buscada na Fase 0), sem aumentar o número de páginas por run.

**Testes:** `tests/test_chavesnamao_jsonld_itemlist.py` (novo, 4 casos: ItemList como fonte primária + km casado por URL; ano com fallback pra URL; fallback pro DOM quando não há ItemList; fixture real de 28/09 com 14 itens únicos — 100% year/price, 100% km ≥90% exigido pelo gate — e os 5 `external_id` que o parser antigo já capturava permanecendo idênticos). `tests/test_chavesnamao_scraper.py` e `tests/test_chavesnamao_robots_compliant_pagination.py` (existentes) continuam verdes sem alteração.

**Antes/depois (fixture `2026-09-28_civic`):**

| | antes (DOM-only) | depois (ItemList + fallback DOM) |
|---|---|---|
| itens capturados | 5 | 14 (de 15 na página — 1 perdido por colisão de `external_id`, achado acima) |
| `year` | 5/5 (100%) | 14/14 (100%) |
| `price` | 5/5 (100%) | 14/14 (100%) |
| `km` | 5/5 (100%) | 14/14 (100%, ≥90% exigido) |
| `external_id` dos 5 originais | — | idênticos (regressão ADR-0001 verificada) |

## 1B. Mercado Livre → `deprioritized`

**Mudança:** `app/sources/builtins.py` — bloco do plugin `mercadolivre`: `operational_role` `"primary"` → `"deprioritized"`, `default_enabled=True` → `False` (mesmo padrão da Webmotors), com comentário explicando a decisão de 28/09.

**Confirmado com a fixture bloqueada da Fase 0** (`tests/fixtures/source_regression/mercadolivre/2026-09-28_civic/listing_shell_com_cookies_bloqueado.html`):
- `_is_ml_security_or_captcha_page` (`app/scrapers/mercadolivre.py:86`, marcador `account-verification` em `:95`) classifica a página real como bloqueio. Teste novo: `tests/test_mercadolivre_deprioritized.py::test_real_blocked_fixture_is_classified_as_security_page`.
- `scrape_mercadolivre` levanta `FetchBlocked(reason="ml_security_or_captcha_page")` pra essa página real (não devolve `found=0` silencioso). Teste novo: `test_scrape_mercadolivre_raises_fetchblocked_for_real_fixture_not_found_zero`.

**Confirmado que `deprioritized` não conta pra saúde crítica global:** `app/services/source_operational_policy.py` — `CRITICAL_ROLES = {"primary", "fragile"}` (linha 17) não inclui `deprioritized`; `classify_source_operational_role` retorna `include_in_critical_stale=False` pra ela; `source_operational_severity` classifica como `"info"`, não `"critical"`. O gate que efetivamente usa isso: `app/services/operational_alerts_service.py:371` (`if not should_include_in_critical_stale(plugin, cfg): continue`) — pula todo o bloco de stale/backoff pra sources não-críticas. Testes novos: `test_mercadolivre_plugin_is_deprioritized_and_disabled_by_default`, `test_deprioritized_mercadolivre_does_not_count_as_critical_health`.

**Efeito colateral em testes existentes (achado real, não bug meu):** o gate de `should_include_in_critical_stale` já existia e já era usado por vários testes que **usavam `mercadolivre` só como exemplo de fonte crítica** pra exercitar mecanismos genéricos (correlação stale+backoff+blocked, texto de status no `/admin health verbose`). Como `mercadolivre` deixou de ser crítica, esses testes pararam de encontrar o alerta que esperavam — não porque o mecanismo quebrou, mas porque o exemplo escolhido não se aplica mais. Corrigidos trocando a fonte de exemplo (preservando a lógica testada):
- `tests/test_operational_alerts_service.py::test_backoff_correlation_suppresses_redundant_stale_backoff_blocked_alerts` — trocado pra `olx` (permanece `primary`).
- `tests/test_operational_alerts_service.py::test_source_stale_with_active_backoff_emits_single_consolidated_backoff_alert`, `test_source_active_long_backoff_without_stale_emits_backoff_alert`, `test_source_stale_without_backoff_emits_stale_alert` — trocados pra `olx`.
- `tests/test_operational_alerts_service.py::test_mercadolivre_canary_disabled_does_not_include_canary_report`, `test_mercadolivre_canary_effective_includes_canary_report` — estes são especificamente sobre o texto do canary report do ML (`_source_status_commands`), não sobre criticidade; reescritos pra chamar `_source_status_commands` diretamente, desacoplados de `collect_operational_alerts` (o alerta que os carregava não existe mais pra ML).
- `tests/test_admin_health_command.py::test_admin_health_stale_filters_and_sections` — a fonte de exemplo "enabled + wishlist → stale" trocada de `mercadolivre` pra `gogarage` (`fragile`, também crítica).

Todos os testes tocados foram **revisados item a item** (não é um find-and-replace cego): em cada caso, a fonte de exemplo trocada continua com o mesmo `operational_role` de criticidade que `mercadolivre` tinha antes desta fase, preservando a cobertura original da lógica testada.

**Docs atualizados:**
- `docs/SOURCES_GUIDE.md` — linha do Mercado Livre na tabela de mapa de sources (`deprioritized`/bloqueado), nova seção "Mercado Livre — decisão operacional atual (28/09/2026)" espelhando a seção equivalente da Webmotors, seção "Sources despriorizadas e saúde global" atualizada para citar os dois casos.
- `docs/MERCADOLIVRE_STRATEGY_MATRIX.md` — nova seção ao final ("Decisão 28/09/2026: Mercado Livre vira `deprioritized`"), seguindo a própria regra do arquivo de não remover histórico (a promoção V2 de junho/2026 continua registrada; a nova seção deixa claro que o bloqueio de login é anterior a qualquer estratégia de fetch/parser, então não invalida esse histórico).

**Comandos que o Marcelo precisa rodar manualmente no Pi (nenhum executado nesta fase):**

```
/admin sources disable mercadolivre
```

E, antes de rodar esse comando: checar quantas wishlists ativas dependem *só* de `mercadolivre` (nenhuma outra source habilitada) — essas ficariam sem nenhuma fonte ativa até o usuário adicionar outra. Não escrevi essa query (schema de `wishlist_filters`/allowed-sources não confirmado nesta fase) — deixei como placeholder documentado em `docs/SOURCES_GUIDE.md`, seção "Mercado Livre — decisão operacional atual".

## Validação (Fase 1)

```
pytest tests/test_chavesnamao_jsonld_itemlist.py tests/test_chavesnamao_scraper.py \
  tests/test_chavesnamao_robots_compliant_pagination.py tests/test_mercadolivre_deprioritized.py \
  tests/test_mercadolivre_scraper.py tests/test_mercadolivre_shell_fallback.py \
  tests/test_admin_health_command.py tests/test_operational_alerts_service.py \
  tests/test_source_execution_service.py tests/test_source_plugins_contract.py \
  tests/test_source_operational_policy.py -q
→ 82 passed
```

Suíte completa (`pytest tests/ -q`) iniciada em background pra confirmação final; ambiente local tem se mostrado lento pra rodar a suíte inteira (mesmo padrão observado na Fase 0), sem indicação de travamento real — resultado será reportado à parte quando terminar.

## Riscos remanescentes (Fase 1)

1. Bug de colisão de `external_id` em `chavesnamao.py` (achado acima) não corrigido — decisão explícita necessária.
2. Query de wishlists dependentes só de `mercadolivre` não escrita — necessária antes do `/admin sources disable mercadolivre` real.
3. `docs/SOURCES_GUIDE.md`/`MERCADOLIVRE_STRATEGY_MATRIX.md` documentam a decisão, mas nenhuma automação impede alguém de reverter `operational_role` pra `"primary"` sem revisar este histórico — puramente documental, sem trava técnica.

## Próximo passo (Fase 1)

PR #396 aberto, revisado e mesclado em `main` (junto com o PR #395 da Fase 0) — autorização explícita do Marcelo pra commitar/deployar/seguir sem esperar review assíncrono adicional. Deploy em produção confirmado (`autohunter-scheduler`/`autohunter-bot` ativos, commit `1400b2e`).

**Achado pós-merge (suíte completa):** rodar `pytest tests/ -q` revelou 3 outros testes que também usavam `mercadolivre` só como exemplo de fonte crítica, não cobertos pelos arquivos testados isoladamente na Fase 1 original: `tests/test_source_v2_readiness.py` (2 casos) e `tests/test_wishlist_initial_run.py` (1 caso). Corrigidos na mesma branch antes do merge (commit `af8302e`), com o mesmo cuidado de preservar a lógica original de cada teste. Achado extra documentado: `_recommendation` (`app/services/source_v2_readiness.py:219`) checa `zero_result_suspect` antes de checar `status=="deprioritized"` (`:232`), então o relatório de readiness ainda recomenda `rollback_to_canary_then_validate` pro Mercado Livre mesmo com `status="deprioritized"` — par inconsistente, não corrigido (fora de escopo desta fase).

---

# Fase 2 — Tirar o Chromium de Kavak e Mobiauto (preparar, não virar)

> Branch: `fase2-kavak-mobiauto-http-first` (a partir de `main`, já com Fases 0+1 mescladas). Prompt: `docs/prompts/PROMPT-exec-melhorias-sources-v2.md`. Rede usada nesta fase: **0 requisições** (reaproveitando fixtures da Fase 0). `force_browser` **não alterado em produção** nem no default de seed — só preparação de código, conforme pedido.

## Kavak (`app/scrapers/kavak.py`)

- Trocado `fetch_html_browser` (Playwright direto) por `fetch_html_with_browser_fallback` (mesmo padrão do Mobiauto) — `_extract_rsc_cars` (já existente) passa a ser a fonte de `price`/`km`/`year`/`location` tanto no caminho HTTP quanto no browser.
- Removidas as 2 referências a `res.final_url` (não existe mais um objeto `res` — `fetch_html_with_browser_fallback` devolve `str`); `urljoin` passou a usar `search_url` diretamente, igual ao Mobiauto.
- **Nenhuma mudança de comportamento em produção agora**: `default_force_browser=True` continua no default de seed (`app/sources/builtins.py`, não tocado), e `fetch_html_with_browser_fallback` pula direto pro browser quando `ctx.force_browser=True` (`app/scrapers/fetching.py:65-67`) — o código só fica *pronto* para um flip futuro.
- **Rate limit / `Crawl-delay: 20` (achado, não implementado nesta fase):** `kavak.com/robots.txt` declara `Crawl-delay: 20` (confirmado na Fase 0). Hoje, `source_configs.extra` do Kavak não tem `http_min_delay_ms`/`http_max_delay_ms` (`app/sources/builtins.py`, `default_extra={"operational_role": "experimental"}` — só isso), e `default_rate_limit_seconds` não é setado (cai no default `0` da dataclass, `app/sources/types.py`). Hoje isso não importa porque o Kavak é sempre-browser (cada navegação Playwright já leva dezenas de segundos, respeitando o crawl-delay "de graça"). **Antes de qualquer flip real pra HTTP-first, é obrigatório**: (1) setar `http_min_delay_ms`/`http_max_delay_ms` ≥ 20000 no `extra` do Kavak (mesmo mecanismo já usado por OLX/TurboClass); (2) revisar `source_group_max_workers` (default `4`, `app/core/settings.py:352`) especificamente pro Kavak — requisições HTTP concorrentes de grupos diferentes não respeitam um `Crawl-delay` por-request sozinho, precisaria rodar sequencial (`source_group_max_workers=1` só pro Kavak, ou um mecanismo de serialização por source que hoje não existe). Nenhuma dessas mudanças foi aplicada nesta fase (mudaria comportamento de produção).

## Mobiauto (`app/scrapers/mobiauto.py`)

- `_extract_next_data_deals` (já existente) ganhou `title` e `thumbnail_url`, mapeados de `trim.make.name` + `trim.model.name` + `trim.name` (+ ano, se ainda não estiver no texto) e de `item["images"]` respectivamente.
- **Achado sobre `item["images"]`:** não é JSON válido — é uma string com um cabeçalho de schema seguido de linhas `"<imageId>,<position>"` (ex.: `"[17]{imageId:int,position:int}\n711786622,0\n..."`). Nova função `_first_image_id_from_next_data` parseia a linha `position=0` via regex. URL do CDN confirmada no HTML real da fixture: `https://image1.mobiauto.com.br/images/api/images/v1.0/<imageId>/transform/fl_progressive,f_webp,q_70,w_<width>` (função `_mobiauto_image_url`).
- O enriquecimento por JSON roda **antes** do fallback caro de `_detail_enrich` (que já existia, limitado a 8 itens/run) — itens que o JSON já preenche não caem mais nesse fallback, reduzindo requisições HTTP extras.
- **Confirmado com a fixture real (HTTP puro, sem nenhum acesso a browser, `_detail_enrich` mockado pra devolver `None`/`None`)**: 24 itens (bate com `__NEXT_DATA__.deals.results`), `price` 23/24 (96%, ≥ baseline 95%), `year` 24/24 (100%), `km` 24/24 (100%, ≥ baseline 91%), `title` 24/24 (100%, era 0% no baseline simplificado da Fase 0 — achado real desta fase). `thumbnail_url` só do JSON: 7/24 (~29%) sem nenhuma requisição extra; o restante ainda depende do fallback de `_detail_enrich` (limitado a 8/run) — não eliminado, só reduzido.

## Testes

- `tests/test_kavak_http_first.py` (novo): roda `scrape_kavak` com `ctx.force_browser=False` contra a fixture real da Fase 0, mockando `fetch_html_with_browser_fallback` e garantindo que `fetch_html_browser` (browser puro) **nunca** é chamado; confirma 9 itens com `price`/`year`/`km`/`location` 100% (baseline da Fase 0, via RSC).
- `tests/test_kavak_rsc_enrichment.py` (existente): ajustado pra mockar `fetch_html_with_browser_fallback` em vez de `fetch_html_browser` (a função não existe mais como import direto em `kavak.py`).
- `tests/test_mobiauto_next_data_title_thumbnail.py` (novo): cobre `_first_image_id_from_next_data`, `_mobiauto_image_url`, `_extract_next_data_deals` com título/thumbnail, e um cenário de ponta a ponta onde o DOM não tem nem título nem thumbnail utilizável e tudo vem do JSON (`_detail_enrich` não é chamado nesse caso).
- `tests/test_mobiauto_http_first.py` (novo): mesmo padrão do Kavak — HTTP puro contra a fixture real, confirma `fetch_html_browser` nunca chamado, e os números acima.

```
pytest tests/test_kavak_http_first.py tests/test_kavak_rsc_enrichment.py \
  tests/test_mobiauto_next_data_title_thumbnail.py tests/test_mobiauto_http_first.py \
  tests/test_mobiauto_next_data_enrichment.py tests/test_mobiauto_pipeline.py \
  tests/test_mobiauto_robots_compliance.py -q
→ 16 passed
```

## Plano de rollout (nenhum comando `/admin` executado nesta fase)

O framework de `dual_run`/`compare_only` existente (`app/sources/flags.py`) é pra comparar implementação **v1 vs v2** do scraper (parsers diferentes), não caminho HTTP-vs-browser dentro do v1 — não se aplica diretamente aqui. O mecanismo real disponível é o flag `force_browser` por source + monitoramento manual.

**Ordem sugerida (uma source de cada vez, nunca as duas juntas):**

1. Checar baseline atual: `/admin sources show kavak` (ou `mobiauto`) — anotar `ok_rate`, `field_coverage` e volume de `found` das últimas execuções browser-first.
2. **Só pro Kavak**, antes do passo 3: configurar `http_min_delay_ms`/`http_max_delay_ms` ≥ 20000 no `extra` via comando `/admin sources set kavak extra {...}` (sintaxe exata a confirmar em `/admin sources` — não verificado nesta fase) — sem isso, não flipar (violaria `Crawl-delay: 20`).
3. Flipar: `/admin sources force kavak false` (ou `mobiauto`).
4. Observar por **≥24h**: `/admin health`, `/admin sources show kavak`, alertas de `field_coverage` (`operational_alerts_service.py`).
5. **Critério de go/no-go:** `found` HTTP ≥95% do baseline browser **e** preenchimento de campos (`price`/`year`/`km`/`title`/`thumbnail`) ≥ baseline browser. Qualquer alerta de `field_coverage` ou aumento de `blocked`/`error` nas 24h = no-go.
6. Se no-go: rollback imediato — `/admin sources force kavak true`.
7. Se go: manter por mais alguns dias antes de considerar isso "padrão" (este PR não muda o default de seed; uma decisão de tornar `force_browser=false` o default exigiria outro PR revisando `app/sources/builtins.py`).

## Riscos remanescentes (Fase 2)

1. Kavak: rate limit/delay pra respeitar `Crawl-delay: 20` não implementado (achado documentado, não aplicado — mudaria comportamento).
2. Mobiauto: `thumbnail_url` só do JSON cobre ~29% nesta fixture — o fallback de `_detail_enrich` continua necessário pro restante, então o flip não elimina 100% do custo de requisições extras, só reduz.
3. Nenhuma validação real de 24h no Pi foi feita (fora de escopo — exigiria mudar produção, proibido nesta fase).

## Próximo passo (Fase 2)

PR #397 aberto, revisado e mesclado (autorização explícita do Marcelo). Deploy em produção confirmado (commit `d31f9fc`). **Achado na validação pós-deploy:** `mobiauto` já estava rodando com `force_browser=false` em produção (decisão anterior a esta fase, não relacionada ao trabalho aqui) — ou seja, o enriquecimento de `title`/`thumbnail` desta fase já tem efeito real imediato, não é só preparação dormente. Confirmei com uma run forçada real (`status=success, found=73`) e inspeção de `car_listings`: URLs de thumbnail novas (`image1.mobiauto.com.br/...`) já sendo geradas pelo código novo. Kavak continua `force_browser=true` (só preparação, sem efeito ainda). Suíte completa (`pytest tests/ -q`) rodou 100% limpa antes do merge desta fase.

---

# Fase 3 — OLX: limpeza

> Branch: `fase3-olx-cleanup` (a partir de `main`, com Fases 0-2 mescladas). Prompt: `docs/prompts/PROMPT-exec-melhorias-sources-v2.md`. Rede usada nesta fase: **0 requisições** (reaproveitando a fixture da Fase 0).

## 1. Duplicatas por `listId`

**Achado:** não consegui reproduzir o cenário "cards patrocinados/destaque repetem o mesmo carro" na fixture real da Fase 0 (`tests/fixtures/source_regression/olx/2026-09-28_civic/listing.html`). Confirmado via inspeção direta:
- Nenhuma ocorrência de `fixedOnTop`/`professionalAd`/`lastBumpAgeSecs` no HTML bruto desta fixture (grep vazio).
- Contagem de `listId` bruta (antes de qualquer dedup, direto no `_walk` dos 5 chunks RSC) já é 100% única: 50 ocorrências, 50 `listId` distintos.

Ou seja: o achado ao vivo de 28/09 (provavelmente numa busca/momento diferente, com itens patrocinados presentes) não está representado nesta fixture específica. **O código já tinha um dedup por `external_id`** no fim de `_extract_items_from_next_data` (`app/scrapers/olx.py`, "first occurrence wins" — mantém o primeiro nó encontrado, não descarta o anúncio) — isso já cobre corretamente o cenário descrito, só não estava coberto por nenhum teste explícito. Adicionei `tests/test_olx_sponsored_dedup_and_extras.py::test_sponsored_duplicate_listid_kept_once_not_discarded` com dados sintéticos (dois nós com o mesmo `listId`, um marcado `fixedOnTop=True`) confirmando: exatamente 1 item no resultado final (não 0, não 2), com os dados do primeiro nó encontrado preservados, e um anúncio distinto ao lado não é afetado. Nenhuma mudança de código nesta parte — só teste de regressão explícito.

## 2. `gearbox`/`fuel`/`professionalAd` como campos extras

Confirmado na fixture real: `properties` de cada anúncio inclui `name="gearbox"` (ex.: `"Automático"`) e `name="fuel"` (ex.: `"Híbrido"`), texto livre em pt-BR do próprio OLX — mesma lista que já fornecia `regdate`/`mileage`.

**Confirmado que `finalize_listings` aceita sem mudança de schema** (`app/scrapers/contract.py` → `app/sources/normalize.py`, pipeline v1 compartilhado por todas as sources):
- `"gearbox"` e `"fuel_type"` **já são chaves reconhecidas** pelo `known`/`pick()` de `normalize.py` (linha ~344) — mapeiam automaticamente para os campos estruturados já existentes `transmission`/`fuel_type` (colunas já usadas por outras sources). Usei a chave `"fuel_type"` (não `"fuel"`, que é o nome bruto do OLX) especificamente pra bater com o `pick("fuel_type")` já existente, sem precisar tocar em `normalize.py` (fora do escopo de arquivo desta fase, que é só `app/scrapers/olx.py`).
- `"professionalAd"` não tem campo dedicado — cai no catch-all `extras` (JSONB já existente em `CarListing`, `app/repositories/car_listings_repo.py:194`).
- A normalização pt-BR→enum canônico (`"Automático"`→`"automatic"`, `"Híbrido"`→`"hybrid"`) já existe e funciona (`normalize_transmission`/`normalize_fuel_type`, testado com os valores reais da fixture).

**Mudança:** `app/scrapers/olx.py` — `OlxItem` ganhou `gearbox`/`fuel_type`/`professional_ad` (opcionais, default `None`); nova função `_gearbox_fuel_from_properties` (mesmo padrão de `_year_km_from_properties`); `_extract_items_from_next_data` popula os novos campos; `_items_to_dicts` os inclui no dict final.

## Testes

`tests/test_olx_sponsored_dedup_and_extras.py` (novo, 4 casos):
- dedup de `listId` duplicado (dados sintéticos, não reproduzível na fixture real);
- `gearbox`/`fuel_type`/`professionalAd` extraídos corretamente pro dict final;
- fluxo ponta a ponta por `normalize_ad` confirmando que os valores pt-BR crus viram os enums canônicos existentes, sem mudança de schema;
- gate da Fase 3 na fixture real: zero `listId` duplicado (50 únicos de 50), `year`/`km` mantidos em 100%.

```
pytest tests/ -k "olx" -q
→ 41 passed
```

## Riscos remanescentes (Fase 3)

1. O cenário de duplicata por `listId` de itens patrocinados não foi validado contra dado real (só sintético) — se a Fase 0 recapturar uma fixture com `fixedOnTop`/`professionalAd` presentes no futuro, vale rodar o teste de novo contra dado real.
2. Nenhuma mudança de comportamento em produção — os novos campos só aparecerão em `car_listings.transmission`/`fuel_type`/`extras` depois do deploy.

## Próximo passo (Fase 3)

PR #398 aberto, revisado e mesclado (autorização explícita do Marcelo). Deploy em produção confirmado (commit `913cae2`). **Validação pós-deploy:** a OLX estava bloqueada no momento do deploy (achado pré-existente, não relacionado a esta mudança — mesma degradação anti-bot já investigada antes). Sem conseguir uma run ao vivo bem-sucedida, validei o código já deployado rodando contra a fixture real diretamente no Pi: `gearbox`/`fuel_type` extraídos corretamente em 100% dos 50 itens.

---

# Fase 4 — GoGarage e TurboClass

> Branch: `fase4-gogarage-turboclass` (a partir de `main`, com Fases 0-3 mescladas). Prompt: `docs/prompts/PROMPT-exec-melhorias-sources-v2.md`. Rede usada nesta fase: **0 requisições** (reaproveitando a fixture da Fase 0).

## GoGarage — achado real ao rodar o parser pela primeira vez

Rodar `scrape_gogarage` (real, nunca executado antes contra fixture — pendência da Fase 0) contra `tests/fixtures/source_regression/gogarage/2026-09-28_civic/listing.html` deu **12 itens para a busca "honda civic"**. Inspeção item a item: **11 dos 12 não têm nenhuma relação com "civic"** — Renault Clio, Honda City, Volkswagen Nivus, Chevrolet Spin, Cruze, Peugeot 207, Gol, Fiesta, Santana, Palio, Kadett. Confirma exatamente o achado ao vivo do prompt ("carrossel de boosts/destaques não relacionados à busca").

**Causa raiz encontrada por inspeção do HTML:** a página tem duas seções distintas:
- `<div class="gg-home-curated" id="ggHomeCuratedSections">` — carrossel fixo da home ("Mais recentes"/"Boosts"/"Peças do marketplace"), **igual pra qualquer busca**, sem filtro pelo termo.
- `<div class="bc-resultsbar" id="resultados">` com `<div id="resultsMount"></div>` — a grade real de resultados, **vazia no HTML estático** desta fixture (`<div class="bc-kpi">Carregando os achados…</div>` confirma que é populada via JS/AJAX, `POST ?action=search`, já documentado na auditoria de 25/09).

O parser atual (`_extract_from_anchors`, `app/scrapers/gogarage.py`) varria **qualquer** `<a href*="/ads/">` da página inteira, sem distinguir as duas seções — por isso pegava só o carrossel (sempre presente) e nunca a grade real (vazia sem JS nesta captura).

**Mudança:** `_extract_from_anchors` e o re-lookup de card em `scrape_gogarage` agora excluem qualquer `<a>` descendente de `#ggHomeCuratedSections` (via XPath `not(ancestor::*[@id='ggHomeCuratedSections'])`). Escolhi excluir o container **conhecido-ruim** em vez de tentar mirar no container "bom" (que não pude validar com JS real, dado o orçamento de rede zero desta fase) — mais robusto a variações que eu não consigo confirmar sem rede.

**Resultado nesta fixture, pós-fix: 0 itens** (não 12 com ruído). Zero é estritamente melhor que 11 itens fora do tema — satisfaz o gate ("nenhum item fora do termo buscado") mas **não** resolve captura real pra esta fixture específica, porque ela foi capturada sem JS (curl simples, Fase 0) e a grade real depende de JS/AJAX que nunca rodou.

**Achado operacional importante (não uma regressão desta fase):** em produção, `gogarage` já roda com `default_force_browser=True` (`app/sources/builtins.py`, não alterado) — ou seja, o HTML que o scraper processa em produção **já é pós-JS** (renderizado via Playwright), diferente desta fixture (capturada via HTTP puro). Isso significa que, em produção, a grade real provavelmente **não** está vazia — só nesta fixture específica, que não reflete o caminho real de produção.

**CONFIRMADO pós-deploy (30/09):** forcei uma run real (`run_source_for_all_wishlists(..., "gogarage", force=True)`) após o deploy — `status=success, found=37, matched=1` (não `found=0`). Inspecionei os `car_listings` recém-atualizados: resultados genuinamente relevantes (`honda-civic-lx-1-6-1999-automatico`, `civic-ek-k20`, `honda-civic-lsi-93-turbo-d16-vtec`, múltiplos `honda-fit-*`), sem nenhum dos carros aleatórios do carrossel (Clio/Cruze/Kadett/etc.) que apareciam antes do fix. Confirma a hipótese: o fix funciona corretamente em produção, onde o HTML já é pós-JS.

**Divergência de citação da Fase 0, reconciliada:** a auditoria de 25/09 (`scraping-efetividade-audit.md`) citava JSON-LD (`@id`) como fonte primária do GoGarage; a fixture de 28/09 só tinha JSON-LD `WebSite` (sem `ItemList`/`Product`). Explicação: `_extract_jsonld_itemlist` (código atual) já tenta JSON-LD `itemListElement` primeiro e cai pro fallback de âncoras quando não encontra — comportamento correto, só que nesta fixture específica não há `ItemList` (site pode ter deixado de emitir esse JSON-LD para resultados de busca, ou nunca emitiu e a citação de 25/09 se referia a outra página/contexto). Não é uma regressão de código, é o fallback funcionando como projetado.

**`external_id` → `data-ad-id` (avaliação, ADR-0001, não aplicado):** os cards têm um atributo `data-ad-id` (ex.: `data-ad-id="1292"`) nos links, mais estável em tese que o slug da URL (`_guess_external_id`, que já usa o slug de `/ads/<slug>` — igual ao pedido do prompt, não migrei). Migrar exigiria comparar slug↔`data-ad-id` por um período pra garantir que a mesma ad sempre mapeia pro mesmo `data-ad-id` entre execuções (não verificado nesta fase) antes de considerar — risco de dedup duplo/perdido se algum `data-ad-id` mudar entre requests ou se o slug já usado hoje divergir do id numérico pra ads antigas. Não aplicado, conforme instrução do prompt.

## TurboClass — `engine_tag`

`app/scrapers/turboclass.py`: variável `spec` (MOTORIZAÇÃO do card — Turbo/Original/etc, já extraída e usada só para compor o `title`) agora também sai como campo extra `"engine_tag"`. Sem mudança de schema: não é chave reconhecida por `app/sources/normalize.py`, cai no catch-all `extras` (JSONB já existente em `CarListing`), confirmado via `normalize_ad` num teste dedicado.

## Testes

```
pytest tests/ -k "gogarage or turboclass or normalize or contract" -q
→ 122 passed
```

- `tests/test_gogarage_curated_carousel_exclusion.py` (novo): exclusão do carrossel confirmada com dado sintético (card destaque + card real lado a lado); gate da Fase 4 confirmado na fixture real (0 itens, não itens fora do tema).
- `tests/test_turboclass_engine_tag.py` (novo): `engine_tag` presente em 100% da fixture real (27 itens); fluxo ponta a ponta via `normalize_ad` confirmando que cai em `extras` sem mudança de schema.

## Riscos remanescentes (Fase 4)

1. ~~GoGarage: captura real não validada~~ — **resolvido pós-deploy** (30/09): run real forçada, `found=37`, resultados relevantes confirmados em `car_listings` (ver seção acima).
2. **GoGarage: `_extract_jsonld_itemlist` não recebeu a mesma exclusão.** Se o carrossel da home algum dia emitir seu próprio JSON-LD `ItemList` (não emite hoje, confirmado), essa função ficaria vulnerável ao mesmo problema. Não aplicado porque não há evidência atual de que isso acontece.
3. **GoGarage: fallback regex (`except Exception` em `_extract_from_anchors`) não tem a exclusão** — só o caminho `lxml`/XPath tem. Risco baixo (fallback de último recurso, só ativa se o parse lxml falhar).

## Próximo passo (Fase 4)

Abrir PR desta branch (`fase4-gogarage-turboclass`) para revisão. Esta é a última fase do prompt v2 — depois desta, todas as 4 fases estarão completas.
