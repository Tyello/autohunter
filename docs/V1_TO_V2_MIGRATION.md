# V1 → V2: Status real de migração

## 1. Resumo executivo

- O runtime atual é **misto**: o registry de sources é declarativo (`app/sources/builtins.py`), mas o caminho principal ainda usa scrapers legados ativos (`app/scrapers/*.py`) por padrão.
- O framework v2/unified existe e está ativo no código (`app.scrapers.sources` + adapters v2), mas o uso por source depende de `source_configs.extra.impl` (`v1|v2|dual`).
- `impl=dual` existe e roda comparação real quando há scraper v2 registrado para a source; sem v2 registrado, o dispatch cai no caminho v1.
- Parte dos gaps históricos já está implementada no caminho ativo (especialmente Mercado Livre, OLX e iCarros).
- Este documento separa explicitamente:
  - o que já está implementado no caminho ativo;
  - o que ainda está pendente no caminho v2/unified;
  - e gaps de runtime/comando/configuração (não-parser).

## 2. Legenda de status

- `implemented_active`: já existe no scraper ativo usado pelo registry principal.
- `implemented_v2`: já existe no scraper v2.
- `implemented_both`: existe no ativo e no v2.
- `pending_v2`: existe no ativo, mas ainda falta no caminho v2/unified.
- `pending_active`: falta no caminho ativo.
- `runtime_gap`: não é parser/scraper; é diferença de comando, flag, dispatch ou config.
- `doc_only`: estava documentado, mas não há evidência de implementação no código.
- `not_applicable`: não faz sentido para aquela source.
- `needs_validation`: há indício estático, mas precisa validação por execução real.

## 3. Matriz geral dos gaps

