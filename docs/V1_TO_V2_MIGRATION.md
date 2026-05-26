# V1 → V2: Status real de migração

## Mercado Livre — regra obrigatória para novas tarefas

Novas tarefas V1→V2 para Mercado Livre devem obedecer a matriz em `docs/MERCADOLIVRE_STRATEGY_MATRIX.md`.

## 1. Resumo executivo

- O runtime atual é **misto**: registry declarativo em `app/sources/builtins.py`, com scrapers legados `app/scrapers/*.py` ainda como caminho principal em várias sources.
- O framework v2/unified existe e está ativo, mas a seleção por source depende de `source_configs.extra.impl` (`v1|v2|dual`) e cobertura v2 disponível.
- `impl=dual` é configuração persistida por source; não existe flag `--impl dual` no `/admin runall`.
- A trilha V1→V2 é **técnica de estabilização** e **não** substitui as prioridades de produto (wishlist/filtros).
- Próxima etapa **não** é flip geral para `v2`: é inventário automático + dual-run controlado + paridade por source principal.
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
- `deprioritized`: implementado, porém fora do caminho crítico operacional no momento.
- `blocked_by_antibot`: bloqueio operacional confirmado por camada anti-bot/challenge.
- `operational_decision`: status definido por decisão operacional explícita.

## 3. Matriz geral dos gaps

