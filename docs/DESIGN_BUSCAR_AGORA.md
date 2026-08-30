# Design: Motor de "Buscar agora" on-demand no banco

**Status:** Discovery (read-only) — aguardando revisão antes de qualquer implementação.
**Data:** 2026-08-29
**Escopo desta passada:** investigação + desenho. Nenhum código, schema ou config foi alterado.

---

## 0. Divergências em relação ao brief (leia isto primeiro)

1. **"Buscar agora" hoje NÃO é uma busca no banco — é uma raspagem ao vivo.** `/buscar` e o botão `🔎 Buscar agora` (`MENU:SEARCH`) chamam `manual_search()` (`app/services/search_service.py:25`), que **itera todas as fontes cadastradas e executa `plugin.scrape()` de verdade** (respeitando backoff/cooldown por fonte) antes de fazer qualquer leitura no banco. Só depois disso roda uma query simples (`ILIKE` em `title`/`location`, `ORDER BY created_at DESC LIMIT 30`). Ou seja, o pedido do usuário não é "adicionar" uma busca no banco — é **substituir** um fluxo que hoje dispara scraping síncrono (com custo de Playwright/PerimeterX e rede) por um fluxo puramente de leitura. Isso é uma boa notícia para o objetivo de custo, mas muda o enquadramento do brief: não estamos otimizando uma busca no banco existente, estamos **removendo o scraping do caminho crítico do usuário**.
2. **ADR-0001 e ADR-0002 têm status `Proposed`, não `Accepted`.** (`docs/ADR-0001-search-deduplication.md:3`, `docs/ADR-0002-async-scope.md:3`). Na prática, porém, ambas já foram **implementadas parcialmente**: `canonical_search_key()` existe em `app/services/search_deduplication_service.py:7` e `match_listings_for_active_wishlists()` existe em `app/services/matching_service.py:854`. O texto do brief ("ADRs vigentes") está correto quanto ao *conteúdo/intenção*, mas o status formal do documento está desatualizado — vale corrigir o rótulo dos ADRs numa próxima limpeza, não é bloqueante aqui.
3. **Não existem colunas `status` nem `last_seen_at` em `car_listings`.** O schema atual (`app/models/car_listing.py`) só tem lifecycle via `is_sold: bool` + `sold_at: datetime | None` (adicionadas em `migrations/versions/fase1_005_cursors_and_sold.py`). O brief já assumia que talvez não existissem ("se não existirem") — confirmado: não existem. Isso é o Pré-requisito B mais crítico.
4. **Upsert de listing já ignora updates em campos preenchidos.** `insert_ignore_duplicates_return_ids` (`app/repositories/car_listings_repo.py`, `ON CONFLICT (source, external_id) DO UPDATE`) usa `COALESCE(existing.<campo>, excluded.<campo>)` para os campos promovidos (price, year, mileage_km, city, state, color, etc.) — ou seja, **uma vez que um campo é preenchido, ele nunca é sobrescrito por uma raspagem posterior**, mesmo que o preço real tenha mudado no marketplace. Isso não estava no brief e é relevante para "correção de facetas": um `price` errado capturado uma vez pode ficar errado para sempre até o anúncio ser re-inserido. Não é escopo desta feature corrigir, mas é um risco de dado que afeta diretamente a confiabilidade das facetas de preço/km.
5. **Não existe "criador de busca" e "banco de listings" com filtros 100% equivalentes** — ver mapa completo na seção 3. O ponto mais importante: wishlist filtra por **`model`/`make`/título via texto livre na query** (`Wishlist.query`, casado por tokens — ver `app/services/wishlists_service.py` e `WishlistToken`), não por um campo estruturado `make`/`model` com filtro dedicado. Já a tabela `car_listings` tem `make` e `model` como colunas estruturadas separadas. Ou seja: a wishlist trata "modelo" como parte do texto de busca; o banco trata como coluna. Uma faceta por modelo no motor novo pode usar a coluna estruturada, mas ao devolver isso como alerta pré-preenchido, o campo `query` da wishlist ainda vai ser texto livre reconstituído — não há um `wishlist_filters.field = "model"` hoje.

---

## 1. Fluxo atual — "Buscar agora" e "Criar busca"

### 1.1 "Buscar agora" (a ser substituído)

