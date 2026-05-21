# SOURCES_ARCHITECTURE

## 1) Resumo executivo

A arquitetura atual de sources é **mista e DB-driven**: as fontes são registradas declarativamente em `app/sources/builtins.py` (plugins `SourcePlugin`), mas a execução real continua baseada em scrapers legados `app/scrapers/*.py` conectados ao runner único `run_source_for_all_wishlists`.

Estado atual (código):
- ✅ Registry declarativo em `app/sources/builtins.py`.
- ✅ Scrapers legados diretos em `app/scrapers/*` como caminho principal.
- ✅ Framework v2/unified existe (adapters/v2 + `app.scrapers.sources`), porém **não é universal por source**.
- ⚠️ Modo `dual` existe no runtime e é aplicado por flags em `source_configs.extra`, mas depende de scraper v2 disponível para a source.
- ✅ Mix real v1/v2/dual na mesma base.

---

## 2) Mapa das sources registradas

Fonte: `app/sources/builtins.py` + scrapers legados.

| Source | build_url usado | scraper/função chamada | arquivo scraper | fetch_mode | default_enabled | default_force_browser | default_browser_fallback_enabled | default_sched_minutes | default_cooldown_minutes | default_rate_limit_seconds | operational_role | Playwright direto? | HTTP direto? | fallback browser? | usa `curl_cffi`? | observações |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| mercadolivre | `ml_url` | `scrape_mercadolivre` | `app/scrapers/mercadolivre.py` | http | true | false | true | 60 | 0 | 0 | primary | indireto (via fallback) | sim | sim | **sim** | Implementa pipeline HTTP -> `curl_cffi` -> browser fallback. |
| olx | `olx_url` | `scrape_olx` | `app/scrapers/olx.py` | http | true | false | true | 60 | 0 | 0 | primary | sim (fallback/force) | sim | sim | **sim** | Health local OLX + extração `__NEXT_DATA__`. |
| chavesnamao | `chavesnamao_url` | `_scrape_chavesnamao` -> `scrape_chavesnamao` | `app/scrapers/chavesnamao.py` | browser | true | true | true | 60 | 0 | 0 | primary | sim | sim (em branch sem fallback) | sim | não visto | `fetch_mode=browser` + `force_browser` por default. |
| webmotors | `webmotors_url` | `scrape_webmotors` | `app/scrapers/webmotors.py` | browser | true | true | true | 90 | 0 | 0 | deprioritized | sim | não (prático) | sim | não visto | Browser-first com diagnóstico de bloqueio. |
| gogarage | `gogarage_url` | `scrape_gogarage` | `app/scrapers/gogarage.py` | browser | true | true | true | 60 | 0 | 0 | fragile | sim | sim | sim | não visto | Comentário histórico diz HTTP-first, mas plugin está browser-first. |
| icarros | `icarros_url` | `scrape_icarros` | `app/scrapers/icarros.py` | browser | true | true | true | 60 | 0 | 0 | fragile | sim | não (prático) | n/a | não visto | Forte parsing de ano/local/km/srcset. |
| mobiauto | `mobiauto_url` | `scrape_mobiauto` | `app/scrapers/mobiauto.py` | browser | true | true | true | 60 | 0 | 0 | fragile | sim | sim (híbrido) | sim | não visto | Usa `fetch_html_with_browser_fallback`. |
| kavak | `kavak_url` | `scrape_kavak` | `app/scrapers/kavak.py` | browser | true | true | false | 60 | 0 | 0 | experimental | sim | não | n/a | não visto | Browser-only na prática. |
| facebook_marketplace | `facebook_marketplace_url` | `scrape_facebook_marketplace` | `app/scrapers/facebook_marketplace.py` | browser | true | true | false | 60 | 180 | 0 | experimental | sim | não | n/a | não visto | `supports_manual_search=False`. |
| turboclass | `turboclass_url` | `_scrape_turboclass` -> `scrape_turboclass` | `app/scrapers/turboclass.py` | http | false | false | true | 90 | 0 | 0 | experimental | não (shim não usa browser) | sim | lógico=sim, efetivo=não | não visto | Default desabilitada; extras de ingest incremental. |

> Nota: defaults numéricos ausentes no plugin usam defaults do dataclass `SourcePlugin` (`enabled=True`, `sched=60`, `cooldown=0`, `rate_limit=0`).

---

## 3) Fluxo runtime real de execução

### 3.1 Registro
1. `app/sources/registry.py` mantém `_REGISTRY` e registra via `register_source`.
2. `app/sources/registry.py` importa `app/sources/builtins` no final para auto-registro.

### 3.2 Seed e fonte de verdade operacional
1. `ensure_source_configs` (`app/services/source_configs_service.py`) garante linha `source_configs` por source.
2. Defaults do plugin são usados **só para seed/backfill não destrutivo**.
3. Após existir linha no DB, o runtime é dirigido por `source_configs`.

### 3.3 Execução por scheduler/admin
1. `/admin runall` chama `run_source_for_all_wishlists(..., force=True)` em `app/bot/handlers_admin.py`.
2. Scheduler também usa `run_source_for_all_wishlists` (documentado no próprio serviço).
3. Runner monta grupos por URL (`plugin.build_url(query)`), cria `ScrapeContext`, resolve impl flags, escolhe dispatch v1/v2/dual e chama `scrape_ingest_match_many`.

### 3.4 Hidratação de `SourceConfig` -> `ScrapeContext`
`build_scrape_context` em `app/services/source_configs_service.py` hidrata:
- colunas diretas: `proxy_server`, `browser_fallback_enabled`, `force_browser`;
- knobs de `extra` para timeouts/delays/wait-until;
- knob `browser_block_resources` (bool opcional) para controlar bloqueio de `image/media/font` no Playwright;
- e mantém `extra` completo em `ctx.extra`.

