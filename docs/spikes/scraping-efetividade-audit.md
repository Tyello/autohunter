# Auditoria de efetividade de scraping (captura, custo, frequência)

Status: CONCLUÍDA — 5 investigações, backlog priorizado e lista de NÃO VERIFICADO completos.

**Atualização pós-auditoria (2026-09-25):** itens do backlog já implementados fora do escopo original (read-only) da auditoria, a pedido explícito do usuário, com TDD e sem alterar `default_force_browser`/fetch strategy em produção:
- Item 5 (fix compliance OLX v2 `/api/`) **não** foi feito ainda — ver seção 6.
- Fix de compliance equivalente encontrado e corrigido em **mobiauto**, não previsto originalmente no backlog: `_detail_enrich` (`app/scrapers/mobiauto.py`) estava requisitando URLs com `?page=detail`, disallowed pelo `robots.txt` do mobiauto.com.br (`Disallow: /comprar/carros*?*page=detail`). Corrigido com `_strip_disallowed_detail_query`. Teste: `tests/test_mobiauto_robots_compliance.py`.
- Item 3 (JSON embutido em `mobiauto`/`kavak`) **confirmado via sondagem real** (fora do orçamento de rede original desta auditoria, que era restrito a Webmotors/OLX): ambas as fontes expõem preço/km/ano em JSON já presente no HTML (mobiauto: `__NEXT_DATA__.props.pageProps.deals.results`; kavak: payload RSC em `self.__next_f.push(...)`), sem necessidade de browser. Implementado como enriquecimento aditivo (preenche `year`/`km`, campos que essas fontes nunca tiveram) em `app/scrapers/mobiauto.py` (`_extract_next_data_deals`) e `app/scrapers/kavak.py` (`_extract_rsc_cars`). Testes: `tests/test_mobiauto_next_data_enrichment.py`, `tests/test_kavak_rsc_enrichment.py`.
- **Não implementado ainda**: flip de `default_force_browser` para `False` nessas fontes (eliminaria uso de Chromium). Deliberadamente adiado — é uma mudança de estratégia de fetch em produção (maior blast radius, precisa de validação sustentada, não só uma sondagem pontual), diferente do enriquecimento aditivo acima que é seguro e reversível por natureza (preenche campos novos, não muda o caminho de fetch).

## 0. Resumo executivo

O maior alavancador de **captura** é o item de menor esforço: um monitor de preenchimento de campo por execução, reaproveitando `SourceRun.payload` sem tabela nova e sem query extra (item 1 do backlog) — teria detectado o bug histórico do OLX em uma execução, não em dias, e cobre todas as fontes de uma vez. O maior alavancador de **eficiência/custo** é confirmar se `mobiauto` e `kavak` têm JSON embutido não utilizado nas páginas de detalhe (item 3/6 NÃO VERIFICADO): se confirmado, elimina até 2 das 6 fontes hoje sempre-browser sem nenhum risco arquitetural, só trocando `force_browser` e o parser. Recall real (captura vs. universo existente) só tem métrica barata e confiável hoje para Webmotors via sitemap (marcas liberadas pelo robots.txt); OLX não tem sitemap de anúncios utilizável para esse fim. Frequência adaptativa por URL de busca é desenho viável com dados já existentes, mas depende de medir a distribuição real quente/fria antes de fixar parâmetros — por isso fica como NEEDS-DATA, não GO direto. Nenhuma proposta aqui envolve Scrapling, bypass de anti-bot ou aumento de uso de browser; todas respeitam ADR-0001/ADR-0002 e o orçamento de rede desta auditoria (8 de 30 requisições usadas, só em Webmotors/OLX).

## 1. Monitor de preenchimento por campo (field coverage)

### 1.1 O que já existe hoje (registro por execução)

- Ponto único de escrita por execução: `record_run` (`app/services/source_runs_service.py:10-59`). Insere uma linha em `SourceRun` (`db.add` + `db.flush`, sem `commit` — o commit é feito pelo chamador) e aceita um `payload: Optional[Dict[str, Any]]` livre. **Custo: 0 queries extras** — é o mesmo INSERT que já acontece a cada execução.
- `SourceRun.payload` é uma coluna `JSONB` (`app/models/source_run.py`) — pode receber qualquer estrutura nova sem migração.
- `record_run` é chamado em vários pontos de `app/services/source_execution_service.py` (linhas 183, 428, 457, 743, 778, 839, 911), sempre com um `payload=build_run_payload(...)` montado em memória.
- `build_run_payload` (`app/services/source_execution_helpers.py:111-152`) já monta esse payload e **já tem precedente de métrica de campo**: `thumb_present`/`thumb_rate` (linhas 118-119, 135-138).
- A métrica é calculada em memória, no scheduler, exatamente onde a lista final de anúncios (`listings_all`) é montada: `app/scheduler/jobs.py:248-249` (e replicado em `:531-532` para o segundo fluxo de ingestão, `scrape_ingest_match_many`):
  ```python
  thumb_present = sum(1 for it in listings_all if (it or {}).get("thumbnail_url"))
  thumb_rate = (thumb_present / found) if found else 0.0
  ```
  Isso roda sobre uma lista que já está em memória — **custo 0 em queries e desprezível em CPU** (é um loop sobre no máximo ~70-120 itens por execução).
- Também há um agregado por grupo de execuções (múltiplas URLs de uma fonte) em `app/services/source_execution_service.py:605,698,909,932-933,962` — soma `thumb_present`/`thumb_rate` entre `groups` antes do `record_run` final do lote.
- **Não existe hoje nenhuma métrica equivalente para `price`, `year`, `mileage_km`, `city`/`state`, `external_id` ou `url`.** Confirmado por busca (`grep -rn "price_rate|year_rate|km_rate|field_coverage|coverage_rate"` em `app/services`, `app/scheduler`, `app/health`, `specs`) — o único achado é o próprio `thumb_present`/`thumb_rate`.
- `decide_parse_failure` (`app/scrapers/parse_failure.py:21-48`) é o único "detector" de falha de parsing hoje, e **só dispara quando `found == 0`** (raw>0 mas normalizado=0, ou `partial_failure` com `found==0`). Ele não olha para o conteúdo dos itens que sobreviveram — só para a contagem final.

### 1.2 Onde cada campo crítico é preenchido, por fonte ativa

Fontes ativas por padrão hoje (`default_enabled` não sobrescrito para `False` em `app/sources/builtins.py`, default da dataclass é `True` — `app/sources/types.py:89`): `mercadolivre`, `olx`, `chavesnamao`, `gogarage`, `icarros`, `mobiauto`, `kavak`, `facebook_marketplace`, `turboclass`. **`webmotors` é a única desabilitada por padrão** (`default_enabled=False`, `app/sources/builtins.py:148`, papel `"deprioritized"`).