| Etapa | Local |
|---|---|
| Entrada por comando | `cmd_buscar` — `app/bot/handlers.py:430` (parseia `/buscar <termo> [source:x]` via `_parse_query_and_sources`, `app/bot/handlers.py:185`) |
| Entrada por menu | `cb_quick_search_start` — `app/bot/handlers.py:381`, callback `MENU:SEARCH` |
| Conversa | `quick_search_conversation()` — `app/bot/handlers.py:408`, único estado `QUICK_SEARCH_QUERY = 1001` (`app/bot/handlers.py:327`) |
| Texto livre → busca | `quick_search_on_text` (`app/bot/handlers.py:391`) → `start_manual_search_flow` (`app/bot/handlers.py:330`) |
| Execução (scrape + DB) | `_run_manual_search_sync` (`app/bot/handlers.py:89`), roda em thread via `asyncio.to_thread` |
| Parsing da entrada | `parse_wishlist_query_with_implicit_filters` (reaproveitado do fluxo de wishlist!) + `_extract_extra_price_filters` (`app/bot/handlers.py:264`) + `_extract_state_filter_from_query` (`app/bot/handlers.py:251`) — extrai ano/preço/UF embutidos no texto, ex. "civic até 120000 sp" |
| Scrape ao vivo | `manual_search()` (`app/services/search_service.py:25`) — itera `list_sources()`, roda `plugin.scrape()` de verdade (respeita backoff, exceto quando `sources` explícito força `force_scrape=True`) |
| Filtro pós-scrape | `_listing_matches_semantic_filters` (`app/bot/handlers.py:279`) aplica os filtros extraídos (price/year/state) em memória sobre os resultados |
| Resultado | até 5 payloads formatados, sem persistência de "busca salva" |

Ou seja: **a normalização de texto → filtros (ano, preço, UF) já existe e é compartilhada com o fluxo de wishlist** via `parse_wishlist_query_with_implicit_filters`. Isso é uma peça pronta e reaproveitável para o parser do motor novo — não precisa reinventar.

### 1.2 "Criar busca" (wishlist)

| Etapa | Local |
|---|---|
| Entry point (menu) | `cb_menu` com `MENU:CREATE_WISHLIST` → `menu_create_wishlist_conversation()` (`app/bot/handlers_core.py:1387`) |
| Estado único | `MENU_CREATE_WISHLIST_QUERY = 1` (`app/bot/handlers_core.py:21`) |
| Texto → draft | `menu_create_wishlist_on_text` (`app/bot/handlers_core.py:1074`) — chama `parse_wishlist_query_with_implicit_filters`, grava em `context.user_data["menu_create_wishlist_query"]` e `context.user_data["menu_create_wishlist_draft_filters"]` (via `build_draft_filter_groups`), então chama `_show_create_wishlist_summary_screen` |
| Botões (ajustar filtros, confirmar leilões, criar) | `cb_menu_create_wishlist` (`app/bot/handlers_core.py:1104`), callbacks `CWL:*` / `CWLF:*` |
| Confirmação final | `CWL:CREATE` → `create_wishlist_with_filters_and_initial_summary` (com draft filters) ou `add_wishlist_with_initial_summary` (sem filtros) — ambos em `app/services/wishlists_service.py` |
| Persistência | `Wishlist` (`query`, `is_active`, `include_auctions`) + N `WishlistFilter` (`field`, `operator`, `value`) — ver seção 2 |

**Ponto de reentrada com filtros pré-preenchidos (o que o brief pede):** é exatamente o par de linhas `app/bot/handlers_core.py:1096-1099`:

```python
context.user_data["menu_create_wishlist_query"] = parsed.cleaned_query
context.user_data["menu_create_wishlist_draft_filters"] = build_draft_filter_groups(parsed.filters)
context.user_data["menu_create_wishlist_include_auctions"] = False
return await _show_create_wishlist_summary_screen(update, context)
```

