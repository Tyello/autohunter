# Spec 009 — FIPE bootstrap: popular todos os modelos candidatos por ano (bugfix)

`[spec-kit: T2 — 6pts: arquivos=1, decisões=2, risco=1, novidade=1, verif=1]`

## Bug observado em produção

Wishlist "honda fit s" (year_lte=2008, sem year_gte explícito → anos-alvo 2004-2008). Logs (`system_logs`, component=`fipe_lookup`) mostraram os 5 anos como `skipped_year`, `final_status="skipped"`, sem nenhum `bootstrapped` nem `api_error`.

**Causa raiz** (confirmada rodando `_resolve_fipe_brand_and_model` contra a API FIPE real, ver histórico da sessão):
- `_resolve_fipe_brand_and_model(client, make="Honda", model="fit s")` escolhe **um único** modelo via `_match_fipe_catalog_item` (tie-break: menos tokens extras, depois ordem da lista da API).
- Para "fit s", o token "s" é descartado como ruído (`important_vehicle_tokens` ignora tokens de 1 char), sobrando só `{"fit"}` — que casa com **19 variantes diferentes** do Honda Fit na API real (CX, DX, EX, EXL, LX, Twist, etc., de várias gerações).
- O desempate escolheu "Fit CX 1.4 Flex 16V 5p Aut." (Value 6613), que só existe no ano **2014** na FIPE.
- Essa resolução fica **cacheada para o request inteiro** (`bootstrap_attempted`/`bootstrap_resolved`, comportamento intencional de spec 008, REQ-006/009 — evita chamadas de API repetidas). Como o modelo escolhido não tem NENHUM dos anos 2004-2008, todos os 5 anos falham com `skipped_year`, e como a resolução não é re-tentada, não há segunda chance.

**Decisão do usuário (verbatim, autorizando este fix)**: *"nesse caso o honda fit s é o honda fit 1.5 - mas acho que vale a pena trazer todos os modelos disponíveis de cada ano, e dai fazemos o match quando tiver o anúncio para mostrar"* — ou seja: não tentar adivinhar a trim exata durante o bootstrap da wishlist (que não tem dados suficientes pra desambiguar: só marca/modelo/ano, sem versão). Em vez disso, popular o catálogo com **todos** os modelos candidatos que casam com a query, para cada ano-alvo que tiverem disponível — o matching fino (usando `score_fipe_candidate`/`resolve_listing_to_fipe_candidates`, já existente e usado tanto aqui quanto no matching de anúncios reais via `build_fipe_resolver_coverage_report`) acontece depois, quando há um anúncio real com dados de versão para desambiguar.

## Objetivo

Substituir a resolução "brand + 1 modelo" por "brand + lista de modelos candidatos", e o bootstrap de "1 entry" por "N entries, uma por combinação (modelo candidato × combustível) que exista para aquele ano", cacheando `get_model_years` por modelo candidato (não por ano) para reaproveitar entre os anos-alvo do mesmo request.

## Não-objetivos

- Não mexer em `score_fipe_candidate`, `find_fipe_catalog_candidates`, `resolve_listing_to_fipe_candidates` (matching de anúncios reais — já funciona e é reaproveitado como está).
- Não mexer em `fipe_monthly_sync_service.py` nem no pipeline mensal.
- Não mudar a lógica de `_match_fipe_catalog_item` usada para **marca** (continua sendo 1 único match — marca não tem ambiguidade de trim).
- Não adicionar cache persistente entre requests diferentes (o cache de `get_model_years` por modelo é só uma dict local ao processamento de UM `FipeLookupRequest`, como já é `bootstrap_attempted`/`bootstrap_resolved` hoje).
- Não adicionar novo status de outcome — `"bootstrapped"` continua sendo usado (agora significa "≥1 entry criada para este ano", não "exatamente 1").

## Premissas assumidas