| Fonte | price | year | mileage_km/km | location (city/UF) | thumbnail_url | external_id | url |
|---|---|---|---|---|---|---|---|
| `mercadolivre` | `app/scrapers/mercadolivre.py:655` (regex sobre JSON embutido) e `:762` (fallback) | **NÃO preenchido no scraper** (nenhuma ocorrência de `"year"` em `mercadolivre.py`) | **NÃO preenchido** | `:658` (regex `"type":"location"`) | `:684`/`:767` | `:681`/`:764` | `:683`/`:766` |
| `olx` | `app/scrapers/olx.py:515` (`it.price`, extraído via `__NEXT_DATA__`/RSC/fallback CSS) | `:518`, via `_extract_year_from_title` (`:479-485`, regex no título) | `:519`, via `_extract_mileage_from_title` (`:488-502`, regex no título) | `:517` (`it.location`) | `:514` | `:511` | `:513` |
| `chavesnamao` | regex `"R$"` no texto do link, `app/scrapers/chavesnamao.py:~172` (confirmado em `tests/test_chavesnamao_scraper.py:63`) | **NÃO preenchido** | **NÃO preenchido** | `_extract_location_from_url`/`_extract_location_from_anchor_text` (`chavesnamao.py:106-142`) | `:74` (img/srcset/background), fallback via `og:image` na página de detalhe (`:~233`) | via `/id-` no href | via `href` do card |
| `webmotors` (desabilitada por padrão) | `app/scrapers/webmotors.py:168` (regex `"R$"` no texto do card, único parser — HTTP e browser reusam `_parse_listings_from_html`, linhas 324-326 e 378) | **NÃO preenchido** (nenhuma ocorrência de `"year"`) | **NÃO preenchido** | `:170` via `_extract_location` | `:169` via `_pick_thumb` | `:165` via `_extract_external_id(url)` | `:166` |
| `gogarage` | `app/scrapers/gogarage.py:475` | `:476`, também `d.get("year")` em `:711` (enriquecimento) | **NÃO preenchido** (nenhuma ocorrência de `"km"`/`"mileage_km"`) | `:731` → **hardcoded `None`** no dict base (preenchido só se enriquecido depois) | `:474`, refinado `:710` | `:472`, refinado `:703` | `:727` |
| `icarros` | `:568`/`:592` | **NÃO preenchido** | **NÃO preenchido** | `:557` (`listing.get("location")` ou `_extract_location_from_url`), `:596`, `:647`/`:666` (fallback) | `:594`, `:646`/`:665` (fallback `None`) | `:642`/`:661` | `:643`/`:662` |
| `mobiauto` | `:371` (também `:203`) | **NÃO preenchido** | **NÃO preenchido** | `:364`/`:207` | `:374`/`:402`/`:205` | `:37`/`:52` (fallback) | `:38`/`:53` |
| `kavak` | `:203-204` (enriquecimento condicional; base é `None` em `:196`/`:221`) | **NÃO preenchido** | **NÃO preenchido** | `:207-208` (idem, base `None` em `:198`/`:223`) | `:205-206` (idem, base `None` em `:197`/`:222`) | `:193`/`:218` (`_external_id_from_url`) | `:194`/`:219` |
| `facebook_marketplace` | **NÃO preenchido** — scraper só extrai IDs de item via regex `/marketplace/item/(\d+)` (`app/scrapers/facebook_marketplace.py`, `_extract_ids`) e monta URL; docstring do próprio arquivo admite "title/price often behind dynamic components" | **NÃO preenchido** | **NÃO preenchido** | **NÃO preenchido** | **NÃO preenchido** | via regex do ID | construído via `urljoin` |
| `turboclass` | `:273` | `:277` | **NÃO preenchido** (nenhuma ocorrência de `"km"`/`"mileage_km"`) | `:275` | `:272` | `:269` | `:271` |

Observações importantes desta tabela:

- **`year`/`mileage_km` só são extraídos hoje em 3 das 9 fontes ativas: `olx`, `gogarage` (só `year`) e `turboclass` (só `year`)**. Para `mercadolivre`, `chavesnamao`, `webmotors`, `icarros`, `mobiauto`, `kavak` e `facebook_marketplace`, esses campos **nunca são preenchidos no scraper** — chegam sempre `None`/ausentes ao `car_listings_repo`.
- Na persistência, `app/repositories/car_listings_repo.py:414-439` normaliza a chave (`"km"` vira `"mileage_km"` quando a coluna existe) e há um fallback legado (`_decorate_title_with_year_km`, `:46-70`) que codificava ano/km no título quando o schema não tinha as colunas — hoje o schema tem as colunas (`has_year_col`/`has_km_col` verdadeiros), então esse fallback é código morto na prática, mas seria acionado se as colunas fossem removidas.
- `facebook_marketplace` é essencialmente um scraper de descoberta de URLs, não de dados — qualquer monitor de field coverage vai mostrar 0% em quase todos os campos por design atual, não por bug. Isso é um achado por si só (ver seção 6/backlog).
- `mercadolivre` é a fonte `"primary"` mais usada e nunca extrai `year`/`km` no scraper — hoje esses dados dependem inteiramente do scoring/matching tolerar ausência (`specs/020-score-v2-data-completeness`, `defaulted_dimensions`) em vez de virem preenchidos na origem.

### 1.3 Cálculo de percentual de preenchimento por campo: existe?

Não. Busca em `specs/020-score-v2-data-completeness` (grep por `coverage|field.*fill|preenchimento`) não retorna nenhum mecanismo de medição de coverage de scraping — esse spec cobre `defaulted_dimensions` no **scoring de notificação** (pós-matching, por anúncio individual notificado), um conceito relacionado mas distinto: mede o que falta na hora de pontuar um anúncio já capturado, não a taxa de preenchimento agregada por execução de scrape. `specs/021-olx-year-mileage-extraction` (a spec que corrigiu o bug do título) não introduziu nenhum monitor — grep por `coverage|rate|monitor` nos arquivos da spec não retorna nada; a spec apenas corrigiu a extração pontual via `_extract_year_from_title`/`_extract_mileage_from_title`.

### 1.4 Desenho proposto

**Onde calcular:** em memória, no mesmo ponto onde `thumb_present`/`thumb_rate` já são calculados hoje (`app/scheduler/jobs.py:248-249` e `:531-532`), estendendo o mesmo padrão para os demais campos críticos:

```python
FIELD_KEYS = ("price", "year", "mileage_km", "location", "thumbnail_url", "external_id", "url")
field_present = {k: sum(1 for it in listings_all if (it or {}).get(k)) for k in FIELD_KEYS}
field_rate = {k: (v / found) if found else 0.0 for k, v in field_present.items()}
```

Custo: um loop adicional sobre a mesma lista já em memória (ou fundir no loop existente de `thumb_present`) — **0 queries extras**, mesma ordem de grandeza de CPU que o cálculo de `thumb_rate` já pago hoje.

**Onde persistir:** dentro do mesmo `payload` de `build_run_payload` (`app/services/source_execution_helpers.py:111-152`), adicionando `field_rate`/`field_present` como mais duas chaves do dict — reaproveitando o `SourceRun.payload` JSONB existente. **Nenhuma tabela nova, nenhuma migração.**

**Limites iniciais (thresholds):** por campo e por fonte, começando conservador para não gerar ruído em fontes que já não preenchem `year`/`km` por design atual (tabela 1.2). Sugestão:

- `price`, `external_id`, `url`: threshold alto (ex. `< 90%` dispara alerta) — são campos que **todas** as fontes ativas hoje preenchem quando o parsing funciona; uma queda abaixo de 90% é sinal forte de regressão de parsing.
- `location`, `thumbnail_url`: threshold médio (`< 70%`) — dependem mais de heurística/enriquecimento por página de detalhe.
- `year`, `mileage_km`: threshold **por fonte**, não global — para `olx`, `gogarage`, `turboclass` (que já extraem hoje), um baseline por fonte calculado da média móvel dos últimos N runs bem-sucedidos, disparando se cair >50% relativo ao baseline (não um valor absoluto), porque não há benchmark de "preenchimento esperado" a priori. Para as fontes que hoje não preenchem (`mercadolivre`, `chavesnamao`, `webmotors`, `icarros`, `mobiauto`, `kavak`, `facebook_marketplace`), **não alertar** — ausência é o estado normal atual, e alertar aqui seria ruído até que essas fontes ganhem extração desses campos (item de backlog separado, não parte deste monitor).

**Canal de alerta:** reaproveitar o pipeline existente de alertas administrativos, que já roda periodicamente e já teria o dedup/cooldown certo:
- `collect_operational_alerts` (`app/services/operational_alerts_service.py:252+`) monta uma lista de `OperationalAlert(key, message, cooldown_minutes)` (dataclass em `:115-118`), com cooldown controlado via `AppKV` (`_is_cooldown_open`, `:156-169`, chave `ops_alert:{key}`).
- `job_admin_monitor` (`app/scheduler/admin_monitor_job.py:29-51`) chama `collect_operational_alerts` e envia cada alerta via `send_admin_text` (`app/services/admin_alerts_service.py:117-119`), que despacha para os chats configurados em `autohunter_admin_alert_chats`/`autohunter_admins` (`iter_admin_chat_ids`, `admin_alerts_service.py:26-33`).
- Proposta: adicionar ao `collect_operational_alerts` uma checagem que lê os `SourceRun.payload` mais recentes por fonte (já é feito hoje para outras métricas nesse mesmo arquivo, ex. `_extract_runtime_impl`, linhas ~55-62, que também lê `payload`), compara `field_rate` contra o threshold/baseline, e adiciona um `OperationalAlert` com `cooldown_minutes` alto (ex. 360min) para não repetir o alerta a cada tick do scheduler.

