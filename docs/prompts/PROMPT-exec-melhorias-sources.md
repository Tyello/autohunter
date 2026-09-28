# Prompt Claude Code — Execução: melhorias nas sources de classificados

> Origem: avaliação ao vivo das sources em 28/09/2026 (doc "AutoHunter — Avaliação das Sources e Melhorias").
> Execute **por fases**. Cada fase = 1 branch + 1 PR. **Não comece a fase seguinte** sem que a anterior esteja com testes verdes e o relatório atualizado.

## Modo de operação

- **Fase 0 é READ-ONLY.** Das fases 1 a 4 em diante, as escritas ficam restritas aos arquivos listados em cada fase, aos testes, às fixtures e ao relatório.
- **Proibido:** migrações e alterações de schema, deploy, mudar `source_configs` em produção, qualquer bypass anti-bot, solver de CAPTCHA ou proxy, e adicionar dependências novas (Scrapling já é **NO-GO**, ver `docs/spikes/scrapling-parser-spike.md`).
- **Rede:** permitida só para capturar fixtures, com **no máximo 40 requisições no total**, intervalo ≥2s entre elas, respeitando o `robots.txt`. Registre no relatório cada comando executado e o status HTTP recebido.
- **Citações:** toda afirmação sobre o código precisa de `arquivo:linha`. O que não puder ser confirmado deve ser marcado como **NÃO VERIFICADO**, sem inferência.
- **Entregável de acompanhamento (único):** `docs/spikes/sources-melhorias-execucao.md`. Atualize ao final de cada fase com: o que mudou, os testes, o antes/depois de campos preenchidos por fixture e as pendências.

## Contexto (não reconstrua; use isto)

- Garagem Alvo / autohunter: alertas de anúncios de carros de entusiasta via Telegram. Stack: Python 3.13, FastAPI, SQLAlchemy/Alembic, APScheduler, curl_cffi, Playwright.
- **Restrições obrigatórias:**
  1. Raspberry Pi 4 (4 GB), com CPU fraca.
  2. Supabase é remoto: **nenhuma** mudança pode adicionar query por anúncio.
  3. Chromium consome muita memória: toda mudança deve **reduzir** o uso de browser, nunca aumentar.
- **ADR-0001:** dedup por chave canônica; "na dúvida, não colapsar". Mudanças de `external_id` afetam a dedup, então trate-as como risco.
- **ADR-0002:** async só no scraping HTTP-first; DB async fica fora de escopo.
- **Lição registrada:** quando várias dimensões do score falham juntas, a causa é o parse perdendo campos (ano/km) antes do scorer. Meça **preenchimento de campo**, não só a contagem de anúncios.
- **Infra existente, que deve ser reutilizada:** registro de sources em `app/sources/builtins.py`; fallback HTTP→browser em `app/scrapers/fetching.py`; `app/scrapers/hybrid_cookies.py`; `dual_run` em `app/sources/dual_run.py` e `app/scrapers/dual_run.py`; `parse_failure` em `app/scrapers/parse_failure.py`; `finalize_listings` em `app/scrapers/contract.py`; e fixtures de regressão (`docs/source_regression_fixtures.md`, `tests/fixtures/source_regression/`, `tests/test_source_regression_fixtures.py`).

## Achados da avaliação ao vivo (28/09) — ponto de partida

Os testes foram feitos no Chrome logado do Marcelo, com IP residencial. **Revalide antes de assumir** que o mesmo vale no Pi.