O motor de busca no banco, ao chegar em "zero resultado, criar alerta?", só precisa popular esses três campos de `context.user_data` com o termo normalizado + os filtros de faceta escolhidos pelo usuário (convertidos para `NormalizedWishlistFilter`, mesmo formato que `parse_wishlist_query_with_implicit_filters` já produz) e retornar `MENU_CREATE_WISHLIST_QUERY`. **Não é preciso criar um novo estado de conversa** — a tela de resumo (`_show_create_wishlist_summary_screen`) e os botões `[Criar alerta] [Ajustar filtros] [Agora não]` já existem sob os nomes `CWL:CREATE`, `CWL:CREATE_FILTERS` e `CWL:CANCEL`. "Ajustar filtros" já cai em `_show_draft_filters_screen` (`app/bot/handlers_core.py:1198`), que é o fluxo de criar busca "com campos preenchidos" pedido no brief.

**Ressalva de engenharia de conversa:** a `ConversationHandler` de criação de wishlist (`menu_create_wishlist_conversation`) tem como único `entry_point` o callback `MENU:CREATE_WISHLIST` (`app/bot/handlers_core.py:1389`). Para o motor de busca (que vive presumivelmente numa nova `ConversationHandler` própria, ex. `search_engine_conversation`) invocar esse fluxo diretamente, é preciso decidir **como** — as opções são (a) despachar um callback sintético `MENU:CREATE_WISHLIST` que a própria lib do bot resolve, ou (b) fatorar a lógica de `menu_create_wishlist_on_text` num helper chamável diretamente, populando o `user_data` e chamando `_show_create_wishlist_summary_screen`, e então transicionar o estado do `ConversationHandler` ativo. **Isso é uma decisão de implementação, não uma trava — mas escolher (a) ou (b) tem que estar na spec antes de codar**, porque `python-telegram-bot` não permite "pular" de uma conversa para outra sem fallback/reentrada explícita.

---

## 2. Schema de `car_listings` — normalização de campos de faceta

Fonte: `app/models/car_listing.py` + `migrations/versions/fase1_002_extend_car_listings.py`, `fase1_007_car_listings_contract_fields.py`.

| Campo faceta | Coluna / tipo | Constraint | Normalização conhecida (código) | Pronto para GROUP BY/ORDER BY? |
|---|---|---|---|---|
| Modelo/título | `title: Text` (nullable), `make: Text`, `model: Text` (ambos nullable) | nenhuma | Populados pelos scrapers/adapters por fonte, sem normalizador central único identificado nesta passada. **Suposição não confirmada:** se `make`/`model` vêm consistentes entre fontes (ex. "Honda" vs "HONDA" vs "honda") não foi possível verificar sem consultar dados reais do Supabase. | **Não confirmado** — precisa de amostra real. Se houver variação de caixa/acentuação, `GROUP BY model` vai fragmentar contagens (ex. "Civic" e "civic" como grupos distintos) até normalizar (`lower()`/`unaccent`). |
| Ano | `year: Integer`, nullable | nenhuma (sem CHECK de faixa no schema) | Validação de faixa (1900–2100) existe só no **parser de filtro de wishlist** (`normalize_wishlist_filter_input`, `app/services/wishlists_service.py:853-860`), não na ingestão do listing em si. | Tipo é `int`, pronto para `GROUP BY`/faixas — mas nulos e outliers (ex. ano 0 ou 9999 vindo de scraper com bug) não são bloqueados na escrita. Índice parcial `idx_car_listings_year` já existe (ver seção 4). |
| Estado/UF | `state: Text`, nullable | nenhuma | Sem normalização garantida na ingestão (não há CHECK de que é uma UF de 2 letras). A validação de UF (`KNOWN_STATES`, conversão nome→UF) só existe no parser de **filtro de wishlist** (`app/services/wishlists_service.py:931-939`), não na escrita de `car_listings`. | **Suposição não confirmada** se o dado já vem como UF de 2 letras dos scrapers ou como texto livre ("São Paulo" vs "SP"). Isso é o ponto mais arriscado para uma faceta "por UF" confiável — precisa de auditoria de dados real antes de expor a faceta. |
| Cidade | `city: Text`, nullable | nenhuma | Mesma situação: sem normalização garantida na escrita. | Idem — GROUP BY vai fragmentar se houver variação de grafia. |
| Preço | `price: Numeric(12,2)`, nullable | Guard de aplicação (`_sanitize_price`, `app/services/listings_service.py:29`) — descarta valores `<= 0`, `> 9999999999.99`, ou não-numéricos, **na ingestão**, antes do upsert | Sanitização já ocorre no caminho de ingest atual (`ingest_listings`/`ingest_listings_stats`) | Tipo numérico correto, sanitização de escrita já existe. Bom candidato a faceta/ordenação sem trabalho extra. |
| KM/rodagem | `mileage_km: Integer`, nullable | nenhuma no schema; validação de faixa (0–1.500.000) só no parser de **filtro de wishlist** | Nenhuma sanitização na ingestão do listing em si (diferente de `price`). | Tipo correto, mas sem guard de ingestão — outlier de scraper (ex. km negativo ou 99999999) pode entrar sem barreira. |
| Cor | `color: Text`, nullable | nenhuma | Normalização (`normalize()`) só existe no parser de **filtro de wishlist** (`app/services/wishlists_service.py:930`), não na ingestão do listing. | Mesma fragilidade de `state`/`city`: se o dado bruto do scraper não é normalizado na escrita, contagem por faceta pode fragmentar variações. |