**Custo em queries por execução:** **0** para o cálculo (em memória) e **0 adicional** para persistência (mesmo INSERT do `record_run`). Para o job de alerta, que já roda separado do scraping (`job_admin_monitor`), o custo é o mesmo da leitura de `SourceRun` que `collect_operational_alerts` já faz para outras métricas (**1 query agregada, já paga hoje**, não uma query nova).

### 1.5 Pergunta-chave: esse monitor teria detectado o bug do OLX? Em quanto tempo?

**Sim, muito provavelmente — e mais rápido do que qualquer mecanismo hoje existente.**

O bug (km/ano/FIPE sumindo do OLX antes do scoring) não derrubava `found` a zero — os anúncios continuavam sendo extraídos e contados normalmente, só os campos `year`/`mileage_km` (e o FIPE calculado a partir deles) vinham vazios. Isso significa:

- `decide_parse_failure` (`parse_failure.py:29-46`) **não disparava**, porque exige `found == 0` em todos os seus ramos — essa é a confirmação direta do porquê o bug passou despercebido, citada na lição registrada no contexto da tarefa.
- Com o monitor proposto, a métrica `field_rate["year"]`/`field_rate["mileage_km"]` para a fonte `olx` cairia de um baseline não-zero (o scraper extraía esses campos normalmente antes do bug) para próximo de 0% assim que a regressão de parsing começasse a afetar o título — **na primeira execução de scrape do OLX após o bug ser introduzido** (o scheduler roda OLX a cada `sched_olx_minutes`, tipicamente na casa de minutos, não dias).
- Como o cálculo é feito por execução (não por lote agregado ao longo do dia), a detecção seria **na execução seguinte à introdução do bug**, e o alerta administrativo (sujeito ao `cooldown_minutes` do job, que roda periodicamente, tipicamente a cada poucos minutos conforme o agendamento de `job_admin_monitor`) sairia dentro de uma janela de minutos, não do tempo que o bug real ficou sem detecção (que dependeu de alguém notar manualmente).

Ressalva **NÃO VERIFICADO**: não encontrei no histórico do repositório (fora de escopo de leitura de git blame/PR nesta auditoria, que é sobre código atual) o tempo real que o bug ficou ativo em produção antes de ser corrigido pela spec 021 — a estimativa acima é sobre o tempo de detecção *com* o monitor proposto, não uma comparação com o tempo real histórico de detecção sem ele.

## 2. Taxa de captura (recall)

### 2.1 Confirmação: não existe medição de recall hoje

Busca por `recall|capture_rate|coverage` em `app/scrapers`, `app/services`, `app/scheduler`, `specs` não retorna nenhum mecanismo do tipo "anúncios que existiam vs capturados" — os únicos achados são falsos-positivos de nome (`fipe_*`, `db-index-coverage-audit` = cobertura de índice de banco, `car-listings-facet-indexes`), sem relação com recall de scraping. **Confirmado: não existe.**

A única comparação estrutural existente é `compare_results`/`run_with_dual_mode` (`app/scrapers/dual_run.py:26-58`, `:69-105`), mas ela compara **v1 vs v2 do nosso próprio código rodando contra a mesma URL de busca**, não contra uma referência externa de "quantos anúncios realmente existem". Ela mede `only_v1_count`/`only_v2_count`/`intersection` (`dual_run.py:49-57`) — divergência de parsing entre duas implementações nossas, não recall real. Se ambas as implementações perderem os mesmos anúncios (ex.: paginação não coberta por nenhuma delas), o dual_run não detecta.

### 2.2 Achado adicional relevante: nenhum scraper hoje pagina resultados

Busca por `page=|paginat|next_page|page_number` em `app/scrapers/olx.py`, `app/scrapers/mercadolivre.py` e `app/services/search_urls_service.py` não retorna nada — cada execução de scrape hoje bate em **uma única página de busca** por URL configurada (tipicamente ~40-70 cards, conforme limites vistos nos scrapers, ex. `webmotors.py:174` corta em 70). Isso é relevant para qualquer proposta de medição de recall: se a página 1 já não cobre todo o resultado de uma busca ampla, qualquer estimativa de recall vai estar sistematicamente subestimando o que existe além da primeira página — mas isso também é uma limitação da captura normal hoje, não só da medição.

### 2.3 Opções avaliadas

**(a) Sitemaps oficiais.** Ver seção 4 para os achados de rede (Webmotors, OLX). Onde existir sitemap de anúncios com `<lastmod>`, o custo é baixíssimo (poucas requisições HTTP a arquivos estáticos, sem passar por anti-bot de busca) e dá uma contagem de referência relativamente confiável — mas só serve como proxy de recall se o sitemap realmente listar os anúncios ativos de forma completa (não confirmado sem a sondagem da seção 4).

**(b) Busca ampla de referência paginada, comparada às URLs em `listings`.** Requer implementar paginação (hoje inexistente, 2.2) para pelo menos uma URL de referência ampla por fonte (ex.: "todos os carros" sem filtro de modelo), rodada fora de pico, com um número limitado de páginas (ex. 5-10). O lado do banco é barato: `(source, external_id)` tem `UniqueConstraint` (`app/models/car_listing.py:28`), então comparar o lote de `external_id`s coletados contra os já existentes é **uma única query indexada em lote** (`WHERE source = :s AND external_id = ANY(:ids)`), nunca por anúncio — compatível com ADR-0002. Custo real está do lado de requisições HTTP: paginar uma busca ampla custa `N` requisições adicionais por fonte por execução de amostragem (não por tick normal de scraping) — deve rodar com frequência baixa (ex. 1x/dia, fora de pico), não a cada ciclo do scheduler.

**(c) Comparar com os anúncios recebidos no `dual_run`.** Como descrito em 2.1, isso **não mede recall real** — mede apenas divergência entre v1 e v2 da mesma fonte. Só seria útil como proxy de recall se uma das duas implementações (v1 ou v2) usasse uma estratégia de coleta estruturalmente diferente da outra (ex.: uma usa API interna, outra pagina HTML) — hoje isso não é garantido pelo código (`run_v1_adapter`/`run_v2_adapter`, `app/scrapers/dual_run.py:9`) e não foi verificado se há alguma fonte nessa condição. **NÃO VERIFICADO**: se existe hoje alguma fonte cujo v1 e v2 usam fontes de dados de fato diferentes (não só parsers diferentes do mesmo HTML).

### 2.4 Tabela comparativa

| Opção | Custo requisições/dia | Custo queries Supabase | Confiabilidade |
|---|---|---|---|
| (a) Sitemap oficial | Baixo (poucos arquivos estáticos, ~1-5 por fonte) — depende da sondagem da seção 4 | 1 query em lote por comparação (`external_id IN (...)`) | Alta *se* o sitemap listar anúncios ativos de forma completa (a confirmar por fonte) |
| (b) Busca ampla paginada | Médio-alto (requer paginar, hoje não implementado; N requisições por execução de amostragem, 1x/dia sugerido) | 1 query em lote por comparação | Média — depende de quantas páginas se decide raspar; sujeita a anti-bot na página ampla |
| (c) Comparação via `dual_run` | 0 adicional (reaproveita execuções já feitas) | 0 adicional | Baixa para recall real — mede só divergência v1/v2, não cobertura vs. mercado real |

### 2.5 Recomendação preliminar

(a) é a opção mais barata e alinhada aos ADRs quando o sitemap existir e for confiável (ver seção 4); (b) é o fallback para fontes sem sitemap de anúncios, mas custa engenharia nova (paginação) que hoje não existe; (c) não deve ser vendida como medição de recall — é útil só para o que já faz hoje (divergência de parsing entre v1/v2).