| ID | Tema | Source(s) | Status | Caminho ativo | Caminho v2/unified | Evidência no código | Risco | Próxima ação |
|---|---|---|---|---|---|---|---|---|
| FND-01 | `curl_cffi` no `unified_fetch` | Fundação | `pending_v2` | ML/OLX já têm `curl_cffi` no scraper legado | `app/scrapers/scraper_base/fetcher.py` não usa `curl_cffi` | fetcher unificado só faz HTTP->browser; ML/OLX ativos fazem etapa intermediária | Médio | Decidir política após dual-run/medição; não globalizar agora. |
| FND-02 | `block_resources` configurável por source | Fundação | `implemented_both` | Knob por source via `source_configs.extra.browser_block_resources` no contexto | unified e pool Playwright respeitam valor efetivo | `build_scrape_context` hidrata flag + fetch/browser pool usam `block_resources` por source/contexto | Baixo | Manter defaults econômicos e exceções anti-bot documentadas. |
| FND-03 | `impl=v1|v2|dual` via `source_configs.extra` | Fundação | `implemented_both` | Flags lidas e aplicadas no runner principal | idem | `read_source_impl_flags` + `build_scrape_dispatch` | Baixo | Manter e documentar precedência DB/config. |
| FND-04 | `/admin runall <source> --impl dual` | Fundação | `runtime_gap` | `/admin runall` aceita só nomes de source | sem parser de flag `--impl` | `_admin_runall` não parseia `--impl`; operação real é via `source_configs.extra.impl` | Alto | Remover instrução enganosa; trocar por fluxo de config persistida. |
| FND-05 | Cobertura real de scrapers v2 registrados | Fundação | `implemented_both` | V1 ativo para todas registradas em builtins | v2 registrado para: mercadolivre, olx, icarros, webmotors, chavesnamao, kavak, gogarage, mobiauto, turboclass | `app/scrapers/sources/__init__.py` auto-registra essas sources; Facebook Marketplace não aparece | Médio | **Próxima ação principal:** gerar inventário automático v1/v2 por source. |
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
| WEB-01 | diagnóstico de bloqueio | Webmotors | `implemented_both` | diagnóstico admin de bloqueio/challenge implementado e em uso | implemented_v2 | serviços de diagnóstico + classificação WM_DIAG em bucket `BLOCKED` | Baixo | Manter como fixture de blocked/challenge e execução manual/admin. |
| WEB-02 | PerimeterX/challenge detection | Webmotors | `implemented_both` | detecção de challenge PerimeterX implementada e validada | implemented_v2 | resultado operacional consolidado: challenge com HTTP 200 | Baixo | Nenhuma ação imediata no roadmap V1→V2. |
| WEB-03 | warmup (básico/comportamental) | Webmotors | `operational_decision` | warmup implementado e testado; não removeu challenge | not_applicable | browser direto + assets liberados + warmup básico/comportamental testados | Médio | Não priorizar novas iterações agora; manter diagnóstico/manual. |
| WEB-04 | browser-first | Webmotors | `implemented_active` | plugin está `fetch_mode=browser` + `force_browser=True` | implemented_v2 | mesma diretriz no plugin/arquitetura | Baixo | Manter. |
| WEB-05 | status operacional | Webmotors | `deprioritized` | source implementada com execução manual/admin disponível | not_applicable | `operational_role=deprioritized` + `default_enabled=false` no seed novo | Baixo | Fora do caminho crítico da migração V1→V2. |
| GOG-01 | browser-first real | GoGarage | `implemented_active` | plugin é browser-first | implemented_v2 | `fetch_mode=browser` e `force_browser=True` | Baixo | Corrigir comentário histórico para evitar confusão. |
| GOG-02 | dependência de seletores/cards | GoGarage | `needs_validation` | scraper depende de estrutura HTML renderizada | needs_validation | natureza do parser por seletores | Médio | Validar estabilidade de seletores por amostra. |
| GOG-03 | divergência comentário histórico vs config | GoGarage | `runtime_gap` | comentário antigo menciona HTTP-first | config atual é browser-first | divergência em comentários/docs vs plugin real | Baixo | Priorizar código como fonte de verdade e ajustar docs. |
| KAV-01 | browser-only/browser-first real | Kavak | `implemented_active` | browser-first com `force_browser` e sem fallback padrão | implemented_v2 | plugin + scraper ativo confirmam perfil browser | Baixo | Manter experimental e monitorar custo. |
| KAV-02 | status experimental | Kavak | `implemented_active` | `operational_role=experimental` | implemented_v2 | default extra do plugin | Baixo | Manter fora de metas de piloto. |
| TUR-01 | HTTP/feed | TurboClass | `implemented_active` | scraper HTTP/feed ativo | implemented_v2 | plugin `fetch_mode=http` + função dedicada | Baixo | Manter habilitada por default com validação controlada de ingest incremental e duplicidade. |
| TUR-02 | ingest incremental | TurboClass | `needs_validation` | existe menção de extras operacionais no plugin/docs | needs_validation | requer validação por execução/DB | Médio | Validar com run de amostra e métricas de duplicidade. |
| TUR-03 | experimental/habilitado por default | TurboClass | `implemented_active` | `default_enabled=true` | implemented_v2 | plugin builtins | Baixo | Manter status experimental. |
| TUR-04 | presença no v2 registry | TurboClass | `implemented_v2` | n/a | v2 registrado | `app/scrapers/sources/__init__.py` registra `TurboClassScraper` | Baixo | Nenhuma imediata. |
| FBM-01 | no registry principal | Facebook Marketplace | `implemented_active` | está em builtins e runner principal | pending_v2 | não aparece no registry v2 auto-registrado | Médio | Definir se haverá v2 dedicado ou manter fora da migração curta. |
| FBM-02 | fora do piloto | Facebook Marketplace | `implemented_active` | `operational_role=experimental`; `supports_manual_search=False` | not_applicable | plugin e docs operacionais | Baixo | Manter explicitamente fora do piloto. |
| FBM-03 | depende de sessão manual | Facebook Marketplace | `implemented_active` | scraper depende de sessão/browser state | not_applicable | natureza da source e operação admin | Médio | Manter como experimental com playbook separado. |

## 4. Seções por source

## Mercado Livre

### Status atual
Caminho ativo é robusto e contém mecanismos anti-bloqueio/anti-ruído que não devem ser tratados como “gap total”.