**% de nulos/sujos:** não é possível reportar sem uma consulta real ao Supabase (fora do escopo read-only local desta investigação, e a instrução do brief pede para não inventar números). **Ação recomendada antes da Fase 1 de implementação:** rodar uma consulta agregada única (ex. `COUNT(*) FILTER (WHERE state IS NULL)`, `COUNT(DISTINCT state)`, `COUNT(DISTINCT lower(city))` vs `COUNT(DISTINCT city)`) contra o Supabase real para substituir essa suposição por dado.

### Liveness / status — campos hoje

`car_listings` tem apenas:
- `is_sold: Boolean` (default `False`)
- `sold_at: DateTime(timezone=True)`, nullable

Não existe `last_seen_at` nem `status` (ativo/suspeito/inativo) como pede o brief — precisam ser adicionados (proposta na seção 5).

### `source_url_cursors` / chave canônica (ADR-0001)

- `source_url_cursors` (`app/models/source_url_cursor.py`) segue chave `(source, url)` — cursor de paginação por URL de busca, não é em si a "chave canônica de busca" da ADR.
- A chave canônica de fato é `canonical_search_key(wishlist, plugin) -> str` (`app/services/search_deduplication_service.py:7`), usada para deduplicar wishlists equivalentes **antes de decidir o que raspar** — é um mecanismo de *dedup de scraping*, não de dedup de listings persistidos. Dedup de listing (o "não colapsar na dúvida" do ADR-0001) acontece via `UniqueConstraint("source", "external_id")` em `car_listings` (chave primária de dedup real) e via `cross_source_fingerprint` (campo existente, mas não vi uso ativo de matching cross-source nesta passada — **não confirmado** se há lógica que popula/usa esse campo hoje).

---

## 3. Filtros de wishlist vs. campos de listing — mapa 1:1

Filtros de wishlist suportados hoje (`normalize_wishlist_filter_input`, `app/services/wishlists_service.py:811-950`, e `_wishlist_filter_help_text`, `app/bot/handlers_core.py:51-67`):

| Filtro de wishlist (`WishlistFilter.field`) | Operadores válidos | Coluna equivalente em `car_listings` | Observação |
|---|---|---|---|
| `price` | lt, lte, gt, gte, eq, neq, between | `price` | 1:1 |
| `year` | lt, lte, gt, gte, eq, neq, between | `year` | 1:1 |
| `mileage_km` | lt, lte, gt, gte, eq, neq, between | `mileage_km` | 1:1 |
| `source` | eq, neq | `source` | 1:1 |
| `color` | eq, neq | `color` | 1:1 |
| `city` | eq, neq | `city` | 1:1 |
| `state` | eq (só) | `state` | 1:1, mas wishlist só aceita `eq` — sem `state in (...)` |
| `seller_type` | eq, neq | *(não existe coluna em `car_listing.py`)* | **Divergência**: wishlist filtra `seller_type`, mas o model `CarListing` lido nesta passada não tem essa coluna promovida — **precisa confirmar** se `seller_type` vem de `extras` (JSONB) em vez de coluna própria. Se sim, facetar/agrupar por ele exige `extras->>'seller_type'`, mais caro que coluna indexada. |
| `body_type` | eq, neq | `body_type` | 1:1 |
| `doors` | eq, neq, between (schema aceita lt/lte/gt/gte também) | `doors` | 1:1 |
| — (não é filtro estruturado) | — | `make`, `model`, `title` | **Divergência principal:** modelo/marca/título são casados via **texto livre da wishlist** (`Wishlist.query` + índice invertido de tokens, `WishlistToken`), não via `WishlistFilter`. O motor de busca no banco vai facetar por `make`/`model` como coluna, mas ao devolver isso como pré-preenchimento de alerta, o valor cai de volta em `query` (texto), não em um `WishlistFilter(field="model", ...)`. |
| — | — | `fuel_type`, `transmission`, `version`, `cross_source_fingerprint`, `listing_type`, `currency`, `is_sold`, `sold_at` | Colunas de listing sem filtro de wishlist equivalente hoje. Não é obrigatório cobrir todas no motor novo, mas se uma faceta usar, por exemplo, `fuel_type`, e o zero-resultado tentar oferecer "criar alerta" pré-preenchido com esse filtro, **não há campo de wishlist para recebê-lo** — a herança quebra silenciosamente exatamente como o brief antecipou. |