## 3. Frequência adaptativa por busca

### 3.1 Como `next_due` é calculado hoje

O intervalo é calculado **por fonte, não por URL de busca nem por wishlist**. Fluxo em `app/scheduler/run.py`:

- `job_run_source_for_all_wishlists(source_name)` (`run.py:130-219`) roda por fonte (o nome já entrega: um tick cobre todas as wishlists daquela fonte de uma vez).
- `minutes = int(cfg.sched_minutes or 0)` (`run.py:164` e `:193`) vem de `SourceConfig` (`get_source_config_snapshot`, DB-driven, `source_configs.sched_minutes` — um valor escalar por fonte).
- `st = _get_state(db, src)` (`run.py:169`/`:198`) busca `SourceState`, que tem `source: unique=True` (`app/models/source_state.py:24`) — **uma linha por fonte**, não por URL.
- `next_due = (last_eff + timedelta(minutes=minutes)) if last_eff else _utcnow()` (`run.py:171`/`:200`) — mesmo intervalo fixo aplicado à fonte inteira; se `_utcnow() < next_due`, o tick não faz nada (`:172-174`/`:201-203`).
- Quando devido, `enqueue_job(...)` (`:182`/`:213`) empilha **um job por fonte** na fila (`browser` ou `http`), que dentro da execução itera por todas as URLs de busca configuradas para aquela fonte (os "groups" mencionados nos payloads de `source_execution_service.py`).

**Conclusão direta:** hoje não há diferenciação de cadência por URL de busca específica ou por wishlist — uma busca de nicho (poucos anúncios novos) e uma busca genérica de "carro" (muitos anúncios novos) na mesma fonte são raspadas na mesma cadência, porque o intervalo vive em `source_configs.sched_minutes`/`SourceState`, ambos por fonte.

### 3.2 Dados existentes que sustentam cálculo de "taxa de anúncios novos por URL"

Apesar do `next_due` ser por fonte, os dados granulares por URL **já existem** e não exigiriam nova tabela:

- `SourceUrlCursor` (`app/models/source_url_cursor.py:14-33`, tabela `source_url_cursors`) — chave `(source, url)`, com `last_external_id`, `last_seen_at`, `last_checked_at`, `runs`. Não guarda contagem de itens novos por execução, mas confirma o "estado" por URL.
- `SourceRun` (via `record_run`, `app/services/source_runs_service.py:10-59`) grava `url` (linha 17 da assinatura) e `items_ingested` (linha 22-23) por execução — e `items_ingested` mapeia `total_inserted`/`inserted_new` (`app/scheduler/jobs.py:306`,`:590`, e o `record_run` do lote em `source_execution_service.py:920` usa `items_ingested=total_inserted`), ou seja, **é especificamente a contagem de anúncios novos (INSERT), não atualizações** — exatamente o sinal necessário para "taxa de anúncios novos por URL de busca".
- `CarListing.created_at` (via `TimestampMixin`, `app/db/base.py:26-30`) funciona como proxy de "primeira vez visto" por anúncio individual, mas **não tem vínculo direto com qual URL de busca o descobriu** (o schema de `car_listings` não guarda a URL de origem — só `source`/`external_id`). Por isso, o sinal correto para "novos por URL" é `SourceRun.items_ingested` agrupado por `(source, url)` ao longo do tempo, não uma junção com `car_listings`.

**Consulta proposta (1 query agregada, com `LIMIT`, sem tocar Supabase por anúncio):**
```sql
SELECT url, date_trunc('day', created_at) AS day, SUM(items_ingested) AS new_count, COUNT(*) AS runs
FROM source_runs
WHERE source = :source AND created_at > now() - interval '14 days'
GROUP BY url, day
ORDER BY day DESC
LIMIT 500;
```
Isso é compatível com a restrição de "no máximo 1 query agregada com `LIMIT`" — roda fora do caminho de scraping em si (ex. um job diário separado, como o `job_admin_monitor`), não a cada tick.

### 3.3 Política proposta

- **Faixas de intervalo:** manter `sched_minutes` como piso configurável por fonte (`source_configs`, hoje já é o mínimo operacional por motivo de rate-limit/anti-bot), e introduzir um **multiplicador por URL** aplicado sobre esse piso, calculado a partir da taxa de novos anúncios/dia observada em 3.2:
  - taxa alta (ex. `new_count/dia` acima de um percentil alto entre as URLs da mesma fonte) → intervalo no piso (`sched_minutes` puro);
  - taxa baixa/zero em janela de N dias → intervalo multiplicado (ex. 2x, 4x, até um teto configurável), reduzindo requisições em buscas de nicho sem anúncios novos.
- **Como subir/descer:** ajuste gradual (ex. half-life ou multiplicador incremental por ciclo de avaliação, não salto direto ao teto) para evitar oscilação — mas o desenho fino desse algoritmo é decisão de implementação, não coberto por esta auditoria além de citar a política.
- **Proteções necessárias:**
  - **Intervalo máximo para buscas de usuário Premium**: hoje não existe nenhuma diferenciação por plano no scheduler (`grep -n "premium" app/scheduler/run.py app/scheduler/jobs.py` só retorna o job de expiração de assinatura, não lógica de cadência) — isso precisaria ser adicionado como trava explícita: nunca deixar o multiplicador estender o intervalo de uma busca com wishlist Premium ativa além de um teto (ex. nunca mais que `sched_minutes * 2` para buscas com pelo menos uma wishlist Premium vinculada), garantindo que o adaptativo não penalize o usuário pagante.
  - **Orçamento de requisições por fonte e dia**: hoje o único limite existente é `rate_limit_*_seconds` (throttle entre requisições dentro de uma execução) e `cooldown_minutes` (backoff pós-bloqueio) — não há um orçamento agregado diário por fonte. A política adaptativa precisaria somar as reduções esperadas contra um teto diário simples (ex. `max_requests_per_day` por fonte em `source_configs.extra`) para não permitir que a soma de todas as URLs "quentes" ultrapasse o que a fonte tolera antes de bloquear.

### 3.4 Estimativa de redução de requisições/dia e efeito na latência

Estimativa qualitativa (sem dado de produção sobre distribuição real de "URLs quentes vs frias" — **NÃO VERIFICADO**, precisaria da consulta de 3.2 rodando por um período antes de dar número): buscas de nicho (marca/modelo raro, faixa de preço estreita) tendem a ser a maioria numérica das wishlists configuradas, mas a minoria do volume de anúncios novos/dia. Se a distribuição seguir esse padrão (típico em marketplaces), reduzir a cadência das URLs "frias" para 2-4x o intervalo base deve cortar uma fração relevante do total de requisições/dia sem tocar nas URLs "quentes" (que continuam no piso). O custo é latência de alerta maior *apenas* para as wishlists que caem nas URLs frias — que, por definição, têm poucos ou nenhum anúncio novo no período observado, então o impacto percebido pelo usuário deve ser baixo. Sem medir a distribuição real (item de pré-requisito antes de qualquer PR), não é possível dar um número de redução confiável.

## 4. Descoberta via sitemap (sondagem de rede limitada)

**Ambiente:** sondagem executada do PC de desenvolvimento (não do Raspberry Pi — acesso ao Pi não estava disponível nesta sessão), usando `curl_cffi` (`pip show curl_cffi` confirma `0.14.0` instalado), `impersonate="chrome120"`, timeout 20-25s, com **≥2.5s de intervalo entre requisições**. Total usado: **8 requisições** (abaixo do limite de 30), listadas abaixo em ordem. Comando/script usado: `scripts descartáveis` locais (`probe_sitemaps.py`, `probe_sitemaps2.py`, `probe_olx.py`, `probe_olx2.py`, todos com prefixo `probe_` e fora do repositório, em `$CLAUDE_JOB_DIR/tmp`, não commitados).

### 4.1 Webmotors