### Atualização recente (dual-run V2 HTML)
- Em dual-run recente, V2 já alcançou HTML por `browser_fallback` com `raw_items_found > 0`, indicando evolução do fetch.
- O gap principal estava na normalização: `parse_listing` retornava `None` para cards HTML sem título visível.
- O V2 passou a reaproveitar `_parse_polycard_items` (caminho validado no V1) no branch HTML, convertendo os itens POLYCARD para o formato raw do V2 e aplicando dedupe por `id`.
- Também foi adicionado fallback defensivo de título (img/link/slug de URL) para evitar descarte total quando o card não possui `h2`/`title`.
- Próximo gate operacional: retomar paridade dual-run com V1 e V2 > 0 quando não houver captcha temporário no ML.

### Atualização operacional (2026-05-24)
- Validação de paridade V1/V2 atingida em dual-run:
  - `v1_count=30`
  - `v2_count=15`
  - `matched_count=15`
  - `only_v1_count=0`
  - `only_v2_count=0`
  - `v2_metrics.fetch_method=browser_fallback`
  - `v2_metrics.raw_items_found=15`
  - `v2_metrics.items_parsed=15`
  - `v2_metrics.items_valid=15`
  - `parse_errors=0`
- Interpretação obrigatória:
  - V2 está funcional, não bloqueado e validou 15 itens;
  - diferença `v1_count` vs `v2_count` parece contagem bruta/duplicidade no V1 (não ausência de IDs no V2);
  - `field_diffs` observados de `year` (vazio no V1, preenchido no V2) representam enriquecimento positivo, não regressão.
- Próxima etapa recomendada:
  - explicitar paridade de únicos e duplicidade no relatório (`raw_count` vs `unique_count`);
  - classificar `field_diffs` em bloqueantes vs enriquecimento para evitar falso WARN por ruído de contagem.
- Gate de flip permanece inalterado:
  - só considerar `impl=v2` após `v1_count > 0` e `v2_count > 0` na mesma janela limpa.
- Diretriz para futuros agentes:
  - não reabrir PR de parser/fetch V2 com base apenas nesse resultado de 2026-05-24.

### Atualização operacional (2026-05-26)
- Novo dual-run registrou:
  - `v1_count=0`
  - `v1_error=FetchBlocked reason=ml_shell_without_results`
  - `v2_count=14`
  - `v2_unique_count=14`
  - `v2_blocked=false`
  - `v2_metrics.fetch_method=browser_fallback`
  - `v2_metrics.raw_items_found=14`
  - `v2_metrics.items_parsed=14`
  - `v2_metrics.items_valid=14`
  - `parse_errors=0`
- Interpretação obrigatória:
  - V2 permaneceu funcional no cenário observado;
  - o FAIL do relatório foi provocado pelo V1 em shell (`ml_shell_without_results`);
  - `V1 shell` não constitui evidência contra o V2;
  - V2 com 14 itens válidos é evidência positiva operacional.
- Diretriz operacional imediata:
  - não abrir nova PR de parser/fetch V2 com base isolada nesse resultado;
  - não rodar `strategy_probe` completo em sequência;
  - preferir single dual-run após cooldown.

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

### Gates para decisão de flip (Mercado Livre)
- Gate preferencial (permanece obrigatório como primeira escolha):
  - `v1_count > 0` e `v2_count > 0` na mesma janela limpa.
- Gate alternativo de validação (quando V1 está instável por shell):
  - aplicar **somente** se V1 falhar com `ml_shell_without_results` e V2 retornar itens válidos de forma repetida;
  - exigir simultaneamente:
    1. `v2_blocked=false`;
    2. `v2_count > 0`;
    3. `raw_items_found == items_valid` **ou** `items_valid > 0` sem `parse_errors`;
    4. IDs do V2 compatíveis com o último baseline bom conhecido;
    5. ausência de `blocking_field_diffs` conhecidos;
    6. revisão manual obrigatória para qualquer decisão de flip.
