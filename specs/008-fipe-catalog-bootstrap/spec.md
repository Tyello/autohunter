# Spec: Bootstrap on-demand de FipeCatalogEntry para marca/modelo desconhecidos  [spec-kit: T3 — 9pts: arquivos=1(2-4), decisões=2, risco=2, novidade=1(variação de padrão existente), verif=2]

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Verificação final: spec-verifier independente (obrigatório em T3), fix loop máx. 3 iterações
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 20 iterações totais
- Parada: veredito APROVADO do verifier | orçamento estourado → humano
- Registro: specs/008-fipe-catalog-bootstrap/RUN.md (append-only)

## Objetivo
Hoje o loop de lookup on-demand (`_process_one_fipe_lookup` em `app/services/fipe_on_demand_lookup_service.py`, spec 007) só consegue **atualizar** uma `FipeCatalogEntry` já existente e stale (`_refresh_fipe_catalog_entry`, exige `brand_code`/`model_code` já conhecidos). Quando a marca/modelo de uma wishlist nunca foi sincronizada pelo pipeline mensal, `resolve_listing_to_fipe_candidates` sempre retorna `no_match`/`insufficient_data` e o ano é marcado `skipped_year` para sempre — mesmo que a FIPE tenha esse veículo. Requisito explícito do usuário: uma busca nova deve **criar** entradas novas no catálogo ao vivo, sob demanda, sem baixar toda a base de marcas/modelos da FIPE antecipadamente (população lazy). Esta spec adiciona um caminho de bootstrap: quando um ano-alvo não encontra nada no catálogo local, tenta localizar marca e modelo na API FIPE por correspondência determinística de tokens (`get_brands` → `get_models` → `get_model_years` → `get_price`) e, se resolvido com confiança, persiste uma `FipeCatalogEntry` nova via `upsert_fipe_catalog_entries` (que já suporta insert). Resultado esperado: uma wishlist para marca/modelo nunca visto ganha cobertura FIPE já na primeira execução do lookup, sem exigir sincronização mensal prévia.