| # | Requisição | Status | Tamanho | Observação |
|---|---|---|---|---|
| 1 | `GET https://www.webmotors.com.br/robots.txt` | 200 | 3.9 KB | ver 4.1.1 |
| 2 | `GET https://www.webmotors.com.br/sitemap/v2/sitemaps-DA-index.xml` | 200 | 3.1 KB | índice com 20 sitemaps por marca (`.xml.gz`) |
| 3 | `GET https://www.webmotors.com.br/sitemap/v2/DA-index-HONDA.xml.gz` | 200 | 4.5 MB (bytes brutos da resposta) | ver 4.1.2 |
| 4 | `GET <1 URL de detalhe extraída do arquivo Honda>` | 200 | 18.9 KB | ver 4.1.3 |

**4.1.1 `robots.txt`:** política seletiva por marca para o path `/comprar/`. Regra geral é `Disallow: /comprar/`, com `Allow:` explícito só para uma lista de marcas ("ONDA 1"/"ONDA 2" de liberação de indexação): `bmw`, `mercedes-benz`, `audi`, `mitsubishi`, `land-rover`, `porsche`, `ram`, `mini`, `volvo`, `toyota`, `honda`, `ford`, `kia`, `caoa-chery`, `nissan`, `peugeot` (carros) + marcas de moto. Também há `Disallow: /api/detail/`. O sitemap-index (`sitemaps-DA-index.xml`) só lista `.xml.gz` para exatamente essas marcas liberadas — ou seja, o próprio sitemap já respeita o allow-list do robots.txt (não há sitemap de marcas bloqueadas).

**4.1.2 Arquivo `DA-index-HONDA.xml.gz`:** apesar da extensão `.gz` e do `content-type: application/gzip` retornado, o corpo da resposta já veio como **XML puro** (`gzip.decompress` falhou com `BadGzipFile`, mas o texto começava com `<?xml`) — indício de que o `curl_cffi`/servidor já descomprime a resposta via `Content-Encoding: gzip` da camada HTTP antes do corpo chegar à aplicação, então o `.gz` do nome do arquivo não precisa de descompressão manual adicional nesse fluxo de cliente. **28.677 `<loc>`** e **28.677 `<lastmod>`** (1:1, todo `<loc>` tem `<lastmod>`, todas datadas do dia da sondagem, 2026-09-25). Formato de URL: `https://www.webmotors.com.br/comprar/{marca}/{modelo}/{versao-slug}/{tipo}/{ano}/{id-numerico}` — ex.: `.../comprar/honda/fit/14-lx-16v-flex-4p-automatico/4-portas/2009/79259493`. O último segmento numérico é o ID do anúncio, condizente com o padrão usado por `_extract_external_id` (`webmotors.py`).

**4.1.3 URL de detalhe (`.../honda/cb-1000r/1000cc/2012/3061347`):** HTTP 200, **sem nenhum desafio/sinal de PerimeterX** (checagem por substring `perimeterx|px-captcha|_pxhd|please enable js`, nenhuma encontrada) — a página carregou normalmente via HTTP simples com TLS impersonation, sem bloqueio. Porém: **não há `application/ld+json` nem `__NEXT_DATA__` no HTML inicial** (18.9 KB, majoritariamente shell/scripts de tracking — Datadog RUM, Adobe Target, etc.). Isso é consistente com o comentário já existente no código (`webmotors.py`: "Browser-first capturando XHR JSON (Playwright) é o caminho mais estável") — os dados estruturados (preço, ano, km) não estão no HTML inicial da página de detalhe, precisam vir de uma chamada XHR pós-carregamento, que só um browser real executa.

### 4.2 OLX

| # | Requisição | Status | Tamanho | Observação |
|---|---|---|---|---|
| 5 | `GET https://www.olx.com.br/robots.txt` | 200 | 12.9 KB | ver 4.2.1 |
| 6 | `GET https://www.olx.com.br/sp/sitemap_index.xml` | 200 | 2.1 KB | 15 sitemaps (`sp/sitemap1.xml` … `sp/sitemap15.xml`) |
| 7 | `GET https://www.olx.com.br/robots.txt` (re-fetch para salvar corpo completo) | 200 | 12.9 KB | idem #5, salvo em arquivo local para grep completo |
| 8 | `GET https://www.olx.com.br/sp/sitemap1.xml` | 200 | 6.5 MB | ver 4.2.2 |

**4.2.1 `robots.txt`:** um único bloco `User-agent: *` (linha 1) cobre todo o arquivo — **confirma `Disallow: /api/` (linha 607)**, aplicável globalmente. Também há `Disallow: /q/*`, `Disallow: /busca`, `Disallow: /search/`. O path usado hoje pelo scraper v1 ativo (`olx_url`, `app/services/search_urls_service.py:139-141`: `https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q=...`) **não bate em nenhuma regra `Disallow`** (não há `Disallow: /autos-e-pecas` nem regra genérica de path que capture esse prefixo) — a busca de listagem usada em produção está em conformidade com o robots.txt.

**Conformidade do `/api/v1/search/listings`:** `grep -rn "api/v1/search/listings" app/` retorna **apenas** `app/scrapers/sources/olx.py:31,52` — o adapter **v2** (`API_URL = "https://www.olx.com.br/api/v1/search/listings"`, usado em `:52`). O scraper **v1** (`app/scrapers/olx.py`, ativo por padrão conforme 5.1 — `impl` default é `"v1"`) **não contém nenhuma referência a `/api/`** (`grep -n "api/v1|/api/" app/scrapers/olx.py` não retorna nada). Ou seja: **o path atualmente ativo em produção não viola `Disallow: /api/`**; o path que violaria só existe no adapter v2, que não está ligado por padrão. Se `source_configs.extra["impl"]` da OLX for movido para `"v2"` ou `"dual"` em produção (não verificado se já está — **NÃO VERIFICADO**, é dado de runtime/DB), isso passaria a violar o `robots.txt` e precisaria ser corrigido antes de promover v2.

**4.2.2 `sp/sitemap1.xml` (amostra, 1 de 15 arquivos do state SP):** 50.000 `<loc>`, **zero `<lastmod>`** por URL (só o sitemap-index tem `<lastmod>`, por arquivo, não por URL individual). Formato de URL: páginas de **navegação por categoria/localização** (ex.: `https://www.olx.com.br/estado-sp/sao-paulo-e-regiao/atibaia`, `https://www.olx.com.br/imoveis/terrenos/lotes/estado-sp/regiao-de-presidente-prudente/rosana`) — **nenhuma URL de anúncio individual encontrada** (nenhuma URL com um ID numérico de 7+ dígitos típico de anúncio OLX, conforme checagem regex). Não sondei os outros 14 arquivos do índice (fora do orçamento necessário para responder a pergunta-chave desta seção com uma amostra já suficientemente clara) — **NÃO VERIFICADO** se algum dos outros 14 segue padrão diferente, mas a estrutura consistente do sitemap-index (mesmo prefixo `sp/sitemapN.xml`, sem indicação de categoria diferente por arquivo) sugere fragmentação por tamanho, não por tipo de conteúdo.

### 4.3 Veredito por fonte