- Regra final:
  - mesmo no gate alternativo, a decisão de flip não é automática e continua dependente de revisão manual.

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
Source tecnicamente implementada, com diagnóstico admin funcional e execução manual disponível, mas **bloqueada operacionalmente** por challenge de anti-bot (PerimeterX/fingerprint).

### Evidência consolidada
- testado browser direto;
- testado `browser_block_resources=false`;
- testado warmup básico;
- testado warmup comportamental;
- testado `curl_cffi` experimental;
- resultado recorrente: HTTP 200 com challenge (`provider=perimeterx`, `Access to this page has been denied`, `Pressione e segure`).

### Decisão operacional
- `operational_role=deprioritized`;
- `default_enabled=false` para seed novo;
- não entra como falha crítica global de saúde;
- não priorizar Webmotors no caminho V1→V2 agora.

### Papel da Webmotors nesta trilha
- usar como fixture/diagnóstico de `blocked/challenge`;
- não usar como critério de sucesso da migração v2;
- manter execução manual e diagnóstico/admin para observabilidade operacional.

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
Source HTTP/feed, experimental e habilitada por default.

### Já implementado no caminho ativo
- caminho HTTP/feed.
- presença no v2 registry.
- status experimental (default enabled).

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
- Alterar `source_configs.extra.impl` diretamente no banco, com cuidado operacional, por SQL controlado/script administrativo/migration pontual.
- Hoje não há comando Telegram/admin seguro para alterar `source_configs.extra.impl`.
- Depois da alteração persistida, executar `/admin runall <source>` sem flag `--impl`.

### Observação
Se for desejável trocar `impl` por comando Telegram, isso precisa de tarefa específica para criar comando admin seguro e auditável.

## 6. Próximas tarefas recomendadas (ordem sugerida)

- **P0 — Alinhar documentação V1→V2 ao estado real.**
  - Status: concluído nesta PR de documentação.

- **P1 — Criar inventário automático de cobertura V1/V2.**
  - Status: concluído com `scripts/source_v2_inventory.py`.
  - Comandos:
    - `python scripts/source_v2_inventory.py --no-db`
    - `python scripts/source_v2_inventory.py --format json --no-db`
  - Matriz gerada: `source | has_v1 | has_v2 | supports_dual | current_impl | operational_role | default_enabled`.
  - O inventário é read-only: não executa scrapers, não usa browser e não altera runtime/DB.
  - Esta saída é a base para o **P2 dual-run controlado**.

- **P2 — Criar/rodar dual-run controlado nas sources principais.**
  - Status: iniciado com script manual para Mercado Livre.
  - Script inicial (manual, sem alterar runtime de produção):
    - `python scripts/source_dual_run_report.py mercadolivre --query "civic si"`
    - `python scripts/source_dual_run_report.py mercadolivre --query "civic si" --format json`
  - Nesta primeira etapa, o dual-run report executável suporta apenas `mercadolivre`.
  - O script é estritamente operacional/manual: não altera `source_configs`, não altera impl default, não grava DB, não chama scheduler, não chama matching/notificações e não envia Telegram.
  - Objetivo: gerar evidência objetiva de paridade/divergência V1 vs V2 (counts, matched, only_v1, only_v2, field diffs) antes de qualquer flip para `impl=v2`.
  - Próximas sources planejadas para expansão do mesmo fluxo: `olx`, `icarros`, `chavesnamao`, `mobiauto`.

- **P3 — Paridade Mercado Livre no v2.**
  - Garantir: `curl_cffi` (ou decisão explícita de não portar), POLYCARD, merge POLYCARD+HTML, filtro anti-peças, tracking/sponsored URL, VIP price fallback, canonicalização e guardrail de vertical veículos.
  - Progresso recente: corrigido bug no extractor HTML do V2 que montava `items`, mas retornava `[]` no final de `extract_raw_data`.
  - Próximo dual-run deve validar aumento de `diagnostics.v2_metrics.raw_items_found`.
  - Se `raw_items_found > 0` e `items_valid = 0`, a próxima etapa é ajustar `parse_listing`/normalização em PR separada.