| ID | Tema | Source(s) | Status | Caminho ativo | Caminho v2/unified | Evidência no código | Risco | Próxima ação |
|---|---|---|---|---|---|---|---|---|
| FND-01 | `curl_cffi` no `unified_fetch` | Fundação | `pending_v2` | ML/OLX já têm `curl_cffi` no scraper legado | `app/scrapers/scraper_base/fetcher.py` não usa `curl_cffi` | fetcher unificado só faz HTTP->browser; ML/OLX ativos fazem etapa intermediária | Médio | Decidir política única (manter por-source vs portar para unified). |
| FND-02 | `block_resources` configurável por source | Fundação | `runtime_gap` | Sem knob por source no caminho unificado | `unified_fetch` fixa `block_resources=True` | ausência de leitura de `ctx.extra` para esse controle | Médio | Criar knob explícito por source no contexto. |
| FND-03 | `impl=v1|v2|dual` via `source_configs.extra` | Fundação | `implemented_both` | Flags lidas e aplicadas no runner principal | idem | `read_source_impl_flags` + `build_scrape_dispatch` | Baixo | Manter e documentar precedência DB/config. |
| FND-04 | `/admin runall <source> --impl dual` | Fundação | `runtime_gap` | `/admin runall` aceita só nomes de source | sem parser de flag `--impl` | `_admin_runall` não parseia `--impl`; operação real é via `source_configs.extra.impl` | Alto | Remover instrução enganosa; trocar por fluxo de config persistida. |
| FND-05 | Cobertura real de scrapers v2 registrados | Fundação | `implemented_both` | V1 ativo para todas registradas em builtins | v2 registrado para: mercadolivre, olx, icarros, webmotors, chavesnamao, kavak, gogarage, mobiauto, turboclass | `app/scrapers/sources/__init__.py` auto-registra essas sources; Facebook Marketplace não aparece | Médio | Publicar inventário automático de cobertura v2 por source. |
| FND-06 | Hidratação de `source_configs.extra` em `ScrapeContext` | Fundação | `implemented_both` | Contexto recebe knobs conhecidos + `ctx.extra` | idem | `build_scrape_context` com flatten + payload extra | Baixo | Manter; reforçar em docs operacionais. |
| ML-01 | `curl_cffi` | Mercado Livre | `implemented_active` | `_fetch_html_ml` usa HTTP -> `curl_cffi` -> browser fallback | sem evidência equivalente na v2/unified | scraper legado contém import e fallback por camadas | Médio | Trazer para v2/unified ou manter exceção documentada. |
| ML-02 | POLYCARD extraction | Mercado Livre | `implemented_active` | `_parse_polycard_items` implementado | não confirmado no v2 | parser regex de `"polycard"` ativo | Médio | Portar para v2 se paridade exigir. |
| ML-03 | merge POLYCARD + BeautifulSoup | Mercado Livre | `implemented_active` | merge de fontes de item no fluxo final | não confirmado no v2 | scrape legado combina resultados e completa campos faltantes | Médio | Documentar como requisito de paridade. |
| ML-04 | filtro anti-peças (`_vehicle_relevance_score`) | Mercado Livre | `implemented_active` | score aplicado nos itens | não confirmado no v2 | `_PART_KEYWORDS` e threshold ativos | Médio | Portar para v2 para evitar ruído de peças. |
| ML-05 | tracking URLs patrocinadas | Mercado Livre | `implemented_active` | resolve `click*/brand_ads` para destino final | não confirmado no v2 | `_is_tracking_url` + `_extract_tracking_destination` + canonical fallback | Médio | Portar pipeline completo para v2. |
| ML-06 | `_unescape_ml` | Mercado Livre | `implemented_active` | helper dedicado ativo | não confirmado no v2 | `_unescape_ml` usado em URL/título/localização | Médio | Reusar helper no parser v2. |
| ML-07 | fallback de preço via página VIP | Mercado Livre | `implemented_active` | `_extract_price_from_vip_html` usado como fallback final | não confirmado no v2 | fetch detalhe e extração de preço | Baixo | Manter no ativo; avaliar custo/benefício no v2. |
| ML-08 | canonicalização de URLs | Mercado Livre | `implemented_active` | `_normalize_ml_url`/`_canonical_url_from_external_id` ativos | não confirmado no v2 | normalização + reconstrução por external_id | Médio | Portar canonicalização para v2. |
| ML-09 | guardrail vertical veículos | Mercado Livre | `implemented_active` | bloqueia saída do vertical de veículos | não confirmado no v2 | `_left_vehicle_vertical` + hosts/prefixos permitidos | Médio | Tornar regra explícita no v2. |
| OLX-01 | `curl_cffi` | OLX | `implemented_active` | fetch híbrido usa `curl_cffi` | não confirmado no v2/unified | import e tentativa prioritária no scraper ativo | Médio | Definir convergência com unified_fetch. |
| OLX-02 | `__NEXT_DATA__` | OLX | `implemented_active` | `_extract_next_data_json` com fallback regex | não confirmado no v2 | parse Next.js ativo | Baixo | Preservar no caminho v2. |
| OLX-03 | fallback HTML | OLX | `implemented_active` | `_fallback_parse_from_cards` | não confirmado no v2 | fallback acionado sem `__NEXT_DATA__` | Baixo | Garantir fallback equivalente no v2. |
| OLX-04 | health tracking file-backed | OLX | `implemented_active` | usa JSON local (`olx.json`) com lock | not_applicable | funções `olx_health_*` | Baixo | Manter; revisar apenas se migrar observabilidade. |
| OLX-05 | runtime force-browser | OLX | `implemented_active` | `olx_force_browser` + janela runtime | not_applicable | `_runtime_force_browser_active` e configuração | Baixo | Manter e documentar operação. |
| OLX-06 | browser fallback/warmup | OLX | `implemented_active` | fallback browser implementado; warmup não é requisito central OLX | `needs_validation` | fallback ativo via config Playwright | Baixo | Validar benefício real de warmup dedicado. |
| OLX-07 | dedupe interno | OLX | `implemented_active` | dedupe por URL/external_id no fluxo do scraper | needs_validation | evidência de redução de duplicatas no parser | Baixo | Validar via run real e dual report. |
| ICA-01 | extração de ano pela URL | iCarros | `implemented_active` | `_extract_year_from_url` | não confirmado no v2 | parser legado usa ano em enrich/fallback | Baixo | Reproduzir no v2. |
| ICA-02 | cidade/UF pela URL | iCarros | `implemented_active` | `_extract_location_from_url`/`_slug_to_city_uf` | não confirmado no v2 | localização inferida do path canônico | Baixo | Reproduzir no v2. |
| ICA-03 | extração robusta de km | iCarros | `implemented_active` | regex dedicada `_extract_km` | não confirmado no v2 | ignora falsos positivos (ex.: distância) | Baixo | Reproduzir no v2. |
| ICA-04 | `srcset` picking | iCarros | `implemented_active` | `_pick_from_srcset` + múltiplos seletores | não confirmado no v2 | thumbnail melhor resolução | Baixo | Reproduzir no v2. |
| ICA-05 | upgrade/ranking de thumbnail | iCarros | `implemented_active` | heurísticas de upgrade de imagem | não confirmado no v2 | função de upgrade dedicada | Baixo | Reproduzir no v2. |
| ICA-06 | fallback detail/listing | iCarros | `implemented_active` | resolve URL real e enriquece detalhe | não confirmado no v2 | `_resolve_listing_url_from_fallback_page` + `_detail_enrich` | Médio | Reproduzir no v2 com limite de custo. |
| MOB-01 | `srcset`/thumbnail robusto | Mobiauto | `implemented_active` | parser tenta `srcset` + enrich em detalhe | needs_validation | expansão de srcset e backfill de thumb | Baixo | Validar taxa de thumbnail em produção. |
| MOB-02 | HTTP/browser/híbrido | Mobiauto | `implemented_active` | usa `fetch_html_with_browser_fallback` (híbrido) com `force_browser` possível | needs_validation | caminho híbrido estático confirmado | Baixo | Medir frequência real de fallback browser. |
| WEB-01 | diagnóstico de bloqueio | Webmotors | `implemented_active` | documentação e serviços indicam detecção de bloqueio/challenge | needs_validation | integração com serviços de diagnóstico | Médio | Validar cobertura atual em execuções recentes. |
| WEB-02 | PerimeterX/challenge detection | Webmotors | `implemented_active` | detecção existe em serviços auxiliares | needs_validation | referências em documentação/serviços operacionais | Médio | Correlacionar detecção com ações automáticas. |
| WEB-03 | warmup real vs recomendado | Webmotors | `needs_validation` | warmup existe, eficácia variável | not_applicable | `/admin warmup` existe; eficácia depende de bloqueio atual | Médio | Medir sucesso pós-warmup por janela de tempo. |
| WEB-04 | browser-first | Webmotors | `implemented_active` | plugin está `fetch_mode=browser` + `force_browser=True` | implemented_v2 | mesma diretriz no plugin/arquitetura | Baixo | Manter. |
| WEB-05 | captura HTML/XHR | Webmotors | `needs_validation` | há indicação de fluxo com XHR no diagnóstico, não consolidado neste doc como garantido | needs_validation | depende de execução real da source | Médio | Validar com logs controlados. |
| GOG-01 | browser-first real | GoGarage | `implemented_active` | plugin é browser-first | implemented_v2 | `fetch_mode=browser` e `force_browser=True` | Baixo | Corrigir comentário histórico para evitar confusão. |
| GOG-02 | dependência de seletores/cards | GoGarage | `needs_validation` | scraper depende de estrutura HTML renderizada | needs_validation | natureza do parser por seletores | Médio | Validar estabilidade de seletores por amostra. |
| GOG-03 | divergência comentário histórico vs config | GoGarage | `runtime_gap` | comentário antigo menciona HTTP-first | config atual é browser-first | divergência em comentários/docs vs plugin real | Baixo | Priorizar código como fonte de verdade e ajustar docs. |
| KAV-01 | browser-only/browser-first real | Kavak | `implemented_active` | browser-first com `force_browser` e sem fallback padrão | implemented_v2 | plugin + scraper ativo confirmam perfil browser | Baixo | Manter experimental e monitorar custo. |
| KAV-02 | status experimental | Kavak | `implemented_active` | `operational_role=experimental` | implemented_v2 | default extra do plugin | Baixo | Manter fora de metas de piloto. |
| TUR-01 | HTTP/feed | TurboClass | `implemented_active` | scraper HTTP/feed ativo | implemented_v2 | plugin `fetch_mode=http` + função dedicada | Baixo | Manter desabilitada por default até validação. |
| TUR-02 | ingest incremental | TurboClass | `needs_validation` | existe menção de extras operacionais no plugin/docs | needs_validation | requer validação por execução/DB | Médio | Validar com run de amostra e métricas de duplicidade. |
| TUR-03 | experimental/desabilitado por default | TurboClass | `implemented_active` | `default_enabled=false` | implemented_v2 | plugin builtins | Baixo | Manter status experimental. |
| TUR-04 | presença no v2 registry | TurboClass | `implemented_v2` | n/a | v2 registrado | `app/scrapers/sources/__init__.py` registra `TurboClassScraper` | Baixo | Nenhuma imediata. |
| FBM-01 | no registry principal | Facebook Marketplace | `implemented_active` | está em builtins e runner principal | pending_v2 | não aparece no registry v2 auto-registrado | Médio | Definir se haverá v2 dedicado ou manter fora da migração curta. |
| FBM-02 | fora do piloto | Facebook Marketplace | `implemented_active` | `operational_role=experimental`; `supports_manual_search=False` | not_applicable | plugin e docs operacionais | Baixo | Manter explicitamente fora do piloto. |
| FBM-03 | depende de sessão manual | Facebook Marketplace | `implemented_active` | scraper depende de sessão/browser state | not_applicable | natureza da source e operação admin | Médio | Manter como experimental com playbook separado. |

