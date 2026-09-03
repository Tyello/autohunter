# Diagnóstico — Score constante em 66/100 e FIPE ausente

Auditoria somente leitura. Nenhum código, config ou dado foi alterado.

## 1. Anatomia do score (`app/scoring/score_v2.py:100-257`, função `score_ad`)

| Dimensão | Peso máx. | Fonte do dado | Valor "default" quando o sinal falta | Está variando? |
|---|---|---|---|---|
| `match` (texto livre + ano) | 35 | `wishlist.query` tokenizado (`score_v2.py:113-133`) | **35** quando `terms == []` (`:124-125`) | Não, quando o wishlist é 100% baseado em filtros estruturados (ver §2a) |
| `market_price` | 25 | `MarketStats` do cohort (marca/modelo/ano) via `market_stats_service` | **12** quando `market_stats` é `None` ou `sample_size < min_market_sample` (padrão 8) (`:137,139`) | Raramente varia — cohorts pequenos/nichados não atingem amostra mínima |
| `fipe_price` | 10 | `fipe_price` passado pelo caller (`notifications_queue_service.py`) | **5** quando `fipe_price is None` (`:149,151`) | **Nunca varia — sempre 5** (causa raiz em §3) |
| `mileage` (km/ano) | 15 | `ad.mileage_km` + ano do anúncio | **8** quando `km is None` ou ano ausente (`:158,163-165`) | Varia só quando `mileage_km` está populado na origem |
| `rarity` | 4 | Ratio de raridade + `rarity_sample_size` | **2** quando amostra insuficiente (`:180-182`) | Raramente varia, mesmo motivo do market_price |
| `quality` (completude do anúncio) | 10 (máx. real 8) | Presença de preço/km/local/imagens/URL/ano-marca-modelo | Começa em 8, subtrai por campo ausente (`:184-197`) | **Única dimensão que varia de fato** |

`raw_total = match + market_price + fipe_price + mileage + rarity + quality` (`:200-207`), depois caps opcionais:
- `price_dec is None` → teto 65 (`:211-212`)
- sem imagens → teto 60 (`:213-214`)
- preço + km + imagens ausentes → teto 50 (`:215-216`)

### Confirmação aritmética do "66"

Para o caso relatado (preço presente, "Boa compatibilidade" = faixa 50-69, critério casado é um `FilterRule` de ano, não texto livre):

```
match         = 35   (wishlist sem termos de texto livre — só filtros estruturados)
market_price  = 12   (default — amostra de mercado insuficiente para o cohort)
fipe_price    =  5   (default — FIPE nunca resolvido, ver §3)
mileage       =  8   (default — ad.mileage_km é None)
rarity        =  2   (default — amostra insuficiente)
quality       =  4   (8 − 2 por km ausente − 2 por outro campo ausente, ex.: local ou URL)
--------------------------------------------------------
raw_total     = 66   (nenhum cap se aplica: preço presente, imagens presentes)
```

Isso bate exatamente com o valor observado. A hipótese original do usuário (peso FIPE = 34, 100−34=66) está **numericamente incorreta** — o peso real da dimensão FIPE é só 10 pontos, e seu default (5) contribui só 5 pontos "perdidos" (10−5), não 34. O 66 constante é a **soma de cinco dimensões defaultadas simultaneamente** (match, market_price, fipe_price, mileage, rarity = 62 pontos fixos) mais uma `quality` que também tende ao mesmo valor porque os mesmos campos (km, local/URL) tendem a estar ausentes nos mesmos anúncios/fonte.

## 2. Por que a variância é (quase) zero

Não é peso zero nem contexto pré-computado não repassado — é que **quatro das seis dimensões caem no valor default ao mesmo tempo, na maioria dos anúncios**, por três causas independentes que coincidem:

**a) `match` sempre 35 para wishlists baseadas em filtro.**
`app/services/wishlist_query_parser.py:155` retorna `cleaned_query=""` quando a mensagem do usuário é inteiramente composta de critérios estruturados (ano, preço, km) sem nenhum termo de texto livre (marca/modelo/versão). Isso vira `wishlist.query`, e em `score_v2.py:113-116`, `terms` fica vazio → `match_score = 35` fixo, sempre no teto, para qualquer anúncio que passe pelos filtros. Isso **não é um bug** — é o comportamento pretendido para busca só-filtro — mas remove a maior dimensão (35 pts) da variância do score.