- **PREM-01**: `MAX_BOOTSTRAP_MODEL_CANDIDATES = 25`. Justificativa: a query real "honda fit s" casou 19 modelos reais na API FIPE; 25 dá margem sem permitir explosão de chamadas de API para marcas com catálogos muito grandes (ex.: queries genéricas demais). Candidatos além do cap são descartados (mesma ordem de desempate já usada: menos tokens extras, depois ordem da lista da API).
- **PREM-02**: erro de API (`FipeApiError`) em qualquer chamada (`get_model_years` ou `get_price`) durante a população de um ano é **fail-fast**: propaga para cima e usa o mecanismo existente `_apply_bootstrap_api_error` (rollback + `request.attempts += 1` + retry/failed conforme `fipe_lookup_max_attempts`). Não faz "swallow" por candidato. Justificativa: entries já commitadas por candidatos anteriores no mesmo ano permanecem válidas (`upsert_fipe_catalog_entries` commita por chunk, dentro do próprio helper), então nenhum trabalho é perdido; e um outage real da API FIPE deve continuar acionando o retry existente, não ser mascarado como "não achei nada".
- **PREM-03**: quando `get_model_years` de um modelo candidato retorna múltiplas variantes de combustível para o mesmo ano-alvo (ex.: "2019 Gasolina" e "2019 Flex"), TODAS são persistidas como entries separadas (mesma identity_key diferenciada por combustível, já suportado por `upsert_fipe_catalog_entries`) — não só a primeira.
- **PREM-04**: o outcome logado em `system_logs`/`request.status` não muda de formato — continua `"bootstrapped"` (se ≥1 entry criada para o ano) ou `"skipped_year"` (se 0). O request não guarda mais qual entry específica "venceu" (já não guardava antes — ver histórico: `done`/`refreshed` também não persistem `catalog_entry_id` em lugar nenhum).

## Contratos

### `_match_all_fipe_catalog_items` (nova função, substitui o uso de `_match_fipe_catalog_item` para modelos)

```python
MAX_BOOTSTRAP_MODEL_CANDIDATES = 25

def _match_all_fipe_catalog_items(items: list[dict], query_text: str, *, label_key: str = "Label") -> list[dict]:
    """
    Retorna TODOS os items cujo token-set (via important_vehicle_tokens) contém query_tokens
    (issubset), ordenados por (menos tokens extras primeiro, depois ordem original da lista),
    truncados em MAX_BOOTSTRAP_MODEL_CANDIDATES. Lista vazia se query_tokens vazio ou nenhum match.

    Reaproveita a MESMA lógica de containment/desempate de _match_fipe_catalog_item (não duplicar
    a normalização — importar important_vehicle_tokens já usado por ela), mas retornando todos os
    matches em vez de só o primeiro.
    """
```
- `_match_fipe_catalog_item` (usada para marca) **permanece intocada**.

### `_resolve_fipe_brand_and_models` (substitui `_resolve_fipe_brand_and_model`)

```python
def _resolve_fipe_brand_and_models(
    client: FipeApiClient, *, make: str, model: str
) -> tuple[dict, list[dict], int] | None:
    """
    1. reference_table = client.get_latest_reference_table(); reference_code = reference_table["Codigo"].
    2. brands = client.get_brands(reference_code); brand = _match_fipe_catalog_item(brands, make).
       Se brand is None -> return None (NÃO chama get_models).
    3. models = client.get_models(reference_code, brand["Value"]).
       candidates = _match_all_fipe_catalog_items(models, model).
       Se candidates vazio -> return None.
    4. Return (brand, candidates, reference_code).

    Propaga FipeApiError sem capturar (igual à função anterior).
    """
```

### `_bootstrap_fipe_catalog_entries_for_year` (substitui `_bootstrap_fipe_catalog_entry`)

```python
def _bootstrap_fipe_catalog_entries_for_year(
    db: Session,
    client: FipeApiClient,
    *,
    brand: dict,
    model_candidates: list[dict],
    reference_code: int,
    year: int,
    model_years_cache: dict[str, list[dict]],
) -> int:
    """
    Para o `year` dado, itera model_candidates NA ORDEM recebida (já vem ordenada por relevância
    de _match_all_fipe_catalog_items) e cria uma entry de catálogo para CADA combinação
    (modelo, combustível) que exista para esse ano em qualquer candidato. Retorna quantas entries
    foram criadas/atualizadas.

    Para cada model_item em model_candidates:
      1. model_value = model_item["Value"]
      2. Se model_value NÃO estiver em model_years_cache:
         model_years_cache[model_value] = client.get_model_years(reference_code, brand["Value"], model_value)
         (propaga FipeApiError sem capturar — fail-fast, PREM-02)
      3. years_for_model = model_years_cache[model_value]
      4. matches = [y for y in (years_for_model or []) if str(y.get("Value","")).split("-",1)[0] == str(year)]
      5. Para CADA year_item em matches (PREM-03 — todas as variantes de combustível):
         a. value = str(year_item.get("Value") or ""); fuel_code = value.split("-",1)[1] if "-" in value else value
         b. price_data = client.get_price(reference_code=reference_code, brand_code=brand["Value"],
            model_code=model_value, model_year=year, fuel_code=fuel_code)
            (propaga FipeApiError sem capturar — fail-fast, PREM-02)
         c. raw_row = {
              "tipo_veiculo": "car", "marca": price_data.get("Marca"), "modelo": price_data.get("Modelo"),
              "ano": price_data.get("AnoModelo"), "combustivel": price_data.get("Combustivel"),
              "codigo_fipe": price_data.get("CodigoFipe"), "valor": price_data.get("Valor"),
              "codigo_marca": brand["Value"], "codigo_modelo": model_value, "codigo_ano": value,
            }
         d. current_month = datetime.now(timezone.utc).strftime("%Y-%m")
         e. normalized = normalize_external_fipe_row(raw_row, reference_month=current_month)
            Se None -> raise FipeApiError("resposta da API FIPE não pôde ser normalizada durante bootstrap")
         f. upsert_fipe_catalog_entries(db, [normalized], reference_month=current_month, source="on_demand_bootstrap")
         g. created += 1

    Return created (int, pode ser 0 se nenhum candidato tinha o ano).
    """
```