## 4. Seções por source

## Mercado Livre

### Status atual
Caminho ativo é robusto e contém mecanismos anti-bloqueio/anti-ruído que não devem ser tratados como “gap total”.

### Já implementado no caminho ativo
- `curl_cffi` intermediário.
- POLYCARD + merge com parser HTML.
- filtro anti-peças por score.
- resolução de tracking patrocinado.
- `_unescape_ml`.
- fallback de preço via VIP.
- canonicalização de URL/external_id.
- guardrail de vertical veículos.

### Pendente no v2/unified
- Consolidar equivalentes desses mecanismos no scraper v2/unified.

### Próxima ação recomendada
Priorizar matriz de paridade v1→v2 para ML antes de qualquer flip para `impl=v2`.

## OLX

### Status atual
Caminho ativo já combina `curl_cffi`, parser Next.js, fallback HTML e controles operacionais de saúde.

### Já implementado no caminho ativo
- `curl_cffi`.
- `__NEXT_DATA__`.
- fallback HTML.
- health file-backed.
- runtime force-browser.
- browser fallback.

### Pendente no v2/unified
- Garantir paridade de fetch híbrido e fallback de parsing no caminho v2/unified.

### Próxima ação recomendada
Executar dual-run controlado para medir divergência de itens e campos.