- **P4 — Paridade OLX no v2.**
  - Garantir: `__NEXT_DATA__`, fallback HTML, dedupe, policy de force-browser/fallback e decisão sobre `curl_cffi`.

- **P5 — Paridade iCarros/Mobiauto/Chaves na Mão.**
  - Foco: cidade/UF, ano, km, thumbnail/`srcset`, detail fallback, taxa de thumbnail e estabilidade de parser.

- **P6 — Decisão arquitetural sobre `curl_cffi`.**
  - Opções: manter por source, adicionar ao `unified_fetch` como etapa opcional, ou não globalizar sem métrica.
  - Recomendação atual: **não globalizar agora**; decidir após dual-run/fixtures.

- **P7 — Comando admin seguro para impl (se houver demanda real).**
  - Exemplo futuro: `/admin sources impl mercadolivre dual|v1|v2`.
  - Observação: não implementar agora sem necessidade; hoje o caminho oficial é `source_configs.extra.impl`.

## 7. Não metas

- Não migrar todas as sources para v2 de uma vez.
- Não usar Webmotors como bloqueador da migração.
- Não globalizar `curl_cffi` sem medição.
- Não adicionar Patchright nesta trilha.
- Não alterar scheduler/matching/notificações nesta documentação.

## 8. Arquivos analisados nesta auditoria

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

## 9. Dual-run diagnostics (V1 vs V2)

- O relatório de dual-run agora pode retornar `summary_status=INCONCLUSIVE` com `summary_reason=both_paths_returned_zero_items` quando V1 e V2 retornam 0 itens.
- `INCONCLUSIVE` **não** autoriza flip para `impl=v2`.
- Em caso de `INCONCLUSIVE`, o próximo passo é validar com outra query/URL representativa e investigar fetch/parser antes de concluir paridade.
- O relatório também expõe `summary_reason` para deixar explícito o motivo do status calculado.

## Dual-run diagnostics (Mercado Livre)

- `summary_status=INCONCLUSIVE` com `summary_reason=both_paths_returned_zero_items` **não** é sinal de paridade; é sinal de investigação pendente.
- Resultado `0/0` (V1=0 e V2=0) **não autoriza** flip para `impl=v2`.
- O relatório agora inclui `diagnostics.hints` para orientar triagem operacional, por exemplo:
  - `both_paths_zero_items`
  - `try_broader_query_or_explicit_url`
  - `check_ml_fetch_or_parser`
  - `inspect_v2_metrics_raw_items_found`
  - `not_safe_to_flip_to_v2`
  - `dual_run_inconclusive_not_parity`
  - `v2_extracted_raw_but_parsed_zero` / `likely_v2_parse_listing_gap`
  - `v2_extracted_zero_raw_items` / `likely_fetch_or_extract_gap`
- O payload também inclui `diagnostics.v2_metrics` (quando disponível) para diferenciar gap de fetch/extract versus parse.

Próximos comandos de validação recomendados:

```bash
python scripts/source_dual_run_report.py mercadolivre --query "honda civic" --format json
python scripts/source_dual_run_report.py mercadolivre --query "golf gti" --format json
python scripts/source_dual_run_report.py mercadolivre --query "civic si" --format json --probe-fetch
python scripts/source_dual_run_report.py mercadolivre --query "civic si" --format json --probe-fetch --capture-html /tmp/ml-civic-si.html
```

Notas de operação:
- `--probe-fetch` é **manual/read-only**: faz um fetch diagnóstico da mesma URL e adiciona `diagnostics.fetch_probe` ao report.
- `--capture-html` **nunca é default**: só grava HTML quando informado explicitamente.
- O HTML capturado pode conter dados de página pública e deve ficar fora do repositório.
- Use os sinais/seletores do probe para decidir se o próximo ajuste deve ocorrer em selector/extract ou em `parse_listing`.