### Integração em `_process_one_fipe_lookup` (bloco de bootstrap dentro do loop de `target_years`)

Estado inicializado antes do loop (substitui as vars atuais):
```python
bootstrap_attempted = False
bootstrap_resolved = None          # agora: tuple(brand, model_candidates_list, reference_code) | None
bootstrap_client = None
model_years_cache: dict[str, list[dict]] = {}   # NOVO — cache por modelo, cross-year dentro do request
```

Dentro do `if result["status"] == "insufficient_data" or best is None:`:
```python
if not bootstrap_attempted and pseudo_listing.make and pseudo_listing.model and year is not None:
    bootstrap_attempted = True
    bootstrap_client = FipeApiClient()
    try:
        bootstrap_resolved = _resolve_fipe_brand_and_models(
            bootstrap_client, make=pseudo_listing.make, model=pseudo_listing.model
        )
    except FipeApiError as exc:
        return _apply_bootstrap_api_error(db, request, wishlist, outcomes, year, exc)

if bootstrap_resolved:
    brand, model_candidates, reference_code = bootstrap_resolved
    try:
        created_count = _bootstrap_fipe_catalog_entries_for_year(
            db, bootstrap_client, brand=brand, model_candidates=model_candidates,
            reference_code=reference_code, year=year, model_years_cache=model_years_cache,
        )
    except FipeApiError as exc:
        return _apply_bootstrap_api_error(db, request, wishlist, outcomes, year, exc)
    if created_count > 0:
        outcomes.append({"year": year, "status": "bootstrapped", "confidence_score": None})
        if final_outcome is None:
            final_outcome = "bootstrapped"
        continue

outcomes.append({"year": year, "status": "skipped_year", "confidence_score": None})
continue
```

O resto de `_process_one_fipe_lookup` (contadores, `final_status`, `system_logs`, decisão final de `request.status`) **não muda**.

## Plano de testes

Arquivo: `tests/test_fipe_on_demand_lookup_service.py`.

**Remover/substituir** (contrato mudou, testes ficam obsoletos):
- `test_resolve_fipe_brand_and_model_success` → `test_resolve_fipe_brand_and_models_success`: FakeClient com get_brands (1 match) e get_models (3 candidatos casando o token de query, 1 não casando) → retorna `(brand, [candidatos ordenados], reference_code)`, lista não inclui o não-candidato.
- `test_resolve_fipe_brand_and_model_returns_none_when_brand_not_found` → adaptar nome, mesma lógica (get_models nunca chamado).
- `test_resolve_fipe_brand_and_model_returns_none_when_model_not_found` → adaptar: get_models retorna itens, nenhum casa os tokens → None.
- **Novo**: `test_resolve_fipe_brand_and_models_caps_at_max_candidates`: FakeClient.get_models retorna 30 itens todos casando o token de query → resultado tem exatamente `MAX_BOOTSTRAP_MODEL_CANDIDATES` (25) itens.
- `test_bootstrap_creates_new_catalog_entry` → `test_bootstrap_creates_entries_for_all_matching_candidates`: 2 model_candidates, ambos com o ano-alvo disponível (1 variante de combustível cada) → `_bootstrap_fipe_catalog_entries_for_year` retorna 2, 2 linhas em `fipe_catalog_entries` (uma por modelo).
- **Novo**: `test_bootstrap_creates_entry_per_fuel_variant` (PREM-03): 1 model_candidate cujo `get_model_years` retorna 2 variantes pro mesmo ano (ex. "2019-1" e "2019-3") → retorna 2, 2 linhas com `fuel` diferente, mesmo `model_code`.
- `test_bootstrap_returns_false_when_year_not_found` → `test_bootstrap_returns_zero_when_no_candidate_has_year`: nenhum candidato tem o ano → retorna 0, `get_price` nunca chamado.
- **Novo**: `test_bootstrap_caches_model_years_across_years_within_request`: chama `_bootstrap_fipe_catalog_entries_for_year` duas vezes (anos diferentes) passando o MESMO `model_years_cache` dict e os MESMOS `model_candidates` → `get_model_years` só é chamado 1x por modelo candidato no total (assert de contador), não 2x.