## Requisitos
- REQ-001: QUANDO, para um ano-alvo, `resolve_listing_to_fipe_candidates` retorna `best_candidate is None` (status `no_match` ou `insufficient_data`) E `pseudo_listing.make` E `pseudo_listing.model` estão preenchidos E `year is not None` E ainda não houve tentativa de resolução de marca/modelo nesta *request* (`FipeLookupRequest`), O SISTEMA DEVE chamar `_resolve_fipe_brand_and_model` para tentar localizar marca e modelo via API FIPE antes de marcar `skipped_year` — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_process_attempts_bootstrap_when_no_local_candidate -q`
- REQ-002: QUANDO a correspondência de marca OU de modelo não é encontrada (nenhum item cujo conjunto de tokens contenha todos os tokens da query) em `_match_fipe_catalog_item`, O SISTEMA DEVE retornar `None` de `_resolve_fipe_brand_and_model` sem levantar exceção, e o ano correspondente DEVE ser marcado `skipped_year` — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_match_fipe_catalog_item_returns_none_when_no_containment tests/test_fipe_on_demand_lookup_service.py::test_process_skips_year_when_brand_not_matched -q`
- REQ-003: QUANDO múltiplos itens contêm todos os tokens da query em `_match_fipe_catalog_item`, O SISTEMA DEVE escolher o item com menor quantidade de tokens extras (`len(item_tokens) - len(query_tokens)`), e em empate residual o primeiro da lista de entrada — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_match_fipe_catalog_item_prefers_fewest_extra_tokens tests/test_fipe_on_demand_lookup_service.py::test_match_fipe_catalog_item_tiebreaks_by_list_order -q`
- REQ-004: QUANDO marca e modelo são resolvidos com sucesso, O SISTEMA DEVE, para o ano-alvo corrente, chamar `_bootstrap_fipe_catalog_entry` que busca em `get_model_years` a combinação cujo ano-prefixo de `Value` bate com o ano-alvo (primeira ocorrência da lista quando houver mais de uma), busca o preço via `get_price` e persiste uma `FipeCatalogEntry` nova via `upsert_fipe_catalog_entries(..., source="on_demand_bootstrap")` — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_bootstrap_creates_new_catalog_entry -q`
- REQ-005: QUANDO `get_model_years` não retorna nenhuma combinação cujo ano-prefixo bata com o ano-alvo, O SISTEMA DEVE marcar esse ano como `skipped_year` (outcome, não erro) sem chamar `get_price` nem abortar o loop — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_bootstrap_returns_false_when_year_not_found -q`
- REQ-006: QUANDO marca e modelo já foram resolvidos com sucesso nesta *request* (cache local ao escopo de `_process_one_fipe_lookup`), O SISTEMA DEVE reaproveitá-los nos anos-alvo seguintes sem repetir `get_reference_tables`/`get_brands`/`get_models` — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_process_reuses_resolved_brand_model_across_years -q`
- REQ-007: QUANDO qualquer chamada à API FIPE durante a resolução de marca/modelo OU durante `_bootstrap_fipe_catalog_entry` levanta `FipeApiError`, O SISTEMA DEVE tratar exatamente como o fluxo de `api_error` já existente para refresh (outcome `api_error`, `db.rollback()`, incrementa `request.attempts`, decide `failed`/`pending` conforme `settings.fipe_lookup_max_attempts`, grava `system_logs` e retorna `"failed_final"`/`"failed_temp"`) — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_process_bootstrap_api_error_stops_loop_and_retries -q`
- REQ-008: QUANDO uma `FipeCatalogEntry` é criada com sucesso via bootstrap para um ano, O SISTEMA DEVE registrar `{"year": year, "status": "bootstrapped", "confidence_score": None}` na lista `outcomes` gravada em `system_logs` (payload `component="fipe_lookup"`) e considerar esse ano como sucesso na decisão final da request (`final_status = "done"`, valor de retorno da função `"bootstrapped"` quando for o primeiro sucesso) — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_process_logs_bootstrapped_outcome tests/test_fipe_on_demand_lookup_service.py::test_process_returns_bootstrapped_when_first_success -q`
- REQ-009: QUANDO a marca/modelo NÃO são resolvidos com sucesso (retorno `None` de `_resolve_fipe_brand_and_model`), O SISTEMA DEVE marcar essa tentativa como concluída (cache "sem match") para não repetir `get_brands`/`get_models` nos anos-alvo seguintes da mesma request, mesmo que nenhuma entry tenha sido criada — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py::test_process_does_not_retry_brand_resolution_after_no_match -q`

## Não-objetivos
- Não alterar `app/services/fipe_monthly_sync_service.py` nem o contrato/comportamento do pipeline mensal externo.
- Não alterar `_refresh_fipe_catalog_entry` nem seu comportamento hoje existente (inclusive a limitação conhecida de zerar `brand_code`/`model_code` em refresh — ver Riscos).
- Não criar migração, tabela ou coluna nova — reaproveita `FipeCatalogEntry`/`upsert_fipe_catalog_entries` como estão.
- Não implementar correspondência fuzzy/fonética/similaridade textual — apenas containment determinístico de tokens (`important_vehicle_tokens`) com tie-break por menor excesso de tokens.
- Não pré-popular ou baixar toda a base de marcas/modelos da FIPE (nem em background, nem em lote) — o bootstrap só roda dentro do processamento de uma `FipeLookupRequest` existente, motivado por uma busca real.
- Não paralelizar chamadas à API FIPE — reaproveita o rate limiter já existente em `FipeApiClient`/`FipeRateLimiter` sem alterá-lo.
- Não persistir cache de "marca não encontrada" entre execuções/requests diferentes — o cache desta spec vive só durante uma chamada de `_process_one_fipe_lookup`.
- Não alterar `settings.fipe_lookup_min_confidence` nem os thresholds de `score_fipe_candidate` usados pelo caminho de catálogo já existente.

## Premissas assumidas (gate de fechamento)
- PREM-01: Gatilho do bootstrap reaproveita exatamente a condição atual de `skipped_year` (`result["status"] == "insufficient_data" or best is None`), restrito a `pseudo_listing.make`/`pseudo_listing.model` preenchidos e `year is not None`. Razão: é o único ponto do loop onde já sabemos que o catálogo local não tem nada útil; a correspondência de marca por containment de tokens é o próprio filtro contra falso-positivo, então não é necessário um sinal adicional (ex.: contar linhas de catálogo por marca) antes de tentar.
- PREM-02: Uma única tentativa de resolução de marca/modelo (`get_reference_tables`+`get_brands`+`get_models`) por `FipeLookupRequest` processado, cacheada localmente nas variáveis da função `_process_one_fipe_lookup` (não em `system_logs`, não em nova coluna). Razão: limita o orçamento de chamadas à API por request (já sujeito ao rate limiter) e evita repetir uma resolução fadada ao mesmo resultado a cada ano do loop de anos-alvo (spec 007, até `fipe_lookup_year_expand_max=5` anos).
- PREM-03: O cache de resolução (positivo ou negativo) não é persistido entre execuções diferentes da fila — cada `FipeLookupRequest` reprocessado (retry) tenta a resolução do zero. Razão: fora do pedido do usuário; cache persistente de "marca desconhecida" é decisão de produto adicional que pode esconder falsos negativos permanentes se a FIPE atualizar sua lista de marcas.
- PREM-04: Correspondência marca/modelo usa `important_vehicle_tokens` (mesma função já usada por `fipe_catalog_resolver_service.py`) e exige containment total (`query_tokens.issubset(item_tokens)`); nunca substring livre nem similaridade aproximada. Razão: evita criar `FipeCatalogEntry` para o veículo errado — falso-positivo aqui grava dado ruim persistente no catálogo, custo maior que um `skipped_year` a mais.
- PREM-05: Seleção de ano/combustível em `get_model_years` usa a primeira combinação cujo prefixo de `Value` (antes do `-`) bate com o ano-alvo — mesma convenção de fallback já usada por `_find_target_year` quando não há `fuel` de referência. Razão: reaproveita convenção já aceita no código existente em vez de inventar uma nova.
- PREM-06: As `FipeCatalogEntry` criadas via bootstrap recebem `source="on_demand_bootstrap"` (distinto de `"on_demand"`, usado pelo refresh) e, diferente de `_refresh_fipe_catalog_entry`, incluem `brand_code`/`model_code`/`year_code` no payload normalizado (`codigo_marca`, `codigo_modelo`, `codigo_ano` — já disponíveis nos dicts `brand`/`model`/`Value` resolvidos), evitando que a entry nasça sem esses códigos. Razão: barato (os códigos já estão em memória) e melhora a re-atualização futura da entry via `_refresh_fipe_catalog_entry`, que hoje exige `brand_code`/`model_code` preenchidos.

## Decisões tomadas
- `_match_fipe_catalog_item` é uma função pura nova (sem I/O), testável isoladamente com listas de dicts fixas — evita acoplar os testes de matching a mocks de `FipeApiClient`.
- `_resolve_fipe_brand_and_model` e `_bootstrap_fipe_catalog_entry` recebem um `FipeApiClient` já instanciado como parâmetro (não instanciam internamente) — permite reaproveitar a mesma instância (e o mesmo rate limiter) entre a resolução de marca/modelo e as chamadas por ano dentro da mesma request, e facilita mock nos testes (mesmo padrão já usado nos testes existentes que fazem `monkeypatch.setattr(svc, "FipeApiClient", FakeClient)`).
- Novo outcome de string `"bootstrapped"` é tratado como sucesso equivalente a `"done"`/`"refreshed"` na decisão final (`final_status`/`final_outcome`) — reaproveita a mesma variável `final_outcome` já existente no loop, sem novo campo.
- Tratamento de `FipeApiError` durante bootstrap reaproveita a MESMA lógica (rollback, attempts, retry/failed, log, return) já escrita duas vezes em `_process_one_fipe_lookup` para o refresh — extraída para um helper privado novo `_apply_bootstrap_api_error(db, request, wishlist, outcomes, exc) -> str`, usado SOMENTE pelos dois novos pontos de chamada (resolução de marca/modelo e `_bootstrap_fipe_catalog_entry`). Os dois blocos já existentes do refresh permanecem intocados (evita risco de regressão em código já verificado na spec 007).

## Contratos e schemas

```python
def _match_fipe_catalog_item(items: list[dict], query_text: str, *, label_key: str = "Label") -> dict | None:
    """
    items: lista de dicts retornados pela API FIPE (ex.: client.get_brands()/client.get_models()),
    cada um com ao menos a chave `label_key` (string) e tipicamente "Value" (código).

    Algoritmo:
    1. query_tokens = important_vehicle_tokens(query_text) (import de fipe_catalog_resolver_service).
       Se query_tokens vazio -> retorna None.
    2. Para cada item, item_tokens = important_vehicle_tokens(item.get(label_key)).
       Item é candidato SOMENTE SE query_tokens.issubset(item_tokens) (contenção total).
    3. Se nenhum candidato -> retorna None.
    4. Entre os candidatos, escolhe o de menor len(item_tokens) - len(query_tokens).
       Empate residual -> primeiro candidato na ORDEM ORIGINAL de `items` (estável, sem reordenar).
    5. Retorna o dict do item escolhido (referência original, não cópia).

    Não faz I/O. Não levanta exceção (além de erros de tipo óbvios se items não for iterável de dicts).
    """