## Chaves na Mão

### Status atual
Browser-first por configuração de plugin; sem gaps específicos críticos mapeados neste ciclo.

### Já implementado no caminho ativo
- Execução browser-first com fallback habilitado por padrão.

### Pendente no v2/unified
- Validar paridade de campo a campo no scraper v2 antes de migração.

### Próxima ação recomendada
Rodar checklist curto de paridade em consultas representativas.

## Webmotors

### Status atual
Browser-first e com instrumentação de bloqueio/challenge; eficácia real depende de warmup e contexto de execução.

### Já implementado no caminho ativo
- Browser-first.
- diagnóstico de bloqueio/challenge (inclui PerimeterX no ecossistema operacional).
- warmup administrativo disponível.

### Pendente no v2/unified
- Evidência objetiva de paridade funcional em cenário de bloqueio real.

### Próxima ação recomendada
Validar eficácia do warmup com métrica de sucesso por janela (ex.: 6h/24h).

## GoGarage

### Status atual
Configuração atual é browser-first; documentação histórica que fala HTTP-first está defasada.

### Já implementado no caminho ativo
- Browser-first real no plugin/execução.

### Pendente no v2/unified
- Validar robustez de parser baseado em seletores/cards.

### Próxima ação recomendada
Ajustar documentação secundária para remover ambiguidade de modo de fetch.

## iCarros

### Status atual
Scraper ativo já possui parsing/enriquecimento avançado (ano/local/km/thumb/detail fallback).

### Já implementado no caminho ativo
- ano/cidade/UF via URL.
- km robusto.
- `srcset` picking.
- upgrade de thumbnail.
- resolução de listing/detail fallback.