- **OLX**: o sitemap (`/sp/sitemap_index.xml` e seus 15 arquivos) serve **(iv) nenhum** dos usos propostos — é um sitemap de páginas de categoria/localização para SEO, sem `<lastmod>` por item e sem URLs de anúncio individual. Não serve como descoberta de anúncios novos nem como referência de recall. A via de descoberta de anúncios do OLX continua sendo a busca já implementada (HTML/JSON embutido).
- **Webmotors**: o sitemap (`/sitemap/v2/sitemaps-DA-index.xml` + arquivos por marca) serve **(iii) ambos**, com ressalvas: **(i) descoberta de anúncios novos** — sim, tem `<lastmod>` por anúncio individual (por ID), permitindo detectar itens novos/atualizados sem passar pela busca protegida por PerimeterX; **(ii) referência de recall** — sim, na mesma lógica (a lista completa de IDs por marca liberada é uma fonte de verdade razoável para comparação). Ressalva: cobre só as marcas liberadas pelo `robots.txt` (a lista de ~16 marcas de carro em 4.1.1), não o catálogo inteiro da Webmotors — recall medido via sitemap seria só para essas marcas.
- **Webmotors reabre a fonte sem passar pela busca protegida?** **Parcialmente.** O sitemap resolve a *descoberta* de quais anúncios existem (IDs + URLs), sem tocar a busca com anti-bot. Mas a página de **detalhe** do anúncio (necessária para preço/ano/km) não expõe dados estruturados no HTML inicial (4.1.3) — os dados ainda dependem de XHR pós-carregamento, ou seja, **ainda precisaria de browser (ou engenharia reversa da chamada XHR) para extrair os campos**, mesmo usando o sitemap para descoberta. O sitemap reduz o problema de "quais IDs existem" (que hoje depende da busca protegida), mas não elimina a necessidade de browser para os dados em si — **não é um NO-GO nem um GO puro para reabrir Webmotors sem browser; é uma redução parcial de escopo** (só resolve descoberta, não extração).

## 5. Ordem de extração e escada de escalonamento

### 5.1 v1 vs v2: o que está de fato ligado hoje

`read_source_impl_flags` (`app/sources/flags.py:15-34`) lê `source_configs.extra["impl"]`, com **default `"v1"`** (`:18`) se a chave não estiver setada. Nenhum `default_extra` em `app/sources/builtins.py` define `"impl"` para nenhuma fonte — logo, **todas as fontes rodam v1 por padrão em produção**, e só migrariam para v2/dual via flag explícita em `source_configs` no banco (não verificado se alguma fonte tem essa flag ligada hoje em produção — **NÃO VERIFICADO**, é dado de runtime/DB, fora do que dá para confirmar só pela leitura de código/config default). Os arquivos v1 (raspadores efetivamente em uso) são `app/scrapers/{mercadolivre,olx,chavesnamao,webmotors,gogarage,icarros,mobiauto,kavak,facebook_marketplace,turboclass}.py`. Os v2 (`app/scrapers/sources/*.py`, baseados em `BaseScraper`, `app/scrapers/scraper_base/scraper.py`) existem para `chavesnamao`, `gogarage_mobiauto` (combinado), `icarros`, `kavak`, `mercadolivre`, `olx`, `turboclass`, `webmotors` — mas não são o caminho ativo por default.

### 5.2 Classificação por fonte da fonte de dado usada (v1, ativo por default)

| Fonte | Fonte de dado primária | Evidência | JSON disponível mas ignorado? |
|---|---|---|---|
| `mercadolivre` | JSON embutido (regex sobre bloco `"polycard"`/`components` no HTML/script da página, não `__NEXT_DATA__` propriamente) | `app/scrapers/mercadolivre.py:640` (regex `"polycard"..."metadata"..."id"..."url"`), `:655` (preço), `:658` (localização) | Não aplicável — já usa JSON |
| `olx` | JSON embutido (`__NEXT_DATA__`/RSC), com fallback CSS | `_extract_next_data_json` (linha citada na spike de parser), `_fallback_parse_from_cards` (`olx.py:757` conforme `tests/test_olx_malformed_html_robustness.py`) | Não — já prioriza JSON, CSS é só fallback documentado |
| `chavesnamao` | CSS (`a[href]` com `/id-`, regex de texto para preço/local) | `app/scrapers/chavesnamao.py:~172` (link+preço), `:106-142` (local via regex) | **NÃO VERIFICADO** — não sondei página real da Chaves na Mão (fora do escopo de rede autorizado nesta auditoria, restrito a Webmotors/OLX) para saber se existe `ld+json`/JSON embutido não utilizado |
| `webmotors` (desabilitada por padrão) | CSS (`lxml.html`, xpath sobre HTML renderizado por browser) | `_parse_listings_from_html` (`webmotors.py:76-172`) | Ver seção 4 — há indício de dados estruturados na página de detalhe via sitemap, a confirmar |
| `gogarage` | JSON embutido (`ld+json`/schema.org, `@id`) | `app/scrapers/gogarage.py:245-249` (`el.get("@id")`/`item.get("@id")`) | Não — já usa JSON-LD como fonte primária |
| `icarros` | JSON embutido (`ld+json`, `priceValue`/`lowPrice`/`highPrice`) | `app/scrapers/icarros.py:443-450` | Não — já usa JSON-LD |
| `mobiauto` | CSS (`lxml` xpath puro, sem nenhuma referência a `ld+json`/`__NEXT_DATA__`/`json.loads` no arquivo) | `app/scrapers/mobiauto.py:126,181-196,283` (só `xpath`) | **Possível** — nenhuma tentativa de JSON embutido encontrada no código; **NÃO VERIFICADO** se a página real do Mobiauto expõe JSON estruturado, pois sondar isso está fora do orçamento de rede autorizado (restrito a Webmotors/OLX) |
| `kavak` | CSS (`lxml` xpath puro, mesma ausência de `ld+json`/JSON) | `app/scrapers/kavak.py:54,120,144,162` | **Possível**, mesma ressalva de `mobiauto` — **NÃO VERIFICADO** |
| `facebook_marketplace` | Nenhuma (regex sobre HTML renderizado só para extrair IDs de URL; sem parsing de preço/título/etc.) | `app/scrapers/facebook_marketplace.py`, `_extract_ids` | Não aplicável — escopo do scraper hoje é só descoberta de link |
| `turboclass` | CSS (`BeautifulSoup`, `.select("table tr")`, seletores de link) | `app/scrapers/turboclass.py:65-70,179-185` | **NÃO VERIFICADO** — não sondei página real do TurboClass |

**Achado principal:** `mobiauto` e `kavak` são candidatos concretos onde o código hoje **não tenta nenhum JSON embutido antes de cair para CSS via browser** — diferente de `mercadolivre`, `olx`, `gogarage` e `icarros`, que já priorizam JSON. Não dá para afirmar que essas páginas *têm* JSON disponível sem sondagem de rede (fora do orçamento desta auditoria), mas é o par mais provável de valer a pena investigar primeiro, porque já rodam **browser forçado** (ver 5.3) — se tiverem JSON embutido, poderiam sair do browser inteiramente.

### 5.3 Escada atual (curl_cffi → retry → browser) por fonte

O **fetch HTTP-first genérico** (`fetch_html_with_browser_fallback`, `app/scrapers/fetching.py:32-102`) implementa: tenta `fetch_html` (HTTP simples) → se bloqueado (`_is_blocked_error`, `:14-20`, baseado em `FetchBlocked`/mensagens de captcha/cloudflare), faz warmup via browser (`_fetch_browser`, `:52-61`) para renovar cookies → tenta HTTP de novo uma vez → só então usa o HTML do próprio browser como último recurso. Esse fluxo só roda quando `ctx.force_browser` é `False` (linha 65) — se for `True`, pula direto para o browser.

| Fonte | `fetch_mode` (builtins.py) | `default_force_browser` | Usa `curl_cffi` no HTTP path? | Observação |
|---|---|---|---|---|
| `mercadolivre` | http | não | **Sim** (`mercadolivre.py:34-54`, impersonate `chrome120`) | Ladder completo: curl_cffi → retry → browser fallback |
| `olx` | http | não | **Sim** (`olx.py:30`, `_OLX_IMPERSONATE`, linhas 309/616) | Ladder completo + escalonamento runtime próprio (ver 5.4) |
| `chavesnamao` | browser | **sim** | Não (usa `fetch_html_with_browser_fallback`/`fetch_html` de `base.py`, `requests` puro, quando não forçado; mas é forçado por default) | Sempre browser, nunca tenta HTTP/curl_cffi por padrão |
| `webmotors` (desabilitada) | browser | **sim** | Opcional, **desligado por padrão** (`webmotors_curl_cffi_enabled: False`, `builtins.py:155`) | Mesmo com curl_cffi ligado, é degrau extra opcional, não o padrão |
| `gogarage` | browser | **sim** | Não | Sempre browser |
| `icarros` | browser | **sim** | Não | Sempre browser |
| `mobiauto` | browser | **sim** | Não | Sempre browser |
| `kavak` | browser | **sim** | Não | Sempre browser |
| `facebook_marketplace` | browser | **sim** (Playwright-only, sem fallback HTTP no código) | Não | Sempre browser, sem ladder nenhum |
| `turboclass` | http | não | Não (usa `base.py`/`requests`) | Ladder existe (HTTP→browser fallback) mas sem TLS impersonation via curl_cffi |