**Consequência prática para o Pré-requisito B:** o conjunto seguro de facetas para a v1 do motor (aquelas com correspondência 1:1 limpa em `WishlistFilter`) é: `price`, `year`, `mileage_km`, `source`, `color`, `city`, `state`, `body_type`, `doors`. Facetar por `make`/`model` funciona para exibição, mas a reconstrução do alerta precisa reinjetar o termo na `query` textual, não como `WishlistFilter`. Facetar por `fuel_type`/`transmission`/`seller_type` (se este último realmente não for coluna) exige decisão explícita antes de expor essas facetas no fluxo de zero-resultado.

---

## 4. Facetas e performance (respeitando Supabase)

### Proposta de shape da query de facetas (só a favor da discussão — nenhum código deve ser escrito nesta fase)

Uma única ida ao banco por faceta agregada, usando `GROUPING SETS` (ou `UNION ALL` de sub-agregações simples se `GROUPING SETS` não for confortável de manter em SQLAlchemy Core) sobre o mesmo `WHERE` de termo/filtros já aplicados:

```sql
SELECT 'state' AS facet, state AS bucket, COUNT(*) AS n
FROM car_listings
WHERE <predicado de termo + filtros já confirmados> AND status <> 'inativo'  -- ver seção 5
GROUP BY GROUPING SETS ((state), (price_bucket_expr), (year_bucket_expr))
```

Isso mantém **uma única round-trip** para o mapa de facetas completo (estado, faixa de ano, faixa de preço), em vez de uma query por faceta — que seria 3+ round-trips por toque de "buscar agora". Faixas de ano/preço (`price_bucket_expr`) precisam ser expressões `CASE WHEN` determinísticas e fixas para caber em `GROUPING SETS` sem uma tabela de buckets à parte — decisão de quais faixas usar deve ficar em spec, não aqui.

### Índices existentes (padrão de estilo a seguir — não propor migration agora)

Confirmados por `postgresql_where` em `migrations/versions/`:

| Índice | Tabela | Colunas | `WHERE` |
|---|---|---|---|
| `idx_car_listings_year` | `car_listings` | `year` | `year IS NOT NULL` |
| `idx_car_listings_make_model` | `car_listings` | `make, model` | `make IS NOT NULL AND model IS NOT NULL` |
| `idx_car_listings_city_state` | `car_listings` | `city, state` | `city IS NOT NULL OR state IS NOT NULL` |
| `uq_wishlist_filters_wishlist_field_op_value_active` | `wishlist_filters` | `wishlist_id, field, operator, value` (unique) | `is_active IS TRUE` |
| (delete guardrails) | `wishlist_tracked_listings` | `wishlist_id, car_listing_id` (unique) | `is_active IS TRUE` |
| (delete guardrails) | `wishlist_tracked_listings` | `wishlist_id, slot` (unique) | `is_active IS TRUE` |
| `ix_notifications_user_sent_at` | `notifications` | `user_id, sent_at` | `status = 'sent'` |
| `ix_notifications_wishlist_sent_24h` | `notifications` | `wishlist_id, sent_at` | `status = 'sent'` |
| `idx_scrape_jobs_source_queue` (unique) | `scrape_jobs` | `source, queue` | `status IN ('queued','running')` |
| `ix_notifications_score_v2` | `notifications` | `score_v2` | `score_v2 IS NOT NULL` |