## Mercado Livre — estratégia de fetch (diagnóstico manual)

- Evidência operacional recente em Raspberry Pi: chamada direta da API pública (`https://api.mercadolibre.com/sites/MLB/search?...`) retornou bloqueio `403` via fetch (`FetchBlocked 403`).
- Evidência operacional recente em Raspberry Pi: URL HTML/lista de veículos retornou shell/SPA sem cards úteis (ex.: `title="| Mercado Livre"`, `cards=0`, `a_mlb_links=0`).
- Foi adicionado probe manual/read-only para estratégias de fetch, sem alterar default de scraping/parsing:
  - `python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json`
  - `python scripts/source_dual_run_report.py mercadolivre --query "civic si" --strategy-probe --format json`
- Captura de payload é opcional e explícita (`--capture-dir`), nunca ativa por padrão.
- Conclusão de migração: antes de avançar com paridade/flipe V1→V2 para Mercado Livre, é necessário recuperar uma estratégia de fetch que entregue dados úteis no ambiente alvo.

- Playwright é plano B diagnóstico explícito (somente manual), via `--include-browser`, sem alterar scraping de produção.
- Comando: `python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json --include-browser`

- `playwright_wait_scroll` executa wait+scroll real (domcontentloaded + waits + scroll leve) somente no probe manual com `--include-browser`.


## Mercado Livre — nota operacional (2026-05-23)

- Evidência recente em Raspberry: URL HTML de lista (`https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si`) respondeu com shell (`title=| Mercado Livre`, sem cards/links úteis).
- Evidência recente em Raspberry: API pública (`https://api.mercadolibre.com/sites/MLB/search?q=honda%20civic&category=MLB1743`) respondeu `403`.
- Próximo passo técnico: executar `scripts/mercadolivre_strategy_probe.py` para matriz de URL+fetch em modo manual/read-only.
- Playwright é plano B diagnóstico explícito somente com `--include-browser`.
- Não concluir migração V1→V2 para Mercado Livre sem ao menos uma estratégia retornando dados úteis (score positivo e preferencialmente >=80).
- Gate de continuidade: V1 precisa permanecer saudável (count > 0 em consultas de referência, ex.: "civic si") antes de qualquer avanço de paridade/flipe V1→V2.
- Próxima etapa após estabilizar V1: reexecutar dual-run (`source_dual_run_report`) e comparar V1 vs V2 com evidência objetiva de divergências.

## Mercado Livre — ajuste V2 de fetch/build_url (2026-05-23)

- V2 passou a usar por padrão a URL HTML de veículos (`https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/<slug>`), alinhada à estratégia operacional validada no V1.
- Fetch V2 do Mercado Livre agora reutiliza fallback validado do V1 (`networkidle` via browser) quando HTTP vem bloqueado/sem conteúdo útil (shell sem cards).
- Endpoint público JSON/API continua disponível apenas para compatibilidade/fallback explícito, e não como caminho principal.
- Diagnóstico recente no dual-run mostrou falha transitória de browser fetch (`Page.content: ... page is navigating`) mesmo com URL/fetch strategy corretos.
- Mitigação aplicada no pool Playwright: retries curtos e controlados na captura de `page.content()`, com espera leve (`domcontentloaded`) antes de falhar definitivamente.
- Quando HTML final cair em página de segurança/captcha, o fluxo deve marcar blocked explícito (ex.: `ml_security_or_captcha_page`), não `0` silencioso.
- Próximo gate de migração permanece: dual-run com `v1_count > 0` e `v2_count > 0` antes de qualquer decisão de flip.


- Gate atual de flip continua bloqueado quando Mercado Livre estiver em `ml_security_or_captcha_page` ou `ml_shell_without_results`; não decidir flip V2 durante janela de bloqueio/captcha.
- V1 e V2 já têm caminho técnico viável, porém a decisão operacional depende de estabilidade fora de security wall temporária.