def _resolve_fipe_brand_and_model(
    client: FipeApiClient, *, make: str, model: str
) -> tuple[dict, dict, int] | None:
    """
    1. reference_table = client.get_latest_reference_table(); reference_code = reference_table["Codigo"].
    2. brands = client.get_brands(reference_code); brand = _match_fipe_catalog_item(brands, make).
       Se brand is None -> retorna None (NÃO chama get_models).
    3. models = client.get_models(reference_code, brand["Value"]); model_item = _match_fipe_catalog_item(models, model).
       Se model_item is None -> retorna None.
    4. Retorna (brand, model_item, reference_code).

    Propaga FipeApiError das chamadas de client.* sem capturar — o chamador decide o tratamento
    (ver _apply_bootstrap_api_error).
    """


def _bootstrap_fipe_catalog_entry(
    db: Session, client: FipeApiClient, *, brand: dict, model: dict, reference_code: int, year: int
) -> bool:
    """
    1. years = client.get_model_years(reference_code, brand["Value"], model["Value"]).
    2. year_matches = [item for item in (years or []) if str(item.get("Value", "")).split("-", 1)[0] == str(year)].
       Se vazio -> retorna False (ano não existe na FIPE para esse modelo; NÃO é erro).
    3. target = year_matches[0] (primeira ocorrência — sem sinal de fuel de referência).
    4. value = str(target.get("Value") or ""); fuel_code = value.split("-", 1)[1] if "-" in value else value.
    5. price_data = client.get_price(reference_code=reference_code, brand_code=brand["Value"],
       model_code=model["Value"], model_year=year, fuel_code=fuel_code).
    6. raw_row = {
         "tipo_veiculo": "car",
         "marca": price_data.get("Marca"),
         "modelo": price_data.get("Modelo"),
         "ano": price_data.get("AnoModelo"),
         "combustivel": price_data.get("Combustivel"),
         "codigo_fipe": price_data.get("CodigoFipe"),
         "valor": price_data.get("Valor"),
         "codigo_marca": brand["Value"],
         "codigo_modelo": model["Value"],
         "codigo_ano": value,
       }
    7. current_month = datetime.now(timezone.utc).strftime("%Y-%m").
    8. normalized = normalize_external_fipe_row(raw_row, reference_month=current_month).
       Se normalized is None -> raise FipeApiError("resposta da API FIPE não pôde ser normalizada durante bootstrap").
    9. upsert_fipe_catalog_entries(db, [normalized], reference_month=current_month, source="on_demand_bootstrap").
    10. Retorna True.

    Propaga FipeApiError das chamadas de client.* sem capturar.
    """