| Source | Achado |
|---|---|
| Mercado Livre | Sem cookies, o site devolve um shell HTML de ~9 KB, sem `polycard`. Com cookies, vêm ~1,9 MB com ~147 `"polycard"`. Ano e km estão em `{"type":"attributes_list", ..., "attributes_list":{"texts":["2014","108.000 Km"]}}` e **não são extraídos** (`_parse_polycard_items`, `app/scrapers/mercadolivre.py:626`). O seletor `h2.ui-search-item__title` tem 0 ocorrências; o título atual está em `.poly-component__title` e os atributos em `.poly-attributes_list__item`. O slug `honda-civic` redireciona para `/honda/civic/?loader=true`. Filtros por path existem: `_YearRange_AAAA-AAAA`, `_PriceRange_`. |
| OLX | Não há mais `__NEXT_DATA__`. Os anúncios estão no stream RSC `self.__next_f.push` com `properties` (`regdate`, `mileage`, `gearbox`, `fuel`, `vehicle_brand`, `vehicle_model`, `carcolor`), além de `professionalAd`, `fixedOnTop` e `lastBumpAgeSecs`. O JSON-LD só traz `AggregateOffer`. O parser RSC já existe (`app/scrapers/olx.py:386-446`). A busca `?q=honda civic` retorna 9.362 resultados, e os cards patrocinados/destaque repetem o mesmo carro. |
| Chaves na Mão | O HTML **sem JS** já tem JSON-LD `ItemList`, com 15 `Product` por página: `name` com o ano, `offers.price`, `url` com `id-NNN`, `color` e `seller`. O km aparece só no texto do card. Paginação por `?pg=N`. Hoje está com `force_browser=True`. |
| Mobiauto | A resposta HTTP 200 sem JS traz `__NEXT_DATA__` → `props.pageProps.deals.results` (24 itens/página, com `numResults`). Cada item tem `id`, `price`, `km`, `dealer` e `deal0km`, além de `trim.productionYear`, `trim.model.year`, `trim.transmission.name`, `trim.fuel.name` e `trim.bodystyle.name`. Paginação por `?page=N`. Hoje é browser-first. |
| Kavak | Next.js RSC. O HTML sem JS contém os cards: `title` ("Honda • Civic"), `subtitle` ("2014 • 133.000 km • versão • Automático"), `mainPrice` e `footerInfo` (cidade), além do objeto `analytics` (`car_make`, `car_model`, `car_price`). Hoje é browser-first. |
| GoGarage | `?q=civic` renderiza um carrossel de boosts/destaques **não relacionados** à busca (Clio, City, 207) acima da grade filtrada. A busca real é um `POST ?action=search` (FormData). Não há mais JSON-LD `ItemList`. Os cards trazem `data-ad-card="1"`, e o botão "Ver detalhes" tem `href="/ads/<slug>"` e `data-ad-id="<num>"`. |
| TurboClass | O card tem o campo `MOTORIZAÇÃO` (Turbo / Original / etc.), hoje descartado. O km aparece só no detalhe. |
| iCarros / Webmotors | Continuam desabilitadas. **Não mexer.** |

---

## Fase 0 — Auditoria e fixtures (READ-ONLY no `app/`)

1. Para ML, OLX, Chaves na Mão, Mobiauto, Kavak, GoGarage e TurboClass, cite com `arquivo:linha`:
   - o caminho de fetch efetivo (`fetch_mode`, `force_browser`, fallback);
   - a função que produz cada campo: `external_id`, `url`, `title`, `price`, `year`, `km`, `location`, `thumbnail`.
2. Capture fixtures atuais em `tests/fixtures/source_regression/<source>/2026-09-28_civic/` seguindo `docs/source_regression_fixtures.md`, com `listing.html` e `expectations.json`.
   - **ML:** tente com os cookies do fluxo existente (`hybrid_cookies` / storage_state). Se só vier o shell de ~9 KB, **salve também esse shell** como cenário `shell_sem_cookies` e marque a fixture com cookies como **NÃO VERIFICADO — pedir ao Marcelo o HTML salvo do navegador**.
3. Rode os parsers **atuais** contra cada fixture e produza, no relatório, a tabela de **preenchimento por campo** (% de itens com `year`, `km`, `price`, `location`, `thumbnail`). Essa tabela é o baseline do "antes".
4. OLX: confirme, com a fixture, se o parse de produção passa por `_extract_rsc_json_chunks` ou cai no fallback de cards. Cite o ponto de decisão.

**Gate:** relatório com o baseline preenchido e as fixtures commitadas. Nada em `app/` alterado.

## Fase 1 — Mercado Livre (maior impacto no score)