**Conclusão:** de 9 fontes ativas por default, **apenas `mercadolivre` e `olx` usam curl_cffi de fato**; `turboclass` tem ladder HTTP→browser mas com `requests` simples (sem impersonation); as outras 6 (`chavesnamao`, `gogarage`, `icarros`, `mobiauto`, `kavak`, `facebook_marketplace`) **pulam a escada inteira e vão direto para Playwright em toda execução**, por `default_force_browser=True` (ou, no caso do Facebook, por não ter path HTTP implementado).

### 5.4 Onde o estado "precisa de browser" é memorizado: generalizado ou específico do OLX?

Existem **duas camadas distintas**, uma genérica e uma específica do OLX:

1. **Genérica (todas as fontes):** `source_configs.force_browser` (coluna DB, `app/services/source_configs_service.py:66,81,192,231,296,365,429`), lido em `build_scrape_context` e propagado para `ctx.force_browser`, usado em `fetching.py:65`. É um **toggle manual/admin**, persistente até ser trocado — não se auto-ajusta sozinho com base no comportamento recente da fonte (fora do que o `default_force_browser` do plugin já fixa por fonte, ver tabela 5.3).
2. **Específica do OLX:** um pequeno "health state" em processo (arquivo/lock local, não tabela DB), com funções dedicadas: `olx_health_record_http_ok` (`olx.py:88-94`, zera `force_browser_until_ts` quando HTTP volta a funcionar), `olx_health_record_browser_fallback` (`:97-105`, registra timestamps de fallback nas últimas 24h), `olx_health_force_browser` (`:108-114`, força browser por N horas, chamado em `:728` após algum gatilho de degradação), `olx_health_runtime_force_remaining_sec` (`:117-122`) e `olx_health_last_http_ok_ts` (`:125-129`). Essa é uma **escalada automática temporária e reversível**, exclusiva do OLX — nenhuma outra fonte tem esse mecanismo de auto-escalonamento por runtime health hoje.

**Resposta direta:** o estado "precisa de browser" tem uma camada genérica (flag manual por fonte, `source_configs.force_browser`) e uma camada de auto-escalonamento **específica do OLX**, não generalizada.

### 5.5 Avaliação do wreq como degrau intermediário

`wreq` não é usado em nenhum lugar do código hoje (`grep -rn "wreq" app/ docs/` só retorna a menção no próprio prompt desta auditoria) — não foi instalado nem testado, conforme instrução. Avaliação **apenas de código/risco, sem rede**:

- **Onde entraria:** como uma alternativa (ou terceira opção) dentro de `fetch_html_with_browser_fallback` (`app/scrapers/fetching.py:32`), antes do fallback para browser — no mesmo ponto onde hoje `fetch_html` (requests/curl_cffi conforme a fonte) já é a primeira tentativa. Para as fontes que hoje são `force_browser=True` por padrão (`chavesnamao`, `gogarage`, `icarros`, `mobiauto`, `kavak`), `wreq` poderia entrar como uma tentativa HTTP-first *antes* de forçar browser — mudando o comportammento de "sempre browser" para "tenta HTTP com impersonation melhor, cai para browser só se bloqueado", o que reduziria uso de Chromium se essas fontes toleram fingerprint melhor sem JS.
- **O que precisaria mudar:** (a) uma função de fetch equivalente a `fetch_html`/o bloco curl_cffi de `mercadolivre.py:34-54`/`olx.py:590-616`, mas usando `wreq`; (b) trocar `default_force_browser=True` para `False` nas fontes candidatas em `app/sources/builtins.py`, com `browser_fallback_enabled=True` mantido como rede de segurança; (c) validar campo a campo via `dual_run` (`app/scrapers/dual_run.py`) antes de promover, por fonte, como o próprio ADR de trilha v1/v2 já exige.
- **Risco:** wreq é uma biblioteca nova para o projeto (dependência adicional), sem histórico de uso aqui — risco de regressão de parsing se o fingerprint TLS/HTTP2 dela não bastar para essas fontes (o motivo original de tê-las como browser-first pode ser anti-bot que dependa de execução de JS, não só de fingerprint de rede, caso em que `wreq` não ajudaria e a mudança seria infrutífera). Isso só pode ser confirmado com teste real (autorizado apenas em venv separado, contra `robots.txt`, não executado nesta auditoria — **NÃO VERIFICADO**).

### 5.6 Fontes que usam browser hoje e estimativa de economia

Por 5.3, hoje usam Playwright/Chromium em **toda execução** (browser forçado): `chavesnamao`, `gogarage`, `icarros`, `mobiauto`, `kavak`, `facebook_marketplace` — **6 das 9 fontes ativas por padrão**. `webmotors` (desabilitada por padrão) também é browser-forced quando ligada. `mercadolivre`, `olx` e `turboclass` só usam browser como fallback (idealmente raro).

Estimativa qualitativa (não há número de RAM/CPU por processo Chromium documentado no repo hoje — busquei em `docs/OPERATIONS_RUNBOOK.md` e só há orientação operacional de monitorar RAM/processos Chromium via `scripts/pi_load_probe.sh`, sem valor fixo citável — **NÃO VERIFICADO**, precisaria medir no Pi real): cada execução de fonte browser-forced paga o custo fixo de um processo Chromium completo (`browser_timeout_ms` de 35-45s configurados por fonte, `builtins.py`) mesmo quando o HTML final teria dados estruturados extraíveis via HTTP simples. Se `mobiauto`/`kavak` (os dois sem nenhuma tentativa de JSON hoje, 5.2) confirmarem JSON embutido disponível numa sondagem futura, migrá-los para HTTP-first eliminaria 2 das 6 fontes browser-forced — uma redução proporcional de ~33% no número de fontes que pagam custo de Chromium por execução, sujeito à restrição do ADR de nunca aumentar uso de browser (a mudança proposta só reduz, nunca adiciona).

## 6. Backlog priorizado

Todos os itens abaixo são propostas de design, não specs criadas nem código implementado — nenhum arquivo em `specs/` foi criado nesta auditoria.