Já há **cobertura parcial direta** para as três facetas mais prováveis (`year`, `make/model`, `city/state`) — bom sinal, o custo de faceta agregada não parte do zero. **Falta** cobertura equivalente para `price` (ex. `idx_car_listings_price WHERE price IS NOT NULL`) e para `mileage_km`, que hoje não têm índice parcial dedicado (não encontrado nesta busca) — candidatos naturais a propor formalmente na spec de implementação, seguindo o mesmo padrão `postgresql_where=... IS NOT NULL`.

---

## 5. Schema de liveness — proposta (não implementar agora)

### Colunas novas em `car_listings`

- `status: Text NOT NULL DEFAULT 'ativo'` com valores esperados `ativo | suspeito | inativo` (usar `Text` + CHECK, seguindo o padrão do projeto de não usar Enum nativo do Postgres seria uma decisão de spec — **suposição não confirmada**: não vi Enum nativo em uso nos models lidos, então `Text` + CHECK é a aposta consistente com o estilo do repo, mas confirmar contra o restante do schema antes de migrar).
- `last_seen_at: DateTime(timezone=True) NULLABLE` — atualizado a cada vez que o listing aparece de novo numa raspagem.

### Onde tocar `last_seen_at` sem round-trip extra

O ponto exato é o `ON CONFLICT ... DO UPDATE SET` já existente em `insert_ignore_duplicates_return_ids` (`app/repositories/car_listings_repo.py`) — é o **mesmo statement** usado tanto pelo scrape recorrente (`app/scheduler/jobs.py:296` e `:580`, via `ingest_listings_stats`) quanto pelo scrape manual de `/buscar` hoje. Adicionar `"last_seen_at": func.now()` **incondicional** dentro do `set_={}` desse upsert (ao lado dos `COALESCE(...)` dos demais campos) cobre 100% dos pontos de ingestão existentes com **zero round-trips adicionais** — é a mesma escrita que já acontece, só um campo a mais no `SET`.