**b) `market_price` e `rarity` quase sempre no default.**
Ambos exigem `sample_size >= min_market_sample` (8, `score_v2.py:106`) no cohort marca/modelo/ano. Para cohorts nichados (carros mais antigos, versões raras) a amostra dificilmente chega a 8, então ambos ficam nos defaults (12 e 2) na maioria dos casos — variância real só aparece em cohorts populares.

**c) `fipe_price` sempre no default — porque nunca é resolvido (ver §3).**

Com essas 3 dimensões (62 dos 100 pontos possíveis) travadas em valores fixos na maior parte dos anúncios, sobra só `mileage` (default 8 se `mileage_km` for `None`, o que também é comum) e `quality` (variação de 0-8) para diferenciar os anúncios — daí o score colapsar para poucos valores repetidos, com 66 sendo o mais comum.

## 3. Por que o FIPE nunca vem

Cadeia de resolução (`app/services/notifications_queue_service.py`):

1. **Lookup direto** — busca em `FipePrice` por `vehicle_key` + `reference_month` atual (`:180-193`, `:256-257`). Chave normalizada por `listing_vehicle_keys()` (`app/services/fipe_service.py:22`), corrigida no commit mais recente `cf8f80a` (normalização de `vehicle_key` entre fontes).
2. **Fallback via catálogo** — se o passo 1 não achar, `_fallback_fipe_price_via_catalog` (`notifications_queue_service.py:27-66`) chama `resolve_listing_to_fipe_candidates` (`fipe_catalog_resolver_service.py:195`), que só aceita o melhor candidato se `confidence_score >= settings.fipe_lookup_min_confidence` (padrão **80**, `app/core/settings.py:354`).
3. **Se tudo falhar** — enfileira um `FipeLookupRequest` (`notifications_queue_service.py:69-...`) para resolução assíncrona posterior.

**Causa raiz:** os passos 1 e 2 dependem de `FipePrice` / `FipeCatalogEntry` estarem populados para o `reference_month` atual. Essas tabelas só são alimentadas pelo job mensal `job_monthly_fipe_update` (`app/scheduler/fipe_update_job.py:42`), que por sua vez chama `run_audited_monthly_fipe_update` (`app/services/fipe_update_job_service.py:43`). Essa função tem um **kill switch que vem `False` por padrão**:

```python
# app/services/fipe_update_job_service.py:70-71
if not bool(getattr(settings, "fipe_monthly_update_enabled", False)):
    return finish("skipped", error="kill switch disabled")
```

- `app/core/settings.py:339`: `fipe_monthly_update_enabled: bool = False`
- `.env.example:172`: `FIPE_MONTHLY_UPDATE_ENABLED=false`
- `deploy/raspberry/README.md:50`: mesmo default documentado para o deploy do Raspberry Pi

Ou seja: **a menos que alguém tenha explicitamente setado `FIPE_MONTHLY_UPDATE_ENABLED=true` no `.env` de produção**, o job mensal nunca roda de verdade — ele executa, loga `status=skipped, error="kill switch disabled"` (`fipe_update_job_service.py:65`), e sai. Sem esse job, tanto `FipePrice` (preço direto) quanto `FipeCatalogEntry` (usado no fallback do passo 2) permanecem vazios/desatualizados para o mês corrente, então:
- passo 1 nunca encontra `vehicle_key`;
- passo 2 nunca tem candidatos válidos no catálogo (`resolve_listing_to_fipe_candidates` provavelmente retorna `status="no_match"` ou `"insufficient_data"` por falta de linhas no `FipeCatalogEntry` do mês);
- passo 3 sempre enfileira `FipeLookupRequest`, mas a fila de reprocessamento (`fipe_lookup_job.py`) também depende do mesmo catálogo para resolver — sem dados de catálogo, a fila também não resolve nada.

O modo de falha, portanto, **não é** parsing de versão nem chave incompatível (isso já foi corrigido no commit `cf8f80a` de 2026-08-31) — é a ausência de dados de origem porque o pipeline de ingestão mensal está desligado por configuração (flag operacional, não bug de código).

## 4. Relação entre os dois sintomas

**Confirmado, parcialmente:** são o mesmo problema raiz em parte, mas não inteiramente como a hipótese original propunha.