def _apply_bootstrap_api_error(
    db: Session, request: FipeLookupRequest, wishlist: Wishlist, outcomes: list[dict], year: int | None, exc: Exception
) -> str:
    """
    Idêntico ao bloco `except FipeApiError` já existente em _process_one_fipe_lookup para o refresh
    (linhas atuais ~372-400), reescrito como helper reutilizável:
    1. outcomes.append({"year": year, "status": "api_error", "confidence_score": None}).
    2. db.rollback().
    3. request.attempts += 1; request.last_error = str(exc)[:1000].
    4. Se request.attempts >= settings.fipe_lookup_max_attempts: request.status = "failed";
       request.processed_at = datetime.now(timezone.utc). Senão: request.status = "pending".
    5. try/except: system_logs_service.log(db, "info", "fipe_lookup", "fipe on-demand lookup outcome",
       payload={"wishlist_id": str(wishlist.id), "outcomes": outcomes, "final_status": "api_error"}).
    6. db.commit().
    7. Retorna "failed_final" se request.attempts >= settings.fipe_lookup_max_attempts, senão "failed_temp".

    Usado SOMENTE pelos dois novos pontos de chamada de bootstrap (_resolve_fipe_brand_and_model e
    _bootstrap_fipe_catalog_entry). Os dois blocos existentes do fluxo de refresh (linhas ~372-427)
    NÃO são alterados nem substituídos por este helper — permanecem como estão.
    """
```

### Integração em `_process_one_fipe_lookup`

No trecho atual (dentro do `for year in sorted(target_years):`):

```python
if result["status"] == "insufficient_data" or best is None:
    outcomes.append({"year": year, "status": "skipped_year", "confidence_score": None})
    continue