| # | Item | Impacto em captura | Impacto em eficiência | Esforço | Pré-requisito | Veredito |
|---|---|---|---|---|---|---|
| 1 | Monitor de field coverage por execução, reaproveitando `SourceRun.payload` (1.3), com alerta admin via `OperationalAlert`/`send_admin_text` quando taxa de preenchimento de campo crítico cair abaixo de limiar | Alto — teria detectado o bug do OLX (1.5) num intervalo de execuções, não em dias | Neutro (custo de 0 queries extras — cálculo é sobre dados já coletados em memória antes do upsert) | M | Nenhum (usa infra existente: `record_run`, `AppKV` de cooldown, canal admin) | **GO** — spec sugerida: `specs/024-field-coverage-monitor` — título "Monitor de preenchimento de campos críticos por execução de scraping"; critério de aceite: cada `SourceRun` grava taxa de preenchimento por campo crítico no `payload`; alerta admin dispara quando taxa cai abaixo de limiar configurável por fonte/campo, respeitando cooldown existente; teste cobre cenário do bug OLX histórico (campo zerado) disparando alerta em ≤1 execução |
| 2 | Estimativa de recall via sitemap Webmotors (marcas liberadas) comparando IDs do sitemap com `car_listings.external_id` já capturados, 1x/dia, fora de pico, sem requisição por listing (2.2 opção a) | Médio — só cobre Webmotors (marcas liberadas), mas dá primeira métrica real de recall no projeto | Baixo custo (1 fetch de sitemap/marca/dia + 1 query agregada IN) | M | Confirmar formato estável do sitemap ao longo de vários dias (não sondado hoje) | **GO** — spec sugerida: `specs/025-webmotors-sitemap-recall` — título "Estimativa de recall via sitemap Webmotors para marcas liberadas"; critério de aceite: job diário fora de pico busca sitemap por marca liberada, calcula `% de <loc> presentes em car_listings.external_id`, persiste métrica agregada (não por listing), sem novas requisições por item |
| 3 | Migrar `mobiauto`/`kavak` para HTTP-first se sondagem confirmar JSON embutido nas páginas de detalhe | Neutro/indireto (não muda captura, mas reduz risco de bloqueio por menos superfície de browser) | Alto — elimina até 2 de 6 fontes browser-forced (5.6) | P (troca de flag) a M (se precisar reescrever parser) | Sondagem de rede autorizada (fora do orçamento desta auditoria — próxima rodada) | **NEEDS-DATA** — não é possível abrir GO sem antes confirmar via sondagem (fora do escopo de rede desta auditoria, que ficou restrita a Webmotors/OLX) se `mobiauto.com.br`/`kavak.com.br` expõem `ld+json`/JSON embutido |
| 4 | Frequência adaptativa por URL de busca com base em taxa de novos anúncios (3.3), usando `first_seen`/cursor já existentes, 1 query agregada com `LIMIT` | Médio (reduz latência de alerta só para URLs "quentes", sem piorar as demais além do piso já existente) | Alto — reduz requisições/dia nas URLs "frias" (3.4) | G (envolve mudança de política de scheduling, testes de regressão em `run.py`) | Medir distribuição real quente/fria (3.4, NÃO VERIFICADO) antes de fixar os multiplicadores de intervalo | **NEEDS-DATA** — desenho está pronto, mas os parâmetros (mín/máx de intervalo, limiares) dependem de medir a distribuição real primeiro; abrir spec só após essa medição |
| 5 | Corrigir path `/api/v1/search/listings` do adapter OLX v2 antes de qualquer promoção para produção (4.2, risco de violar `Disallow: /api/`) | Nenhum diretamente, mas remove risco de regressão de compliance se v2/dual for ativado no futuro | Nenhum | P | Nenhum — é um ajuste isolado no adapter v2, hoje inativo | **GO** — spec sugerida: `specs/026-olx-v2-api-path-compliance` — título "Substituir endpoint `/api/` do adapter OLX v2 por caminho compatível com robots.txt"; critério de aceite: adapter v2 do OLX não referencia nenhum path sob `Disallow: /api/`; teste garante que nenhuma URL construída pelo v2 bate em `/api/`; `impl=v2`/`dual` continua bloqueado para OLX até essa correção ser mesclada |
| 6 | Avaliar `wreq` como degrau intermediário para as 5 fontes hoje `force_browser=True` sem tentativa de JSON (5.5) | Neutro/indireto | Potencialmente alto, mas incerto — depende se o anti-bot dessas fontes é de fingerprint (wreq ajudaria) ou de JS (wreq não ajudaria) | G (nova dependência + testes por fonte + validação via dual_run) | Teste isolado em venv separado, só contra `robots.txt`, fora desta auditoria; e resultado do item 3 (JSON embutido) — se as páginas já tiverem JSON, resolve o problema sem precisar de wreq | **NO-GO por ora** — risco de esforço alto sem garantia de ganho; priorizar item 3 (JSON embutido) primeiro, que é mais barato de verificar e pode tornar `wreq` desnecessário |
| 7 | Sitemap Webmotors como fonte de descoberta de IDs novos (não de dados), com extração dos campos ainda via browser (4.3) | Baixo/médio — só ajuda a saber quais anúncios existem mais cedo, sem depender da busca protegida por PerimeterX; não elimina a necessidade de browser para os dados em si | Baixo — reduz risco de bloqueio na busca, mas não reduz uso de Chromium (ainda precisa da página de detalhe via browser) | M | Confirmar estabilidade do sitemap ao longo de vários dias | **NEEDS-DATA** — o ganho real depende de quanto a busca protegida está de fato sendo um gargalo hoje para Webmotors (fonte desabilitada por padrão); não abrir spec até decisão de reativar Webmotors como prioridade |

## 7. Itens marcados NÃO VERIFICADO e como verificar

| # | Item | Onde aparece | Como verificar |
|---|---|---|---|
| 1 | Tempo real (histórico) que o bug do OLX ficou ativo em produção antes da correção da spec 021 | Seção 1.5 | Consultar histórico de deploy/PR da correção (spec 021) e cruzar com data de introdução da regressão via `git log`/`git blame` em `app/scrapers/olx.py` — fora do escopo de leitura desta auditoria (que focou em código atual, não histórico de commits) |
| 2 | Se existe hoje alguma fonte cujo v1 e v2 usam fontes de dado estruturalmente diferentes (não só parsers diferentes do mesmo HTML), o que tornaria o `dual_run` um proxy válido de recall | Seção 2.1/2.5 | Ler `run_v1_adapter`/`run_v2_adapter` de cada fonte em `app/scrapers/dual_run.py:9` e comparar a estratégia de coleta (API interna vs HTML vs sitemap) par a par |
| 3 | Distribuição real de "URLs de busca quentes vs frias" (proporção de novos anúncios por URL de wishlist) | Seção 3.4 | Rodar a consulta agregada proposta em 3.2 por um período (ex.: 2-4 semanas) antes de fixar limiares de frequência adaptativa |
| 4 | Se alguma fonte tem `source_configs.extra["impl"]` setado para `"v2"`/`"dual"` hoje em produção | Seção 5.1, 4.2 | Consultar a tabela `source_configs` no Supabase de produção (dado de runtime/DB, não visível por leitura de código) |
| 5 | Se as páginas de `chavesnamao`/`turboclass` expõem `ld+json`/JSON embutido não utilizado pelo parser atual (CSS) | Seção 5.2 | Sondagem de rede autorizada e orçada separadamente (esta auditoria restringiu rede a Webmotors/OLX); repetir metodologia da seção 4 com essas duas fontes |
| 6 | Se as páginas de `mobiauto.com.br`/`kavak.com.br` expõem JSON estruturado (`ld+json`, `__NEXT_DATA__` ou script embutido) que o parser atual (CSS puro) ignora | Seção 5.2, 5.6, backlog item 3 | Sondagem de rede autorizada e orçada separadamente; é o item de maior prioridade prática porque, se confirmado, permite eliminar 2 de 6 fontes browser-forced sem risco arquitetural |
| 7 | Risco real de `wreq` (fingerprint TLS/HTTP2 suficiente vs anti-bot dependente de JS) para as fontes candidatas | Seção 5.5, backlog item 6 | Teste isolado em venv separado, restrito a requisições contra `robots.txt` de cada fonte candidata, sem carga em produção |
| 8 | Número concreto de RAM/CPU por processo Chromium no Raspberry Pi (para quantificar economia de migrar fontes para HTTP-first) | Seção 5.6 | Medir no Pi real via `scripts/pi_load_probe.sh` durante uma execução normal de fonte browser-forced, conforme já orientado em `docs/OPERATIONS_RUNBOOK.md` |
| 9 | Se os outros 14 arquivos do índice de sitemap OLX (`sp/sitemap2.xml` … `sp/sitemap15.xml`, e os ~26 sitemaps de outros estados) seguem o mesmo padrão de navegação por categoria/localização (sem URLs de anúncio) encontrado em `sp/sitemap1.xml` | Seção 4.2.2 | Amostrar mais 1-2 arquivos do índice (dentro de um orçamento de rede futuro) para confirmar que o padrão é consistente antes de descartar definitivamente o sitemap OLX como fonte de descoberta |
| 10 | Estabilidade do formato/URL do sitemap Webmotors ao longo do tempo (se `<lastmod>` e a lista de marcas liberadas mudam com frequência) | Seção 4.1, backlog itens 2 e 7 | Repetir a sondagem da seção 4.1 em dias diferentes (ex.: semanalmente por um mês) antes de depender do sitemap como fonte de dado operacional |