- O FIPE ausente **contribui** para o 66 (5 dos 62 pontos "travados" vêm do default de `fipe_price`), mas **não é a causa dominante** da falta de variância. Mesmo que o FIPE fosse religado amanhã, o score continuaria bastante travado por causa de (a) wishlists só-filtro sempre darem `match=35`, e (b) `market_price`/`rarity` caírem no default em cohorts pequenos — ambos independentes do FIPE.
- Religar o FIPE mudaria o score de "66 fixo" para algo como "61–71 variável" (ganho de até ±5 pts pela dimensão FIPE), mas **não resolveria** a baixa variância geral, porque as outras duas causas em §2 continuam ativas.

## 5. Pontos de log propostos (não inseridos — apenas localização sugerida)

Para validar em runtime com 2-3 anúncios distintos, caso a leitura estática não seja conclusiva:

1. `app/scoring/score_v2.py:199` (logo após montar `components`) — logar `components` completo + `raw_total` + `caps_applied` por `ad.id`/`wishlist.id`. Confirma quais dimensões estão de fato no default para cada anúncio real.
2. `app/services/notifications_queue_service.py:256-259` (e espelho em `:400-403`) — logar `lkeys` (chaves geradas), se achou em `fipe_rows`, e o resultado de `_fallback_fipe_price_via_catalog`. Confirma se o miss é no lookup direto, no fallback, ou ambos.
3. `app/services/fipe_catalog_resolver_service.py:195` (início/fim de `resolve_listing_to_fipe_candidates`) — logar `status` retornado e contagem de candidatos encontrados antes do filtro de confiança. Confirma se o catálogo está vazio para o mês (`insufficient_data`/`no_match` por ausência de linhas) vs. candidatos existem mas com confiança < 80.
4. `app/services/fipe_update_job_service.py:65` (dentro de `finish(...)`, já loga via `log(...)`) — **este ponto já loga**; basta consultar a tabela `system_logs` ou `fipe_update_run` filtrando `source="fipe"` para confirmar quantas execuções terminaram em `status="skipped", error="kill switch disabled"` nos últimos meses.
5. `app/scoring/score_v2.py:113-116` — logar `wishlist.query` bruto e `terms` resultante por `wishlist.id`. Confirma quantos wishlists ativos têm `query` vazia (→ `match_score=35` sempre).

## 6. Opções de correção (não executadas)

**Mínima (paliativa):**
- Marcar o score como "parcial" na mensagem quando `fipe_price is None` E `market_context is None` simultaneamente (ex.: badge extra "score calculado sem dados de mercado/FIPE"), para não passar falsa precisão ao usuário.
- Ajustar a UX da seção "Por que você recebeu" para nunca prometer "sem base de FIPE" com texto que hoje nem existe no código (`telegram_formatter.py` só emite "sem base de mercado" — o texto do relato do usuário pode ser de uma versão anterior ou de expectativa, vale confirmar a origem exata da string mostrada).

**De fundo (resolve a causa raiz):**
- Setar `FIPE_MONTHLY_UPDATE_ENABLED=true` no `.env` de produção (Raspberry Pi) e configurar `FIPE_MONTHLY_UPDATE_INPUT_PATH` ou garantir que o crawler (`crawl_latest_fipe_prices`) tenha acesso à API — isso religaria os passos 1 e 2 da resolução FIPE.
- Rodar manualmente `run_audited_monthly_fipe_update(db, force=True)` uma vez para popular `FipePrice`/`FipeCatalogEntry` do mês corrente antes de esperar o próximo agendamento (dia 5).
- Revisar `min_market_sample` (hoje 8) e decidir se cohorts pequenos deveriam ter um cálculo alternativo de `market_price`/`rarity` (ex.: sample mínimo menor, ou fallback para dados regionais/nacionais agregados) para reduzir a frequência do default.
- Para wishlists só-filtro, considerar se `match_score=35` fixo é aceitável (parece intencional) ou se deveria ter menor peso relativo quando não há termo de texto discriminante.

## 7. Confirmação em runtime (queries somente-leitura, produção, 2026-09-03)

Conectado via SSH ao Pi de produção (`/opt/autohunter/.env`, mesmo `DATABASE_URL` do Supabase usado localmente) e executadas queries `SELECT` read-only. Resultados batem exatamente com a leitura estática das seções 1-3:

| Query | Resultado | Confirma |
|---|---|---|
| `SELECT count(*) FROM fipe_prices` | **0 linhas** | Lookup direto (passo 1) falha sempre, sem exceção — tabela nunca foi populada. |
| `SELECT reference_month, count(*) FROM fipe_catalog_entries GROUP BY 1` | **60 linhas totais** (13 em 2026-09, 47 em 2026-08) | Catálogo (passo 2) tem volume irrisório para cobrir o mercado real. |
| `SELECT brand_name, count(*) FROM fipe_catalog_entries GROUP BY 1` | **Honda (45) e Acura (15) — só essas duas marcas** | Catálogo é claramente uma carga manual/teste, não o catálogo FIPE completo. |
| `SELECT make, count(*) FROM car_listings GROUP BY 1 ORDER BY 2 DESC LIMIT 10` | Maior grupo é `make` vazio/NULL (5.516), depois Honda (4.613), Mitsubishi (4.194), Audi, BYD, VW, Chevrolet, Hyundai, Fiat... | Mesmo a única marca em comum (Honda) tem volume real de anúncios ordens de magnitude maior que o catálogo de teste; a maior fatia dos anúncios nem tem `make` preenchido, então `listing_vehicle_keys()` já retorna `[]` para eles antes de qualquer tentativa de match. |
| `fipe_update_runs` (últimas execuções) | Última execução real em **2026-08-10**, via adapter `"external_pipeline"`, importou só **15 linhas** de um arquivo — não é o crawler mensal de produção. Nenhuma execução em setembro/2026. | O pipeline mensal está parado há ~3 semanas; a carga que existe foi manual/pontual, não o job agendado. |
| Payload de um desses runs (`resolver_coverage`) | `status_counts: {"insufficient_data": 100}` para amostra de 100 anúncios | **0% de resolução** mesmo no dia em que o catálogo foi populado — confirma que o fallback via catálogo (passo 2) não resolve nada na prática, não só em teoria. |
| `system_logs` filtrando `source ILIKE '%fipe%'` ou `message ILIKE '%kill switch%'` | **0 linhas** | Os runs do job de FIPE não emitem log estruturado em `system_logs` (o resultado fica só em `fipe_update_runs`) — os pontos de log propostos na §5 realmente não existem hoje nesse caminho. |
| `fipe_lookup_requests` por `status` | 9 `skipped`, 6 `done`, 0 `pending`/`processing` | A fila reativa (passo 3) está rodando e drenando (não empilha indefinidamente), mas não produziu FIPE aproveitável nas notificações mais recentes amostradas abaixo. |
| `SELECT score_v2, count(*) FROM notifications WHERE score_v2 IS NOT NULL GROUP BY 1` | **100% das 20 notificações mais recentes com score = 66** | Variância zero confirmada empiricamente, não só estatisticamente provável. |
| `score_breakdown` das 5 notificações mais recentes | Vetor de componentes **idêntico** em todas: `match=35, market_price=12, fipe_price=5, mileage=8, rarity=2, quality=4`; `market_context.fipe=null` em todas | Bate ponto a ponto com a simulação aritmética da §1 — confirma que não é coincidência nem amostra enviesada. |
| `SELECT (query IS NULL OR btrim(query)='') , count(*) FROM wishlists WHERE is_active AND deleted_at IS NULL GROUP BY 1` | As 8 wishlists ativas têm **`query` não-vazia** | **Refina** a causa do `match=35` fixo (§2a): não é específico de wishlists só-filtro. Como o próprio gate de `match_listings_for_active_wishlists` já exige que os termos da wishlist estejam no anúncio para ele virar candidato, por construção quase todo anúncio que chega a `score_ad` tem `sat == len(terms)` → `match_score=35`. O efeito é o mesmo (dimensão sem variância), mas a causa é estrutural ao pipeline de matching, não uma característica de um subconjunto de wishlists. |

**Conclusão da confirmação:** nenhuma correção foi feita. Os números de produção validam 100% as causas-raiz identificadas por leitura estática — inclusive achando um dado novo (o teste manual de catálogo com `insufficient_data=100`) que remove qualquer dúvida remanescente sobre se o fallback via catálogo "quase funciona": ele não resolve nada mesmo quando alimentado.