```

Substituir por (variáveis `bootstrap_attempted: bool`, `bootstrap_resolved: tuple | None`, `bootstrap_client: FipeApiClient | None` inicializadas como `False`/`None`/`None` ANTES do `for year in ...`):

```python
if result["status"] == "insufficient_data" or best is None:
    if (
        not bootstrap_attempted
        and pseudo_listing.make
        and pseudo_listing.model
        and year is not None
    ):
        bootstrap_attempted = True
        bootstrap_client = FipeApiClient()
        try:
            bootstrap_resolved = _resolve_fipe_brand_and_model(
                bootstrap_client, make=pseudo_listing.make, model=pseudo_listing.model
            )
        except FipeApiError as exc:
            return _apply_bootstrap_api_error(db, request, wishlist, outcomes, year, exc)

    if bootstrap_resolved:
        brand, model_item, reference_code = bootstrap_resolved
        try:
            created = _bootstrap_fipe_catalog_entry(
                db, bootstrap_client, brand=brand, model=model_item, reference_code=reference_code, year=year
            )
        except FipeApiError as exc:
            return _apply_bootstrap_api_error(db, request, wishlist, outcomes, year, exc)
        if created:
            outcomes.append({"year": year, "status": "bootstrapped", "confidence_score": None})
            if final_outcome is None:
                final_outcome = "bootstrapped"
            continue

    outcomes.append({"year": year, "status": "skipped_year", "confidence_score": None})
    continue