**Adaptar os testes de integração** (via `process_pending_fipe_lookups`) para o novo shape do FakeClient (`get_models` retornando lista com >=1 candidato relevante em vez de 1 modelo fixo):
- `test_process_attempts_bootstrap_when_no_local_candidate` — manter intenção (ano sem candidato local → bootstrap cria entry, `out["bootstrapped"] == 1`, `request.status == "done"`); ajustar FakeClient pro novo shape (get_models com 1 candidato relevante é suficiente pra manter o teste simples).
- `test_process_skips_year_when_brand_not_matched` — manter (get_brands sem match → `_resolve_fipe_brand_and_models` retorna None → skipped_year).
- `test_process_reuses_resolved_brand_model_across_years` — renomear pra `..._reuses_resolved_brand_models_across_years`; manter asserção de que `get_brands`/`get_models` só são chamados 1x no request inteiro (cache de `bootstrap_resolved`), AGORA também assertar que `get_model_years` por modelo não é rechamado entre anos (usa o `model_years_cache`).
- `test_process_bootstrap_api_error_stops_loop_and_retries` — manter (erro em `get_model_years` ou `get_price` durante a população do ano → `_apply_bootstrap_api_error` acionado, `request.attempts` incrementado, loop para).
- `test_process_does_not_retry_brand_resolution_after_no_match` — manter (já cobre o cache de resolução; comportamento não muda).
- **Novo**: `test_process_bootstraps_multiple_entries_when_two_candidates_match_year`: wishlist "honda fit" (sem trim ambígua no query), FakeClient.get_models com 2 candidatos "Fit" que casam o token e ambos têm o ano-alvo → após o request, 2 linhas em `fipe_catalog_entries` pro ano, `out["bootstrapped"] == 1` (é o count de REQUESTS bootstrapped, não de entries — conferir contrato atual de `out` em `process_pending_fipe_lookups` antes de assumir).

Validação de cada etapa: `py -m pytest tests/test_fipe_on_demand_lookup_service.py -q` deve terminar 100% passando (pode haver MAIS de 45 testes ao final, dado os novos). Nenhuma regressão nos módulos fora deste arquivo.

## Grafo de dependências (etapas sequenciais — mesmo arquivo)

1. **Etapa 1**: `_match_all_fipe_catalog_items` + `_resolve_fipe_brand_and_models` (substituindo `_resolve_fipe_brand_and_model`) + testes correspondentes.
2. **Etapa 2**: `_bootstrap_fipe_catalog_entries_for_year` (substituindo `_bootstrap_fipe_catalog_entry`) + testes correspondentes (depende da Etapa 1 pro shape de `brand`/`model_candidates`).
3. **Etapa 3**: integração em `_process_one_fipe_lookup` (bloco do loop + `model_years_cache`) + adaptação dos testes de integração existentes + novo teste multi-candidato (depende das Etapas 1-2).
4. **Etapa 4**: regressão completa (`pytest tests/ -q`) + remoção de qualquer função/teste órfão das versões antigas (`_resolve_fipe_brand_and_model`, `_bootstrap_fipe_catalog_entry` — NÃO devem sobrar não usadas).

## Riscos

| Risco | Mitigação |
|---|---|
| Explosão de chamadas de API para queries de marca/modelo muito genéricas | PREM-01 (cap de 25 candidatos) |
| Outage real da API FIPE mascarado como "sem match" | PREM-02 (fail-fast, propaga erro, retry existente continua funcionando) |
| Duplicar entries já existentes do pipeline mensal | `upsert_fipe_catalog_entries` já é idempotente por `identity_key` — reaproveitado sem mudança |
| Funções antigas (`_resolve_fipe_brand_and_model`, `_bootstrap_fipe_catalog_entry`) ficarem órfãs no código | Etapa 4 explicitamente remove qualquer resquício |

## Análise de consistência (T2)

- Todo REQ coberto por pelo menos um teste (ver Plano de testes).
- Nenhuma etapa depende de artefato que uma etapa anterior não cria.
- Contratos e exemplos de pseudocódigo consistentes entre si (conferidos contra o código real atual do arquivo antes de escrever esta spec).
- Nenhuma frase delega julgamento ao executor — toda decisão (cap, fail-fast, múltiplos combustíveis) já está resolvida nas premissas.