Portanto, `source_configs.extra` **chega de fato** ao `ScrapeContext` em dois níveis:
- flatten de campos conhecidos (http/browser tunables);
- payload livre em `ctx.extra`.

### 3.5 Precedência de configuração (evidência de código)
Precedência prática:
1. **DB (`source_configs`)**: fonte de verdade em execução.
2. **Defaults do plugin**: seed inicial + backfill de chaves faltantes em `extra`.
3. **settings/env**: gates globais e operacionais (ex.: `enable_playwright`, allowlist Playwright, feature flags do adapter novo).
4. **`extra`**: parte do DB; não é camada separada de precedência, é conteúdo da própria config persistida.

---

## 4) Status do modo v1/v2/dual

### Evidências
- Leitura de flag: `read_source_impl_flags(extra)` em `app/sources/flags.py` (`impl` aceita `v1|v2|dual`).
- Aplicação no runner principal: `build_scrape_dispatch` em `app/services/source_execution_helpers.py`.
- Execução dual: `execute_dual_run` em `app/sources/dual_run.py`.
- Também há dual path no `search_service` usando `app/scrapers/dual_run.py`.

### Classificação
- `impl=dual` funcional no runtime principal: **partial** (funciona quando existe scraper v2 para a source; senão cai em v1).
- Onde é lido: **real_implemented** (`app/sources/flags.py`).
- Onde é aplicado: **real_implemented** (`build_scrape_dispatch` + `execute_dual_run`).
- `/admin runall <source> --impl dual`: **not_found** no parser atual de `/admin runall` (argumentos tratados só como nomes de source).
- `execute_dual_run`: **real_implemented** em `app/sources/dual_run.py`.
- Sources com dual de fato: **partial** (somente as com scraper v2 registrado em `app.scrapers.sources`).
- `docs/V1_TO_V2_MIGRATION.md`: mistura de plano/histórico; não representa integralmente runtime vigente sem checagem no código.

---

## 5) Matriz preliminar de divergência docs x código

| item documentado | onde aparece | evidência no código | status | risco | recomendação |
|---|---|---|---|---|---|
| `curl_cffi` no unified fetcher v2 | `docs/V1_TO_V2_MIGRATION.md` | `app/scrapers/scraper_base/fetcher.py` não usa `curl_cffi` | divergente | médio | marcar explicitamente como gap real no roadmap. |
| `curl_cffi` ativo no Mercado Livre | migration doc | `app/scrapers/mercadolivre.py` usa `curl_cffi` em `_fetch_html_ml` | alinhado | baixo | manter doc, referenciar implementação atual. |
| `curl_cffi` ativo na OLX | migration doc | `app/scrapers/olx.py` importa/usa `curl_cffi` no fetch híbrido | alinhado | baixo | manter doc. |
| POLYCARD no Mercado Livre | migration doc | `_parse_polycard_items` + merge em `scrape_mercadolivre` | alinhado | baixo | manter doc. |
| filtro anti-peças ML | migration doc | `_vehicle_relevance_score` usado em parse | alinhado | baixo | manter doc. |
| tracking URL patrocinada ML | migration doc | `_is_tracking_url` + `_extract_tracking_destination` + resolução | alinhado | baixo | manter doc. |
| fallback VIP price ML | migration doc | `_extract_price_from_vip_html` + fallback final em scrape | alinhado | baixo | manter doc. |
| `__NEXT_DATA__` OLX | migration/guide | `_extract_next_data_json` + parser OLX | alinhado | baixo | manter doc. |
| health tracking da OLX | guide | arquivo health + funções `olx_health_*` | alinhado | baixo | manter doc operacional. |
| ano/local/km/srcset em iCarros | guide/migration | funções dedicadas no scraper | alinhado | baixo | manter doc. |
| `block_resources` configurável por source | migration implícito | `browser_block_resources` lido de `source_configs.extra` e aplicado no unified + pool | alinhado | baixo | default econômico segue `true`; defaults `false` para webmotors/icarros/mobiauto/facebook_marketplace preservam anti-bot/challenge assets. |
| warmup Webmotors | guide | serviço `browser_warmup_service` + pool `warmup` + comando admin | alinhado | baixo | manter e citar fluxo correto. |
| comando `/admin runall <source> --impl dual` | `V1_TO_V2_MIGRATION.md` | `_admin_runall` não parseia flag `--impl` | divergente | alto (operação enganosa) | corrigir doc primeiro; depois decidir implementação real. |

---

## 6) Recomendações para próxima tarefa

- **P0 — corrigir documentação operacional defasada**: principalmente remover/qualificar instruções de `--impl dual` no `runall`, e explicitar escopo real do dual por source.
- **P1 — inventariar cobertura v2 por source** (arquivo único de matriz v2 disponível/ausente), porque dual hoje depende disso.
- **P2 — adicionar validação automatizada de coerência docs/runtime** (ex.: teste que garante comandos documentados existentes e flags efetivas).
- **P3 — consolidar docs v1/v2**: separar claramente “estado implementado” vs “plano proposto”.

---

## Arquivos obrigatórios solicitados: verificação de existência

Todos os caminhos obrigatórios informados na tarefa **existem** neste snapshot do repositório, incluindo:
- `app/scrapers/chavesnamao.py`, `webmotors.py`, `gogarage.py`, `icarros.py`, `mobiauto.py`, `kavak.py`, `turboclass.py`, `facebook_marketplace.py`;
- `app/scrapers/scraper_base/fetcher.py`;
- `app/services/browser_fetcher.py`, `playwright_pool.py`, `browser_warmup_service.py`.