```

Observações de integração:
- `bootstrap_client` só é criado quando `bootstrap_attempted` vira `True` pela primeira vez (economia: se todo ano-alvo tiver candidato local, nunca instancia `FipeApiClient`) e é reaproveitado (mesma instância) para todas as chamadas de `_bootstrap_fipe_catalog_entry` da mesma request (REQ-006/PREM-02).
- Quando `_resolve_fipe_brand_and_model` retorna `None` (sem exceção), `bootstrap_resolved` permanece `None` — o `if bootstrap_resolved:` seguinte é pulado e cai direto no `skipped_year` final, e por `bootstrap_attempted` já ser `True`, os anos seguintes da mesma request NÃO tentam `_resolve_fipe_brand_and_model` de novo (REQ-009).
- `final_outcome` já é a variável existente que decide `final_status`/retorno da função — nenhuma mudança na lógica de decisão final além de aceitar `"bootstrapped"` como um valor possível (mesma prioridade de "primeiro sucesso vence" que já existe entre `"done"`/`"refreshed"`).

## Plano de testes

Estilo de referência (amostrado de `tests/test_fipe_on_demand_lookup_service.py`, linhas 243-660): `pytest` puro com fixture `db` (SQLite in-memory via conftest), `monkeypatch.setattr(svc, "FipeApiClient", FakeClient)` para stubar a classe inteira, e classes `FakeClient`/`ExplodingClient` locais por teste. Testes de integração do loop montam `Wishlist`+`WishlistFilter` reais no banco de teste e chamam `svc._process_one_fipe_lookup(db, request)` diretamente. Todos os testes novos vão em `tests/test_fipe_on_demand_lookup_service.py` (mesmo arquivo da spec 007).

Total de testes novos declarados: **13** (fora os já existentes, que continuam intocados).

1. `test_match_fipe_catalog_item_returns_none_when_no_containment` — REQ-002. `items=[{"Label":"Toyota"}]`, `query_text="honda"` → `None`.
2. `test_match_fipe_catalog_item_exact_single_match` — base do REQ-001. `items=[{"Label":"Honda"},{"Label":"Toyota"}]`, `query_text="honda"` → retorna o dict `{"Label":"Honda"}` (mesma referência).
3. `test_match_fipe_catalog_item_prefers_fewest_extra_tokens` — REQ-003. `items=[{"Label":"Fit EX 1.5 16V"},{"Label":"Fit"},{"Label":"Fit LX 1.5"}]`, `query_text="fit"` → retorna `{"Label":"Fit"}` (0 tokens extras).
4. `test_match_fipe_catalog_item_tiebreaks_by_list_order` — REQ-003. `items=[{"Label":"Fit EX"},{"Label":"Fit LX"}]` (mesma quantidade de tokens extras), `query_text="fit"` → retorna o primeiro (`{"Label":"Fit EX"}`).
5. `test_resolve_fipe_brand_and_model_success` — contrato de `_resolve_fipe_brand_and_model`. `FakeClient` com `get_latest_reference_table` retornando `{"Codigo": 320}`, `get_brands` retornando `[{"Label":"Honda","Value":"22"}]`, `get_models(320,"22")` retornando `[{"Label":"Fit","Value":"4828"}]` → chamada com `make="honda", model="fit"` retorna `({"Label":"Honda","Value":"22"}, {"Label":"Fit","Value":"4828"}, 320)`.
6. `test_resolve_fipe_brand_and_model_returns_none_when_brand_not_found` — REQ-002. `get_brands` retorna `[{"Label":"Toyota","Value":"1"}]`, `make="honda"` → retorna `None`; assert que `get_models` NUNCA foi chamado (flag na `FakeClient`).
7. `test_resolve_fipe_brand_and_model_returns_none_when_model_not_found` — REQ-002. Marca resolvida, `get_models` retorna `[{"Label":"Civic","Value":"9"}]`, `model="fit"` → retorna `None`.
8. `test_bootstrap_creates_new_catalog_entry` — REQ-004/REQ-008/PREM-06. `FakeClient.get_model_years` retorna `[{"Label":"2019 Gasolina","Value":"2019-1"}]`, `get_price` retorna `{"Marca":"Honda","Modelo":"Fit","AnoModelo":2019,"Combustivel":"Gasolina","CodigoFipe":"001004-9","Valor":"R$ 65.000,00"}` → `_bootstrap_fipe_catalog_entry(db, client, brand=..., model=..., reference_code=320, year=2019)` retorna `True`; consulta direta ao banco (`db.query(FipeCatalogEntry).filter(...).first()`) confirma UMA nova linha com `brand_name="Honda"`, `model_name="Fit"`, `model_year=2019`, `price=Decimal("65000.00")`, `source="on_demand_bootstrap"`, `brand_code="22"`, `model_code="4828"` (asserção de estado real persistido, não apenas retorno).
9. `test_bootstrap_returns_false_when_year_not_found` — REQ-005. `get_model_years` retorna `[{"Label":"2020 Gasolina","Value":"2020-1"}]` (sem 2019) → chamada com `year=2019` retorna `False`; assert `get_price` NUNCA foi chamado (flag na `FakeClient`); assert nenhuma linha nova em `fipe_catalog_entries`.
10. `test_process_attempts_bootstrap_when_no_local_candidate` — REQ-001. Wishlist com `query="honda fit"` e filtro `year gte=2019`, catálogo local vazio para essa marca. `monkeypatch.setattr(svc, "resolve_listing_to_fipe_candidates", ...)` retornando sempre `{"status":"no_match","best_candidate":None,"candidates":[]}`. `FakeClient` completa resolve+bootstrap com sucesso. Chama `svc._process_one_fipe_lookup(db, request)` → retorna `"bootstrapped"`; `request.status == "done"`.
11. `test_process_skips_year_when_brand_not_matched` — REQ-002. Mesmo setup, mas `FakeClient.get_brands` não bate com a marca da query → `_process_one_fipe_lookup` retorna outcome de skip (`request.status == "skipped"`); nenhuma `FipeCatalogEntry` nova criada.
12. `test_process_reuses_resolved_brand_model_across_years` — REQ-006. Wishlist com filtro `gte=2018, lte=2020` (3 anos-alvo, `fipe_lookup_year_expand_max` cobre os 3). `FakeClient` conta quantas vezes `get_brands`/`get_models` foram chamados (deve ser exatamente 1 cada) e quantas vezes `get_model_years`/`get_price` foram chamados (deve ser 3 cada, um por ano) — assert nos contadores da fake, não apenas no resultado final.
13. `test_process_bootstrap_api_error_stops_loop_and_retries` — REQ-007. `FakeClient.get_brands` levanta `FipeApiError("timeout")`. `request.attempts` parte de `0`, `settings.fipe_lookup_max_attempts=3` (padrão). Chama `_process_one_fipe_lookup` → retorna `"failed_temp"`; `request.attempts == 1`; `request.status == "pending"`; `request.last_error` contém `"timeout"`.
14. `test_process_does_not_retry_brand_resolution_after_no_match` — REQ-009. 3 anos-alvo, `FakeClient.get_brands` retorna lista sem match. Assert que `get_brands` foi chamado exatamente 1 vez mesmo com 3 anos no loop (contador na fake).

(A lista acima soma 14 itens; ao redigir os testes, o nome final de cada função DEVE bater com o nome citado no `verificado por:` do REQ correspondente — ajustar REQ-008 para citar `test_process_logs_bootstrapped_outcome`/`test_process_returns_bootstrapped_when_first_success` como dois testes derivados do item 10 acima, ou desmembrar o item 10 em dois testes se necessário para bater exatamente com os nomes dos REQs. Este ajuste de nomenclatura é mecânico e não altera comportamento — não é decisão residual.)

Além dos testes novos: a suíte completa (`pytest tests/ -q`, ~ mesmo total de testes hoje + 14) deve permanecer verde, incluindo os 34 testes da spec 007 em `tests/test_fipe_on_demand_lookup_service.py` e `tests/test_notifications_queue_service.py`, e as falhas pré-existentes documentadas em `specs/007-fipe-on-demand-fixes/RUN.md` (não relacionadas a este código) continuam as mesmas, sem novas falhas.

## Grafo de dependências

Todas as etapas tocam o MESMO arquivo (`app/services/fipe_on_demand_lookup_service.py`) e seu arquivo de teste — execução SEQUENCIAL (sem paralelismo) para evitar conflito de edição concorrente no mesmo arquivo.

Onda 1: Etapa 1
Onda 2: Etapa 2 (depende de 1)
Onda 3: Etapa 3 (depende de 1)
Onda 4: Etapa 4 (depende de 2 e 3)
Onda 5: Etapa 5 (depende de 4)

## Etapas

### Etapa 1: `_match_fipe_catalog_item` + testes puros
- FAZ: Adicionar a função `_match_fipe_catalog_item(items, query_text, *, label_key="Label")` em `app/services/fipe_on_demand_lookup_service.py` conforme contrato acima. Importar `important_vehicle_tokens` de `app.services.fipe_catalog_resolver_service` no topo do arquivo (novo import). Adicionar os testes 1-4 do plano de testes em `tests/test_fipe_on_demand_lookup_service.py`.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py`
- EXEMPLO E/S: `_match_fipe_catalog_item([{"Label":"Fit EX 1.5 16V"},{"Label":"Fit"}], "fit")` → `{"Label":"Fit"}`
- VALIDA COM: `py -m pytest tests/test_fipe_on_demand_lookup_service.py -k match_fipe_catalog_item -q` → 4 passed
- ESCALA SE: `important_vehicle_tokens` não existe mais em `fipe_catalog_resolver_service.py` com essa assinatura, ou a suíte completa do arquivo quebra por conflito de import.