Atenção: os demais campos usam `COALESCE(existing, excluded)` (não sobrescrevem se já preenchidos — ver divergência #4 na seção 0). `last_seen_at` deve ser a **exceção deliberada** — sempre sobrescrito com `now()`, nunca com `COALESCE`, porque seu propósito é justamente refletir a última vez que a raspagem viu o anúncio.

### Assinatura de "anúncio encerrado" por marketplace

| Fonte | Evidência no código encontrada nesta passada | Checável via liveness ao vivo? |
|---|---|---|
| Mercado Livre | `app/scrapers/sources/mercadolivre.py` existe; nenhuma lógica de detecção de "anúncio removido" (404/redirect/texto) foi localizada nesta passada de leitura superficial. **Não confirmado** — precisa inspeção dedicada do scraper ou teste empírico (bater num anúncio antigo e ver o comportamento real). | Sim, é fonte HTTP-first — mas o padrão de resposta (404 puro? redirect para busca? 200 com "anúncio não encontrado"?) precisa ser confirmado empiricamente antes de codar o checker. |
| OLX | `app/scrapers/sources/olx.py` existe. Mesma ressalva — não confirmado o padrão de resposta para anúncio encerrado. | Sim, mas padrão de resposta não confirmado. |
| Chaves na Mão | `app/scrapers/sources/chavesnamao.py` existe. Mesma ressalva. | Sim, mas padrão de resposta não confirmado. |
| Webmotors | `app/scrapers/sources/webmotors.py:6,27` confirma **PerimeterX + SPA React, browser-only** (`docs/SPIKE_WEBMOTORS_MOBILE_API.md` também trata do tema). | **Não** — confirma a suposição do brief. Cai no heurístico de `last_seen_at`/`status`, sem checagem ao vivo. |
| icarros, kavak, turboclass, gogarage/mobiauto | Scrapers existem (`app/scrapers/sources/`) mas não foram inspecionados nesta passada (fora do escopo direto do brief, que citou só as 4 fontes principais). | Não avaliado — se entrarem no motor de busca, repetir esta checagem antes de assumir HTTP-first checável. |

**Marcado explicitamente como suposição não confirmada:** o comportamento exato (404 vs. redirect vs. 200-com-texto) de ML/OLX/Chaves na Mão para anúncio removido não está documentado em nenhum arquivo lido nesta investigação. Isso precisa de um teste empírico dedicado (bater a URL de um `car_listing` antigo marcado como possivelmente vendido e observar a resposta real) antes de escrever o `LivenessChecker` por fonte — é candidato natural a ser a primeira etapa (read-only/empírica) da fase de implementação, não algo para assumir na spec.

---

## 6. Plano de implementação faseado + riscos

> Sequenciado para permitir merge e validação incremental. Cada PR é pequeno o bastante para revisão isolada. Tiers sugeridos assumindo o roteamento spec-kit do projeto (T1 leve / T2 média / T3 grande) — a classificação final é feita na spec de cada PR, não aqui.

1. **PR 0 — Auditoria empírica de dados (sem código, ou script descartável de leitura)**
   Rodar contra o Supabase real: % nulos por campo de faceta, `COUNT(DISTINCT lower(state))` vs `COUNT(DISTINCT state)` (e idem para `city`/`color`), distribuição de `year` fora de [1900,2100], distribuição de `mileage_km` negativo/absurdo. Também: bater 5-10 URLs antigas por fonte (ML, OLX, Chaves na Mão) para documentar o padrão real de "anúncio encerrado". Sem esse PR, os PRs 2 e 5 (facetas e liveness por fonte) partem de suposição, não de dado.
   **Validação:** relatório com números reais anexado à spec seguinte.

2. **PR 1 — Colunas `status` + `last_seen_at` (migration) + touch no upsert existente**
   Adicionar as duas colunas (nullable/com default seguro para não quebrar linhas existentes) e o `last_seen_at = func.now()` incondicional no `ON CONFLICT DO UPDATE` de `car_listings_repo.py`. **Não** liga nenhum comportamento de bot ainda — é só infraestrutura de dados.
   **Validação:** migration roda limpo; teste que confirma que um upsert repetido do mesmo `(source, external_id)` atualiza `last_seen_at` e não regride os demais campos (`COALESCE` intacto).
   Marcar como **[sensível]** na spec (migração de schema em produção via Supabase remoto).

3. **PR 2 — Índices parciais para `price` e `mileage_km`** (seguindo o padrão `postgresql_where=... IS NOT NULL` documentado na seção 4), guiado pelos números reais do PR 0.
   **Validação:** `EXPLAIN ANALYZE` da query de facetas antes/depois no ambiente com dados reais (ou staging equivalente).
   Marcar como **[sensível]** (migração de schema).

4. **PR 3 — Serviço de busca facetada (read-only, sem tocar bot ainda)**
   Novo serviço (ex. `app/services/facet_search_service.py`) com a query `GROUPING SETS` da seção 4, parametrizado por termo + filtros já confirmados. Reaproveitar `parse_wishlist_query_with_implicit_filters` para o parsing inicial do termo livre (já existe e já é usado nos dois fluxos atuais).
   **Validação:** testes unitários com fixtures de `car_listings` cobrindo: termo que casa, termo que não casa nada, filtro que zera resultado mas facet teria estoque em faixa vizinha.

5. **PR 4 — Liveness checker HTTP-first (ADR-0002 compliant)**
   Checker async por fonte (HEAD antes de GET, timeout curto), usando as assinaturas reais documentadas no PR 0. Webmotors explicitamente excluído (fallback para heurística `last_seen_at`). Rodar só sobre o top-N exibido, nunca sobre o conjunto completo.
   **Validação:** teste com mock HTTP simulando os 3 padrões (ativo, 404, redirect) por fonte real; teste que confirma que Webmotors nunca dispara checagem ao vivo.
   Risco a decidir antes de codar: o "limiar de confiança" de `last_seen_at` (brief sugere 15-30 min) — precisa ser parametrizado, não hardcoded, e a escolha do valor default é uma decisão de produto, não técnica.

6. **PR 5 — Handlers do bot: fluxo `buscar agora` novo (facetas → refinar → top-10 → zero-resultado)**
   Nova `ConversationHandler` (ou extensão da existente `quick_search_conversation`) implementando o fluxo de 5 passos do brief. Reaproveita `_show_create_wishlist_summary_screen` e os callbacks `CWL:*` para o reentry de "criar alerta" (ver seção 1.2). **Decisão bloqueante de spec:** opção (a) vs (b) da seção 1.2 para a transição entre conversas.
   **Validação:** teste de integração do bot cobrindo os 3 caminhos: faceta com estoque → top-10 → tracking; zero resultado com filtro válido → oferece alerta pré-preenchido → confirma → wishlist criada com os filtros corretos; termo sujo/sem match → orientação sem oferecer alerta.
   Marcar como **[sensível]** se tocar a `ConversationHandler` existente de criar wishlist (risco de regressão no fluxo já em produção).

7. **PR 6 — Remoção do scrape síncrono do caminho de "buscar agora"**
   Só depois do PR 6 validado em produção por um tempo: aposentar a chamada a `manual_search()`/`plugin.scrape()` dentro do fluxo interativo do bot (ADR-0001, item de ação 6, já cogita isso: "manter [scrape por-wishlist] só para buscar agora sob demanda" — este PR é o que finalmente descomissiona isso). Scraping continua existindo, só não roda mais bloqueando a resposta ao usuário.
   **Validação:** medir tempo de resposta do bot antes/depois; confirmar que scrape recorrente (scheduler) continua alimentando os dados que a busca facetada consome.
   Risco: se o scrape recorrente não cobrir a fonte/termo que o usuário busca, o motor novo pode devolver "zero resultado" onde antes o scrape ao vivo acharia algo. Isso é uma mudança de comportamento visível ao usuário e **precisa ser uma decisão de produto explícita antes deste PR**, não uma surpresa pós-deploy.

### Riscos e decisões pendentes (para o usuário, antes de qualquer código)

- **Decisão de produto:** aceitar que "buscar agora" deixe de fazer scrape ao vivo (PR 6) é uma mudança de expectativa para quem já usa o `/buscar` hoje. Vale um aviso de produto (ex. changelog no bot) na virada.
- **Decisão de escopo de faceta:** confirmar a lista final de facetas expostas na v1 (seção 3 recomenda começar só pelas que têm `WishlistFilter` 1:1: price, year, mileage_km, color, city, state, body_type, doors — deixando make/model como busca textual, não faceta clicável, até decidir como herdar para o alerta).
- **Decisão de UX de conversa:** opção (a) vs (b) da seção 1.2 para o reentry no fluxo de criar busca.
- **Decisão de threshold de liveness:** valor do "janela de confiança" de `last_seen_at` (15 min? 30 min?) — e se deve ser configurável por fonte (ex. fontes mais voláteis como Mercado Livre podem justificar janela menor que Chaves na Mão).
- **Risco de dado:** `COALESCE` no upsert (divergência #4) significa que facetas de preço podem estar "presas" num valor antigo. Não é bloqueante para esta feature, mas deveria virar um item de backlog separado (ex. permitir que a raspagem re-confirme/atualize preço mesmo se já preenchido) — fora de escopo aqui, só registrando o risco.
- **Dependência do PR 0:** todos os PRs de faceta/índice/liveness citam números que hoje são suposição. Não pular o PR 0.

---

## Premissas assumidas (gate de fechamento)

- **PREM-01:** Não foi possível auditar dados reais do Supabase nesta passada (ambiente local não tem acesso à instância de produção). Todos os números de "% nulo/sujo" ficam como pendência do PR 0.
- **PREM-02:** O comportamento HTTP de "anúncio removido" para Mercado Livre, OLX e Chaves na Mão não está documentado em código lido nesta passada — assumido como pendência empírica do PR 0, não decidido por suposição.
- **PREM-03:** Assumido que `seller_type` pode estar em `extras` (JSONB) em vez de coluna promovida, já que não aparece em `car_listing.py` — precisa confirmação antes de decidir se entra como faceta indexável na v1.
- **PREM-04:** Assumido que a transição entre `ConversationHandler`s (busca facetada → criar wishlist) será resolvida via opção (b) da seção 1.2 (helper compartilhado) por ser mais robusta a mudanças futuras do fluxo de criação — mas isto **não foi decidido pelo usuário**, só recomendado; fica como pergunta aberta para a spec de implementação do PR 5.