### Pendente no v2/unified
- Reproduzir as heurísticas de enriquecimento no v2 com custo controlado.

### Próxima ação recomendada
Medir paridade de qualidade (thumb/location/title) em dual-run.

## Mobiauto

### Status atual
Há evidência de caminho híbrido HTTP/browser e tratamento de thumbnail/srcset no scraper ativo.

### Já implementado no caminho ativo
- fetch com browser fallback.
- extração de thumbnail com expansão de srcset.
- enrich pontual em detalhe para preencher lacunas.

### Pendente no v2/unified
- Confirmar paridade real de thumbnail e estabilidade em bloqueios.

### Próxima ação recomendada
Registrar métricas por run (thumb rate, fallback rate).

## Kavak

### Status atual
Source experimental, browser-first na prática.

### Já implementado no caminho ativo
- configuração e execução browser-first.
- classificação experimental.

### Pendente no v2/unified
- Sem gap crítico confirmado além de validação contínua.

### Próxima ação recomendada
Manter fora de metas principais de migração até estabilização.

## TurboClass

### Status atual
Source HTTP/feed, experimental e desabilitada por default.

### Já implementado no caminho ativo
- caminho HTTP/feed.
- presença no v2 registry.
- status experimental (default disabled).

### Pendente no v2/unified
- validar ingest incremental com evidência operacional.

### Próxima ação recomendada
Executar validação controlada antes de aumentar prioridade.

## Facebook Marketplace

### Status atual
Está no registry principal v1; não deve ser tratada como source de piloto padrão.

### Já implementado no caminho ativo
- fonte registrada e executável no runner principal.
- perfil experimental e dependência operacional de sessão manual/browser state.

### Pendente no v2/unified
- não há scraper v2 auto-registrado para Facebook Marketplace no registry atual.

### Próxima ação recomendada
Manter fora do escopo de migração curta v1→v2 até decidir estratégia específica.

## 5. Correção de instruções enganosas

### Comando enganoso removido
`/admin runall <source> --impl dual` **não é suportado** no parser atual de `/admin runall`.

### Caminho correto hoje
- Alterar `source_configs.extra.impl` para `v1`, `v2` ou `dual` via DB/admin tooling existente para `source_configs`.
- Executar `/admin runall <source>` sem flag `--impl` para forçar run com a configuração persistida.

### Observação
Se for desejável trocar `impl` por comando Telegram, isso precisa de tarefa específica para criar comando admin seguro e auditável.

## 6. Próximas tarefas recomendadas (baseadas em evidência)

- **P0** — corrigir documentação e comandos enganosos de dual (concluído neste documento; propagar para guias correlatos).
- **P1** — implementar `browser_block_resources` configurável por source no caminho unified.
- **P2** — decidir se `curl_cffi` deve entrar no `unified_fetch` (estratégia global) ou ficar como otimização por source.
- **P3** — inventariar automaticamente cobertura v2 por source e publicar artefato de controle (doc/check).
- **P4** — melhorar warmup Webmotors **se** validação operacional confirmar gap real recorrente.
- **P5** — criar comando admin seguro para alterar `impl` por source (opcional, se houver demanda operacional real).

## 7. Arquivos analisados nesta auditoria

- `docs/SOURCES_ARCHITECTURE.md`
- `docs/V1_TO_V2_MIGRATION.md`
- `docs/SOURCES_GUIDE.md`
- `app/sources/builtins.py`
- `app/sources/types.py`
- `app/sources/flags.py`
- `app/sources/dual_run.py`
- `app/services/source_execution_helpers.py`
- `app/services/source_execution_service.py`
- `app/services/source_configs_service.py`
- `app/scrapers/scraper_base/fetcher.py`
- `app/scrapers/sources/__init__.py`
- `app/scrapers/mercadolivre.py`
- `app/scrapers/olx.py`
- `app/scrapers/icarros.py`
- `app/scrapers/mobiauto.py`
- `app/scrapers/chavesnamao.py`
- `app/scrapers/webmotors.py`
- `app/scrapers/gogarage.py`
- `app/scrapers/kavak.py`
- `app/scrapers/turboclass.py`
- `app/scrapers/facebook_marketplace.py`

Todos os arquivos obrigatórios listados acima existem no snapshot atual.