### Etapa 2: `_resolve_fipe_brand_and_model` + testes
- FAZ: Adicionar `_resolve_fipe_brand_and_model(client, *, make, model)` conforme contrato. Adicionar os testes 5-7 do plano de testes (com `FakeClient` local a cada teste, seguindo o padrão de `test_process_refreshes_stale_candidate_via_targeted_api_call`).
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py`
- EXEMPLO E/S: ver item 5 do plano de testes.
- VALIDA COM: `py -m pytest tests/test_fipe_on_demand_lookup_service.py -k resolve_fipe_brand_and_model -q` → 3 passed
- ESCALA SE: `client.get_latest_reference_table()` ou `client.get_brands()`/`get_models()` mudaram de assinatura em `fipe_api_client.py` desde a leitura desta spec.

### Etapa 3: `_bootstrap_fipe_catalog_entry` + testes
- FAZ: Adicionar `_bootstrap_fipe_catalog_entry(db, client, *, brand, model, reference_code, year)` conforme contrato. Adicionar os testes 8-9 do plano de testes.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py`
- EXEMPLO E/S: ver itens 8-9 do plano de testes.
- VALIDA COM: `py -m pytest tests/test_fipe_on_demand_lookup_service.py -k bootstrap_creates_new_catalog_entry or bootstrap_returns_false_when_year_not_found -q` → 2 passed
- ESCALA SE: `normalize_external_fipe_row` ou `upsert_fipe_catalog_entries` mudaram de assinatura desde a leitura desta spec; ou o teste 8 falha em confirmar `brand_code`/`model_code` persistidos (indica que `_ALIAS`/normalização não aceita `codigo_marca`/`codigo_modelo`/`codigo_ano` — nesse caso, remover esses 3 campos de `raw_row` e ajustar PREM-06 para registrar a limitação em vez de forçar).