Arquivos: `app/scrapers/mercadolivre.py` e `app/services/search_urls_service.py` (só `ml_url`).
1. Em `_parse_polycard_items`, extraia `attributes_list.texts` e mapeie o ano (4 dígitos entre 1950 e o ano atual + 1) e o km (via `extract_mileage_km_from_text` de `app/scrapers/parsing.py`). Parse o JSON do polycard em vez de ampliar a regex, se isso for viável sem custo relevante de CPU. Justifique a escolha no relatório.
2. Fallback DOM: aceite `.poly-component__title` e `.poly-attributes_list__item`, **mantendo** os seletores antigos.
3. Detecção de bloqueio: uma resposta sem nenhum `"polycard"` e sem `ui-search-layout__item`, com HTML < 50 KB, deve ser classificada como **blocked/shell** (use a classificação de erro já existente), **não** como `found=0`.
4. `ml_url`: quando marca e modelo forem inferíveis, gere direto `/veiculos/carros-caminhonetes/<marca>/<modelo>/` para evitar o redirect. **Não** adicione `_YearRange_` nesta fase; só documente no relatório como aplicaria.

Testes: fixture ML com `year` e `km` preenchidos em ≥90% dos itens, e fixture shell classificada como bloqueio.

**Gate:** antes/depois de preenchimento no relatório e suíte `pytest -q` verde.

## Fase 2 — OLX (confirmar e limpar)

Arquivo: `app/scrapers/olx.py`.
1. Garanta que o caminho RSC seja o primário e que `__NEXT_DATA__` fique como fallback. Não reescreva o que já funciona.
2. Extraia `gearbox`, `fuel` e `professionalAd` das `properties` como campos **extras**, somente se `finalize_listings` já os aceitar sem mudança de schema. Caso contrário, só documente.
3. Anúncios `fixedOnTop` / patrocinados: remova duplicatas por `listId` dentro da mesma página. Não descarte o anúncio em si.

**Gate:** fixture OLX com `year` e `km` ≥90% e zero `listId` duplicado.

## Fase 3 — Tirar Chromium de Mobiauto, Chaves na Mão e Kavak

Arquivos: `app/scrapers/mobiauto.py`, `app/scrapers/chavesnamao.py`, `app/scrapers/kavak.py` e `app/sources/builtins.py` (só `fetch_mode` e defaults).
1. Implemente um parse HTTP-first para cada source, com browser só como fallback:
   - **Mobiauto:** `__NEXT_DATA__.props.pageProps.deals.results`.
   - **Chaves na Mão:** JSON-LD `ItemList` + km do card.
   - **Kavak:** payload RSC dos cards (`title`, `subtitle`, `mainPrice`, `footerInfo`).
2. **Não altere** `force_browser` em produção. Deixe o default de seed pronto e documente o rollout via `dual_run` (`compare_only` → comparar `found` e preenchimento HTTP vs browser por ≥24 h no Pi → só então `/admin sources set-extra`).
3. Garanta que `external_id` **não mude** em relação ao scraper atual (ADR-0001). Se mudar, pare e reporte.

**Gate:** fixtures com preenchimento ≥ o baseline do browser e `external_id` idêntico ao atual em todas as fixtures.

## Fase 4 — GoGarage e TurboClass (nicho)

1. **GoGarage** (`app/scrapers/gogarage.py`): restrinja a extração aos cards da grade de resultados, excluindo o carrossel de boosts/destaques. Avalie **só no relatório** a migração de `external_id` do slug para `data-ad-id`. **Não aplique** a migração sem plano de dedup (ADR-0001).
2. **TurboClass** (`app/scrapers/turboclass.py`): capture `MOTORIZAÇÃO` como campo extra (ex.: `engine_tag`), sem mudança de schema. Se exigir schema, apenas documente.

**Gate:** fixture GoGarage sem nenhum item fora do termo buscado.

## Fora de escopo

Webmotors, iCarros, Facebook Marketplace, leilões, `_YearRange_`/`_PriceRange_` no ML, novos campos no schema, mudanças no scorer e deploy.

## Formato do relatório `docs/spikes/sources-melhorias-execucao.md`

1. Baseline da Fase 0: tabela de preenchimento por source × campo.
2. Uma seção por fase: mudanças (`arquivo:linha`), testes, antes/depois e riscos.
3. Pendências e itens **NÃO VERIFICADO**.
4. Plano de rollout no Pi: comandos `/admin` na ordem, com o critério de go/no-go de cada source.
