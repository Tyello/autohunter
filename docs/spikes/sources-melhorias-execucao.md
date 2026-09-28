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

Todas as requisições HTTP feitas nesta fase, em ordem, com status HTTP. Total: **16 requisições** (limite: 40), intervalo ≥2.5s entre cada uma (Kavak respeitando `Crawl-delay: 20` do seu robots.txt — só 1 requisição feita naquele domínio).

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

Script usado (não faz parte da suíte de testes, é ferramenta de apoio ao relatório): `tests/fixtures/source_regression/_fase0_baseline.py`.

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

## 8. Próximo passo

Abrir PR desta branch (`fase0-audit-sources`) para revisão. **Não iniciar Fase 1** até esta PR ser revisada/mesclada, conforme regra do prompt de origem ("não comece a fase seguinte sem que a anterior esteja com testes verdes e o relatório atualizado").