### Etapa 4 [sensível]: Integração no loop de `_process_one_fipe_lookup`
- FAZ: Adicionar o helper `_apply_bootstrap_api_error(db, request, wishlist, outcomes, year, exc)` conforme contrato. Substituir o bloco `if result["status"] == "insufficient_data" or best is None:` dentro do `for year in sorted(target_years):` de `_process_one_fipe_lookup` pela versão integrada descrita na seção "Integração em `_process_one_fipe_lookup`" acima, inicializando `bootstrap_attempted = False`, `bootstrap_resolved = None`, `bootstrap_client = None` imediatamente antes do `for year in sorted(target_years):`. NÃO alterar nenhum outro trecho da função (os blocos de refresh/`api_error` existentes permanecem byte-a-byte iguais). Adicionar os testes 10-14 do plano de testes.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py`
- VALIDA COM: `py -m pytest tests/test_fipe_on_demand_lookup_service.py -q` → todos os testes do arquivo (existentes + novos) passando
- ESCALA SE: a integração exige tocar o bloco de decisão final (`final_status = "done" if final_outcome else "skipped"`) além de aceitar `"bootstrapped"` como valor de `final_outcome` (se isso não bastar, é decisão residual — escalar); ou algum teste pré-existente do arquivo (spec 007) passa a falhar após a integração.

### Etapa 5: Regressão completa e fechamento
- FAZ: Rodar a suíte completa do projeto. Se alguma falha nova (não presente na lista de pré-existentes registrada em `specs/007-fipe-on-demand-fixes/RUN.md`) aparecer, investigar e corrigir dentro do escopo desta spec (arquivos da Etapa 1-4). Registrar no `RUN.md` desta spec a contagem final de testes e a confirmação de que a lista de falhas pré-existentes não mudou.
- TOCA: nenhum arquivo de produto adicional (apenas leitura/execução); `specs/008-fipe-catalog-bootstrap/RUN.md`
- VALIDA COM: `py -m pytest tests/ -q` → mesma lista de falhas pré-existentes (ou zero, se o ambiente já estiver limpo) + nenhuma falha nova
- ESCALA SE: uma falha nova não é trivialmente atribuível a um bug desta spec (ex.: parece pré-existente mas não bate com a lista registrada) — escalar para decisão humana/spec-resolver, mesmo protocolo usado na Etapa 7 da spec 007 (`git stash` dos arquivos tocados por esta spec + re-rodar para confirmar se é pré-existente).

## Riscos conhecidos e mitigação

| Risco | Etapa | Mitigação já embutida na spec |
|---|---|---|
| Bootstrap cria entry para veículo errado (falso-positivo de marca/modelo) | 1, 2 | Containment total de tokens (PREM-04), sem fuzzy; um único token divergente já invalida o match |
| Custo de API por request sem limite | 4 | Cache de resolução por request (PREM-02/REQ-006), no máximo 1x `get_brands`/`get_models` + até `fipe_lookup_year_expand_max` (5) pares `get_model_years`/`get_price` |
| Entry criada sem `brand_code`/`model_code` (mesmo problema latente de `_refresh_fipe_catalog_entry`) | 3 | PREM-06: bootstrap inclui `codigo_marca`/`codigo_modelo`/`codigo_ano` no payload, evitando reproduzir a lacuna no caminho novo (a lacuna do refresh existente permanece fora de escopo) |
| Rate limit / 429 da API FIPE durante bootstrap em produção | 4 | Reaproveita `FipeApiClient`/`FipeRateLimiter` já existentes sem modificação; erro vira `api_error` com retry via `fipe_lookup_max_attempts` (REQ-007), mesmo comportamento do refresh |
| Duplicação de lógica de tratamento de erro (4 blocos quase iguais no arquivo) | 4 | Helper `_apply_bootstrap_api_error` isola SÓ os 2 novos pontos de chamada; blocos existentes do refresh não são tocados (decisão explícita para não arriscar regressão em código já verificado) |

## Análise de consistência (preencher antes de liberar)
- [x] Todo requisito do objetivo é coberto por ao menos um critério de aceitação (REQ-001 a REQ-009 cobrem trigger, matching, criação, ano ausente, cache, erro de API, outcome de log e decisão final, e não-retentativa)
- [x] Toda etapa consome apenas artefatos criados por etapas anteriores (Etapa 2 e 3 usam `important_vehicle_tokens`/`_match_fipe_catalog_item` só indiretamente via import já existente/Etapa 1; Etapa 4 usa as 3 funções das etapas 1-3)
- [x] Nenhuma contradição entre contratos, exemplos e testes (exemplos de `_match_fipe_catalog_item`, `_bootstrap_fipe_catalog_entry` e testes 1-9 usam os mesmos formatos de dict)
- [x] Nenhuma frase delega julgamento — nota: o parênteses no fim do Plano de testes sobre nomenclatura de REQ-008 é mecânico (bater nome de teste com `verificado por:`), não julgamento de comportamento
