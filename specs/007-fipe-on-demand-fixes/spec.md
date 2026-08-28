# Spec: Correções na busca sob demanda de FIPE (parsing de marca/modelo, intervalo de ano, diagnóstico de skip, erro de enqueue e fallback no alerta)  [spec-kit: T3 — 9pts: arquivos=2, decisões=2, risco=2, novidade=1, verif=2]

## Origem

Investigação real de produção (2026-08-27/28) sobre por que 3 wishlists de teste (`Civic Hatch`, `honda fit s`, `A4 avant`) resultaram em `fipe_lookup_requests.status="skipped"` e por que uma wishlist real de Honda Fit (id `23638981`, criada 2026-07-26) recebeu um alerta no Telegram com "sem base de FIPE". Evidências coletadas via SQL direto em produção estão registradas na conversa que originou esta spec; os achados relevantes viraram REQ-IDs abaixo.

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Verificação final: spec-verifier independente (obrigatório em T3), fix loop máx. 3 iterações
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 20 iterações totais
- Parada: veredito APROVADO do verifier | orçamento estourado → humano
- Registro: specs/007-fipe-on-demand-fixes/RUN.md (append-only)

## Objetivo

A fila de busca sob demanda de FIPE (spec 004) tem quatro defeitos confirmados com evidência de produção: (1) o parser de marca/modelo assume que o primeiro token da query da wishlist é sempre a marca, o que falha sempre que o usuário digita o modelo primeiro (ex: "Civic Hatch", "A4 avant"); (2) um filtro de ano em intervalo (`gte`/`lte`) é colapsado num único ano, perdendo cobertura; (3) um `status=skipped` não registra em lugar nenhum *por que* foi pulado, tornando a fila opaca para depuração; (4) uma falha no enfileiramento é só impressa via `print()`, nunca chega a `system_logs`. Além disso, confirmou-se que a fila on-demand (grava em `FipeCatalogEntry`) e o pipeline que monta o comparativo "vs FIPE" nos alertas do Telegram (lê só `FipePrice`, populada pelo sync mensal) são desconectados — mesmo uma busca on-demand bem-sucedida não alimenta o alerta. Esta spec corrige os quatro defeitos e conecta a fila on-demand ao alerta como fallback, sem alterar o sync mensal (spec 003) nem exigir migration de schema.

## Requisitos

- REQ-001: QUANDO uma wishlist tiver filtro `field="year"` com `gte` e/ou `lte` O SISTEMA DEVE calcular uma lista de até `settings.fipe_lookup_year_expand_max` anos-alvo (mais próximos da âncora definida em PREM-02, dentro do intervalo do filtro) em vez de colapsar para um único ano — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k resolve_target_years`
- REQ-002: QUANDO `_build_pseudo_listing` encontrar, entre os tokens da query da wishlist, um token (ou sequência contígua de tokens) que corresponda (case-insensitive, `ilike`) a uma `brand_name` já existente em `fipe_catalog_entries` O SISTEMA DEVE usar esse token como `make` e o restante da query (tokens fora do token de marca) como `model` — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k pseudo_listing_brand`
- REQ-003: QUANDO nenhum token da query corresponder a uma marca conhecida O SISTEMA DEVE preservar o comportamento legado (primeiro token = `make`, restante = `model`) — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k pseudo_listing_fallback`
- REQ-004: QUANDO o processamento de um `FipeLookupRequest` terminar (`done`, `skipped` ou `failed`) O SISTEMA DEVE gravar em `system_logs` (`component="fipe_lookup"`) um payload contendo o resultado por ano-alvo tentado (`year`, `status`, `confidence_score`) — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k diagnostic`
- REQ-005: QUANDO `enqueue_fipe_lookup_for_wishlist` capturar uma exceção O SISTEMA DEVE gravar o erro em `system_logs` (`component="fipe_lookup"`, `level="error"`), além de manter o `print()` já existente — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k enqueue_logs_error`
- REQ-006: QUANDO `queue_notifications_for_matches` não encontrar preço exato em `FipePrice` para um anúncio (`fipe_rows.get(key) is None` para todas as chaves do anúncio) O SISTEMA DEVE tentar um fallback via `resolve_listing_to_fipe_candidates` contra `FipeCatalogEntry` e usar `FipeCatalogEntry.price` como `fipe_price` somente quando `best_candidate["confidence_score"] >= settings.fipe_lookup_min_confidence` — verificado por: `pytest tests/test_notifications_queue_service.py -q -k fipe_fallback`
- REQ-007: QUANDO o fallback do REQ-006 falhar (exceção, sem candidato, ou confiança insuficiente) O SISTEMA DEVE manter o comportamento atual (`fipe_price=None`) sem interromper o enfileiramento de notificações — verificado por: `pytest tests/test_notifications_queue_service.py -q -k fipe_fallback_safe`

## Não-objetivos

- Não alterar o sync mensal de FIPE (spec 003 / `fipe_prices_import_service.py`, `fipe_monthly_pipeline_service.py`, `fipe_monthly_sync_service.py`).
- Não criar migration nem coluna nova em `fipe_lookup_requests` ou `fipe_catalog_entries` — decisão explícita do usuário (diagnóstico só via `system_logs`).
- Não paralelizar chamadas à API FIPE nem introduzir fila/worker novo — o loop de anos-alvo roda sequencialmente dentro do mesmo processamento de request que já existe.
- Não cachear a lista de marcas conhecidas (PREM-04) — fora de escopo, ver não-objetivo em consistência com volume atual.
- Não tratar nomes de marca compostos ambíguos além de correspondência simples por `ilike` de token(s) contíguos (ex.: heurísticas fonéticas, distância de edição) — fica para uma spec futura se necessário.
- Não mudar o valor global de `fipe_lookup_min_confidence` (continua 80) — reaproveitado como limiar do fallback do REQ-006 em vez de criar um segundo limiar.

## Premissas assumidas (gate de fechamento)

- PREM-01: `fipe_lookup_year_expand_max` (novo setting) tem default `5`. Justificativa: equilíbrio entre cobrir o intervalo pedido e não gerar mais de 5 chamadas de refresh à API FIPE por passada de processamento de um único request.
- PREM-02: quando só `lte` está presente (sem `gte`), a âncora dos "anos mais próximos" é o próprio `lte` (não o ano atual) — evita um range infinito para trás quando não há limite inferior real. Quando só `gte` está presente, a âncora é o ano atual (`datetime.now(timezone.utc).year`), e o topo do range é o ano atual. Quando ambos existem, a âncora é `min(max(ano_atual, gte), lte)` (clipada ao intervalo).
- PREM-03: o fallback de notificação (REQ-006) usa `_ensure_month(db, None)` (mês mais recente presente em `fipe_catalog_entries`) como `reference_month` ao chamar `resolve_listing_to_fipe_candidates`, e não `current_reference_month()` (usado por `FipePrice`) — são pipelines independentes, sem garantia de estarem no mesmo mês-calendário.
- PREM-04: a detecção de marca conhecida (REQ-002) consulta `SELECT DISTINCT brand_name FROM fipe_catalog_entries` a cada chamada de `_build_pseudo_listing`, sem cache. O volume atual (`fipe_lookup_batch_size=20` requests a cada `fipe_lookup_poll_interval_s=60`) não justifica cache nesta spec; se o volume crescer, cache é melhoria futura.
- PREM-05: no máximo 1 chamada de refresh via API FIPE por ano-alvo por passada de processamento (mesmo padrão de hoje, repetido até `fipe_lookup_year_expand_max` vezes). Se qualquer chamada de refresh levantar `FipeApiError` e nenhum ano-alvo tiver sido resolvido com sucesso até ali, o request mantém a semântica atual de retry (`attempts`/`last_error`/`pending`→`failed` conforme `fipe_lookup_max_attempts`).
- PREM-06: no fallback de notificação, se um anúncio tiver múltiplas `listing_vehicle_keys` (versão/transmissão) e nenhuma bater em `FipePrice`, o fallback via `FipeCatalogEntry` é tentado uma única vez usando o `listing` original (não uma vez por chave) — `resolve_listing_to_fipe_candidates` já faz sua própria pontuação de marca/modelo/ano/combustível internamente.

## Decisões tomadas

- Limitar o intervalo de ano a N anos mais próximos da âncora, em vez de expandir o intervalo inteiro sem limite — decisão do usuário, evita explosão de chamadas à API FIPE para filtros muito abertos (ex.: "a partir de 2000").
- Incluir nesta spec o fallback de `notifications_queue_service` lendo `FipeCatalogEntry` (resolve a lacuna arquitetural identificada na investigação) — decisão do usuário, aceitando que isso eleva o tier para T3 por tocar o pipeline de alerta em produção.
- Diagnóstico de skip só em `system_logs` (payload JSON), sem migration — decisão do usuário, mais rápido e sem risco de schema.
- Reaproveitar `settings.fipe_lookup_min_confidence` (80) como limiar do fallback de notificação, em vez de criar um segundo limiar — evita duplicar um número mágico sem justificativa nova.

## Contratos e schemas

Todas as assinaturas abaixo são em `app/services/fipe_on_demand_lookup_service.py`, exceto onde indicado.

```python
def _extract_year_bounds(filters: list[WishlistFilter]) -> tuple[int | None, int | None]:
    """Retorna (gte, lte) extraídos dos WishlistFilter com field="year".
    Um valor não numérico ou ausente vira None nessa posição (mesma tolerância
    a erro que o parsing de ano já tinha em _build_pseudo_listing hoje)."""


def _resolve_target_years(
    gte: int | None, lte: int | None, current_year: int, max_years: int
) -> list[int]:
    """
    - gte is None and lte is None -> [] (sem filtro de ano; comportamento atual preservado
      a jusante: pseudo_listing.year fica None -> resolver retorna insufficient_data).
    - Só gte -> range = [gte, current_year] (se gte > current_year, range = [current_year, gte]).
      Âncora = current_year.
    - Só lte -> range = [lte - max_years + 1, lte]. Âncora = lte.
    - Ambos -> range = [min(gte,lte), max(gte,lte)]. Âncora = min(max(current_year, low), high).
    - Se len(range) <= max_years: retorna o range inteiro, ordem crescente.
    - Senão: ordena os anos do range por (abs(ano - âncora), -ano) crescente, pega os
      `max_years` primeiros, devolve em ordem crescente.
    Nunca levanta exceção; max_years <= 0 é tratado como 1.
    """


_UNSET = object()  # sentinel módulo-level


def _build_pseudo_listing(
    wishlist: Wishlist, filters: list[WishlistFilter], year: int | None = _UNSET
) -> SimpleNamespace:
    """
    Marca/modelo (REQ-002/003): normaliza tokens da query (lowercase, split por espaço).
    Busca no banco `SELECT DISTINCT brand_name FROM fipe_catalog_entries WHERE brand_name IS NOT NULL`.
    Para cada marca conhecida (normalizada), verifica se seus tokens aparecem como sequência
    contígua no início OU em qualquer posição dos tokens da query (case-insensitive).
    Se achar: make = texto original da marca encontrada; model = tokens restantes da query
    (join com espaço), na ordem original, excluindo os tokens consumidos pela marca.
    Se não achar nenhuma marca conhecida: cai no comportamento legado (primeiro token = make,
    resto = model; token único = make == model == token).

    Ano (REQ-001): se `year` for `_UNSET` (não informado pelo chamador), comportamento IDÊNTICO
    ao atual: usa gte se existir (via _extract_year_bounds), senão lte, senão None.
    Se `year` for passado explicitamente (int ou None), esse valor é usado diretamente,
    ignorando os filtros — usado pelo loop em _process_one_fipe_lookup.
    """


def _process_one_fipe_lookup(db: Session, request: FipeLookupRequest) -> str:
    """
    1. Carrega wishlist e filters (igual hoje).
    2. gte, lte = _extract_year_bounds(filters)
    3. target_years = _resolve_target_years(gte, lte, datetime.now(timezone.utc).year,
       settings.fipe_lookup_year_expand_max)
    4. Se target_years == []: target_years = [None]  (preserva o caminho atual sem ano:
       insufficient_data de imediato, sem loop)
    5. month = _ensure_month(db, None)
    6. Para cada year em target_years (ordem crescente): builda pseudo_listing(year=year),
       chama resolve_listing_to_fipe_candidates, aplica a MESMA lógica de decisão que existe
       hoje (insufficient_data/no_match/baixa confiança -> outcome "skipped_year"; candidato
       válido e fresco -> outcome "done"; candidato válido e stale -> tenta
       _refresh_fipe_catalog_entry; sucesso -> "refreshed"; FipeApiError -> outcome
       "api_error" e para o loop nesse ponto, não tenta os anos restantes nesta passada).
       Acumula outcomes = [{"year": y, "status": ..., "confidence_score": ...}, ...].
    7. Decisão final do request (REQ-004 grava `outcomes` completo em system_logs sempre):
       - Se algum outcome for "done" ou "refreshed": status final = "done" (mesma semântica
         de hoje: pelo menos um ano do intervalo está coberto e fresco).
       - Senão, se algum outcome for "api_error": aplica a MESMA lógica de attempts/last_error/
         retry que existe hoje (attempts += 1; se >= fipe_lookup_max_attempts -> "failed",
         senão -> volta a "pending").
       - Senão (todos os anos deram insufficient_data/no_match/baixa confiança): status final
         = "skipped" (mesmo efeito observável de hoje).
    """
```

```python
# app/services/notifications_queue_service.py

def _fallback_fipe_price_via_catalog(db: Session, listing) -> Decimal | None:
    """
    Chama resolve_listing_to_fipe_candidates(db, listing=listing,
    reference_month=_ensure_month(db, None), limit=5) (import de
    app.services.fipe_catalog_resolver_service).
    Se result["status"] == "insufficient_data" ou best_candidate is None: retorna None.
    Se best_candidate["confidence_score"] < settings.fipe_lookup_min_confidence: retorna None.
    Senão: busca FipeCatalogEntry pelo catalog_entry_id do best_candidate e retorna .price.
    Captura QUALQUER exceção internamente e retorna None (nunca propaga — mesmo padrão do
    bloco `fipe_rows` existente logo acima, que já usa `except SQLAlchemyError` / `except Exception`).
    """
```

## Antes de escrever o plano de testes

Estilo de referência amostrado: `tests/test_fipe_on_demand_lookup_service.py` (fixture `db`, `monkeypatch`, funções `test_*` diretas sem classes, asserts diretos sobre retorno/estado do banco) e `tests/test_fipe_apply_status_service.py` (construção direta de `FipeCatalogEntry`/`FipePrice` via fixture, sem factory library). Comando de execução: `pytest <arquivo> -q` (ou `-q -k <filtro>`), conforme `pytest.ini` na raiz. Não existe `tests/test_notifications_queue_service.py` hoje — será criado nesta spec seguindo o mesmo estilo (fixture `db`, construção direta de `Wishlist`/listagem simulada/`FipeCatalogEntry`, `monkeypatch` para capturar os kwargs passados a `score_ad` quando necessário).

## Plano de testes

Total: **14 testes novos**. Nenhum teste existente muda de comportamento esperado (ver PREM/Contratos: assinatura default de `_build_pseudo_listing` sem `year` explícito é bit-a-bit igual à atual).

Em `tests/test_fipe_on_demand_lookup_service.py`:

1. `test_resolve_target_years_no_bounds_returns_empty` (REQ-001) — `gte=None, lte=None` → `[]`.
2. `test_resolve_target_years_small_range_returns_all` (REQ-001) — `gte=2020, lte=2022, max_years=5` → `[2020, 2021, 2022]`.
3. `test_resolve_target_years_gte_only_anchors_on_current_year` (REQ-001, PREM-02) — `gte=2018, lte=None, current_year=2026, max_years=5` → `[2022, 2023, 2024, 2025, 2026]`.
4. `test_resolve_target_years_lte_only_anchors_on_lte` (REQ-001, PREM-02) — `gte=None, lte=2008, current_year=2026, max_years=5` → `[2004, 2005, 2006, 2007, 2008]`.
5. `test_resolve_target_years_both_bounds_clipped_anchor` (REQ-001, PREM-02) — `gte=1990, lte=2000, current_year=2026, max_years=5` → âncora clipada em 2000 → `[1996, 1997, 1998, 1999, 2000]`.
6. `test_pseudo_listing_year_default_unchanged_prefers_gte` (regressão explícita do contrato "sem `year` explícito = comportamento atual") — mesmo caso do `test_pseudo_listing_year_prefers_gte` já existente, chamando `_build_pseudo_listing(wishlist, filters)` sem `year`.
7. `test_pseudo_listing_year_explicit_overrides_filters` (REQ-001 suporte) — filtros com `gte=2018`, chamada com `year=2005` explícito → `pseudo_listing.year == 2005`.
8. `test_pseudo_listing_brand_detected_when_not_first_token` (REQ-002) — seed `FipeCatalogEntry(brand_name="Honda", ...)`, query `"Civic Hatch"` → `make == "Honda"`, `model` contém `"Civic Hatch"` (marca não fazia parte do texto; token de marca não encontrado no texto — usar um caso onde a marca aparece: query `"Honda Civic Hatch"` com o token de marca no meio não é o cenário; usar sim query `"fit honda"` (modelo antes da marca) → `make == "Honda"`, `model == "fit"`).
9. `test_pseudo_listing_brand_detected_honda_fit_s` (REQ-002, caso real da investigação) — seed `FipeCatalogEntry(brand_name="Honda")`, query `"honda fit s"` → `make == "Honda"`, `model == "fit s"` (marca no início continua funcionando).
10. `test_pseudo_listing_falls_back_when_no_known_brand` (REQ-003) — nenhuma `FipeCatalogEntry` com marca correspondente aos tokens da query `"Foo Bar"` → `make == "Foo"`, `model == "Bar"` (idêntico ao comportamento legado).
11. `test_process_logs_diagnostic_payload_per_target_year` (REQ-004) — wishlist com `year gte=2020, lte=2022` (3 anos-alvo, todos sem candidato no catálogo) → após `_process_one_fipe_lookup`, existe uma linha em `system_logs` com `component="fipe_lookup"` cujo `payload["outcomes"]` tem 3 entradas, uma por ano, todas com `status` não-vazio.
12. `test_process_marks_done_when_any_target_year_matches` (REQ-001 integração) — 3 anos-alvo, só o do meio tem `FipeCatalogEntry` fresca correspondente → request final `status == "done"`.
13. `test_process_marks_skipped_when_all_target_years_have_no_match` (REQ-001 integração, substitui em cobertura o antigo teste único de skip) — nenhum dos anos-alvo tem candidato → `status == "skipped"`.
14. `test_enqueue_logs_error_to_system_logs_on_exception` (REQ-005) — `monkeypatch` para `db.commit` levantar exceção dentro de `enqueue_fipe_lookup_for_wishlist` → depois da chamada, existe uma linha em `system_logs` com `component="fipe_lookup"`, `level="error"`.

Em `tests/test_notifications_queue_service.py` (arquivo novo):

15. `test_queue_notifications_uses_fipe_catalog_fallback_when_price_missing` (REQ-006) — sem linha em `FipePrice` para o anúncio; `FipeCatalogEntry` seedada com marca/modelo/ano batendo e `price=Decimal("45000.00")`; `monkeypatch` em `score_ad` para capturar o kwarg `fipe_price` recebido → assert `fipe_price == Decimal("45000.00")`.
16. `test_queue_notifications_fallback_respects_min_confidence` (REQ-006/007) — `FipeCatalogEntry` seedada mas com ano bem distante do anúncio (confidence abaixo de `fipe_lookup_min_confidence`) → `fipe_price` capturado é `None`.
17. `test_queue_notifications_fallback_never_raises_on_resolver_error` (REQ-007) — `monkeypatch` em `resolve_listing_to_fipe_candidates` para levantar exceção → `queue_notifications_for_matches` ainda retorna normalmente (notificação enfileirada), `fipe_price` capturado é `None`.

(Nota: a lista chegou a 17 pontos numerados porque os itens 8 e 9 cobrem sub-casos do mesmo REQ-002 que vale a pena distinguir; "14 testes novos" citado acima está desatualizado por este detalhamento — o número real e vinculante para o gate de fechamento é **17 testes novos**, todos listados acima com REQ-ID.)

Nenhuma asserção deste plano é rasa: todas checam valor real retornado/persistido (`pseudo_listing.make`/`.model`/`.year`, `request.status` pós-commit, linhas reais de `system_logs`, o kwarg `fipe_price` efetivamente recebido por `score_ad`) — nenhuma apenas confere que um mock foi chamado sem checar o argumento.

## Grafo de dependências

Onda 1 (independentes entre si):
- Etapa 1: novo setting `fipe_lookup_year_expand_max`
- Etapa 2: `_extract_year_bounds` + `_resolve_target_years` (funções puras)
- Etapa 5: log de erro em `enqueue_fipe_lookup_for_wishlist`
- Etapa 6 [sensível]: fallback em `notifications_queue_service.py`

Onda 2: Etapa 3 (depende da Etapa 2 — usa `_extract_year_bounds`) — detecção de marca conhecida + `_build_pseudo_listing(year=...)`

Onda 3: Etapa 4 [sensível] (depende das Etapas 1 e 3) — loop de anos-alvo em `_process_one_fipe_lookup` + diagnóstico em `system_logs`

Onda 4: Etapa 7 (depende de todas as anteriores) — regressão completa

## Etapas

### Etapa 1: novo setting `fipe_lookup_year_expand_max`
- FAZ: em `app/core/settings.py`, logo após `fipe_lookup_max_attempts: int = 3` (linha ~355), adicionar `fipe_lookup_year_expand_max: int = 5`.
- TOCA: `app/core/settings.py`
- VALIDA COM: `py -c "from app.core.settings import settings; assert settings.fipe_lookup_year_expand_max == 5"` → sem erro
- ESCALA SE: o atributo já existir com outro nome/valor conflitante.

### Etapa 2: `_extract_year_bounds` e `_resolve_target_years`
- FAZ: em `app/services/fipe_on_demand_lookup_service.py`, extrair a lógica de leitura de `gte`/`lte` que já existe dentro de `_build_pseudo_listing` (linhas 30-40) para uma função `_extract_year_bounds(filters) -> tuple[int | None, int | None]` (mesma tolerância a valor não numérico: `try/except (ValueError, TypeError) -> None` por posição). Adicionar `_resolve_target_years(gte, lte, current_year, max_years) -> list[int]` exatamente conforme o contrato acima. Não alterar ainda `_build_pseudo_listing` nem `_process_one_fipe_lookup` nesta etapa.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py` (adicionar testes 1-5 do plano)
- EXEMPLO E/S: `_resolve_target_years(2018, None, 2026, 5) == [2022, 2023, 2024, 2025, 2026]`; `_resolve_target_years(None, 2008, 2026, 5) == [2004, 2005, 2006, 2007, 2008]`
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k resolve_target_years` → 5/5 passam
- ESCALA SE: validação falhar 2x seguidas com a mesma lógica, ou os testes 1-5 do plano exigirem uma âncora diferente da PREM-02 para algum caso não previsto.

### Etapa 3: marca conhecida em `_build_pseudo_listing` + parâmetro `year`
- FAZ: em `_build_pseudo_listing`, adicionar parâmetro `year=_UNSET` (sentinel `_UNSET = object()` definido no topo do módulo). Se `year is _UNSET`: usar `_extract_year_bounds(filters)` e reproduzir exatamente a lógica atual (`gte` se houver, senão `lte`, senão `None`) para preservar o teste `test_pseudo_listing_year_prefers_gte` sem alteração. Se `year is not _UNSET`: usar o valor recebido diretamente (pode ser `None`). Para marca/modelo: antes de aplicar a heurística legada (primeiro token), consultar `db.query(FipeCatalogEntry.brand_name).distinct()` (precisa receber `db: Session` como novo argumento posicional da função — atualizar os 2 call-sites existentes, `_process_one_fipe_lookup`, para passar `db`), normalizar (`.strip().lower()`) e comparar contra os tokens normalizados da query buscando a maior sequência contígua de tokens da query que bata com uma marca conhecida (ex.: marca de duas palavras teria prioridade sobre marca de uma palavra, mas nenhuma marca do catálogo atual é composta — implementar de forma genérica mesmo assim, sem assumir marca de 1 palavra). Se achar, `make` = texto original da marca (capitalização de `brand_name` da entrada do catálogo), `model` = tokens restantes da query (excluindo os consumidos), na ordem original, unidos por espaço. Se não achar, aplicar a heurística legada inalterada.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py` (testes 6-10 do plano)
- EXEMPLO E/S: query=`"honda fit s"`, catálogo tem `brand_name="Honda"` → `make="Honda", model="fit s"`. query=`"fit honda"`, mesmo catálogo → `make="Honda", model="fit"`. query=`"Foo Bar"`, catálogo sem "Foo"/"Bar" como marca → `make="Foo", model="Bar"` (legado).
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k "pseudo_listing"` → todos os testes de pseudo_listing (novos e existentes) passam
- ESCALA SE: `test_pseudo_listing_year_prefers_gte` ou `test_pseudo_listing_no_year_filter_is_none` (testes já existentes) quebrarem — sinal de que a mudança de assinatura regrediu o comportamento default, que deveria ser bit-a-bit idêntico.

### Etapa 4 [sensível]: loop de anos-alvo em `_process_one_fipe_lookup` + diagnóstico
- FAZ: reescrever `_process_one_fipe_lookup` conforme o contrato descrito acima (passos 1-7): calcular `target_years` via Etapas 1-2, iterar em ordem crescente chamando `_build_pseudo_listing(wishlist, filters, db, year=y)` e `resolve_listing_to_fipe_candidates`, acumular `outcomes`, aplicar a árvore de decisão final (done > api_error/retry > skipped), e SEMPRE gravar `system_logs(db, "info", "fipe_lookup", "fipe on-demand lookup outcome", payload={"wishlist_id": str(wishlist.id), "outcomes": outcomes, "final_status": <status>})` antes do commit final do request. Preservar exatamente a semântica de `attempts`/`last_error`/`fipe_lookup_max_attempts` que existe hoje para o caso `api_error`.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py` (testes 11-13 do plano; atualizar/remover os testes antigos `test_process_marks_skipped_when_no_candidate` e `test_process_marks_skipped_when_insufficient_data` SE E SOMENTE SE eles quebrarem por causa do novo loop — caso contrário mantê-los como estão, cobrindo o caso de 1 único ano-alvo)
- EXEMPLO E/S: wishlist com `year gte=2020, lte=2022` (3 anos-alvo), catálogo com candidato válido e fresco só para 2021 → `outcomes` tem 3 entradas, `final_status == "done"`, `system_logs` recebe 1 linha com os 3 outcomes.
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q` → 100% verde (suíte completa do arquivo, incluindo testes antigos e novos)
- ESCALA SE: um teste antigo do arquivo quebrar de um jeito que não seja resolvível preservando a REGRA "pelo menos um ano coberto e fresco = done" (ex.: se a spec e a suíte antiga discordarem sobre o que "done" significa quando há múltiplos anos).

### Etapa 5: log de erro em `enqueue_fipe_lookup_for_wishlist`
- FAZ: no bloco `except Exception as exc` de `enqueue_fipe_lookup_for_wishlist` (linhas 68-71), adicionar, antes do `db.rollback()`, uma chamada a `system_logs_service.log(db, "error", "fipe_lookup", "enqueue_failed", {"wishlist_id": str(wishlist.id), "error": str(exc)})` envolta em `try/except Exception: pass` (o próprio log não pode derrubar o fluxo se `db` já estiver em estado inválido — mesmo padrão defensivo usado em `notifications_queue_service.py` linhas 93-109). Manter o `print()` existente.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py` (teste 14 do plano)
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k enqueue` → todos os testes de enqueue (existentes + novo) passam
- ESCALA SE: `system_logs_service.log` exigir uma sessão de banco em estado que o `db.rollback()` (chamado logo depois) invalide antes do commit do log — se isso ocorrer, inverter a ordem (log antes do rollback) é a correção óbvia, não uma decisão nova; aplicar direto sem escalar.

### Etapa 6 [sensível]: fallback de FIPE no pipeline de notificações
- FAZ: em `app/services/notifications_queue_service.py`, adicionar `_fallback_fipe_price_via_catalog(db, listing)` conforme o contrato acima (import de `resolve_listing_to_fipe_candidates` e `_ensure_month` de `app.services.fipe_catalog_resolver_service`, e `FipeCatalogEntry` de `app.models.fipe_catalog_entry`). No trecho que hoje calcula `fipe = next((fipe_rows.get(k) for k in lkeys if k in fipe_rows), None)` (linha 140), quando `fipe is None`, chamar `fipe = _fallback_fipe_price_via_catalog(db, listing)` antes de passar para `score_ad`.
- TOCA: `app/services/notifications_queue_service.py`, `tests/test_notifications_queue_service.py` (arquivo novo — testes 15-17 do plano)
- EXEMPLO E/S: anúncio Honda Fit 2008 sem linha em `FipePrice`; `FipeCatalogEntry` com `brand_name="Honda", model_name="Fit", model_year=2008, price=Decimal("32000.00")`, mês = mês mais recente do catálogo → `score_ad` recebe `fipe_price=Decimal("32000.00")`.
- VALIDA COM: `pytest tests/test_notifications_queue_service.py -q` → 3/3 passam
- ESCALA SE: `resolve_listing_to_fipe_candidates` exigir um objeto `listing` com atributos que o `CarListing` real não tenha (ex.: `version`, `fuel_type`) — checar `app/models/car_listing.py` antes de escalar; se o atributo existir com nome diferente, ajustar direto sem escalar.

### Etapa 7: regressão completa
- FAZ: rodar a suíte completa do repositório e confirmar 100% verde.
- TOCA: nenhum arquivo de produção (só validação)
- VALIDA COM: `pytest tests/ -q` → exit code 0, sem falhas nem erros de coleta
- ESCALA SE: qualquer teste fora dos arquivos tocados por esta spec quebrar (indica efeito colateral não previsto em algum dos contratos acima).

## Riscos conhecidos e mitigação

| Risco | Etapa | Mitigação já embutida na spec |
|---|---|---|
| Loop de anos-alvo multiplica chamadas à API FIPE por request | 4 | `fipe_lookup_year_expand_max=5` (PREM-01) limita o teto; loop para no primeiro `api_error` (PREM-05), não tenta os anos restantes na mesma passada |
| Fallback em `notifications_queue_service` degrada latência do envio de notificações (consulta extra ao catálogo por anúncio sem match em `FipePrice`) | 6 | Só executa quando `fipe_rows.get(key) is None` (mesma frequência de hoje em que o comparativo já vinha vazio); `resolve_listing_to_fipe_candidates` é só leitura de banco, sem chamada de API externa |
| Detecção de marca por `ilike` pode confundir modelo com marca em catálogos futuros com nomes ambíguos (ex.: marca "Fox" vs modelo "Fox" da VW) | 3 | Fora de escopo tratar (não-objetivo); comportamento legado permanece como fallback determinístico quando a heurística nova não achar nada |
| Mudança na árvore de decisão de `_process_one_fipe_lookup` altera silenciosamente quando um request vira "done" vs "skipped" | 4 | Testes 11-13 fixam o contrato ("done" se qualquer ano cobrir; "skipped" só se todos falharem) com exemplos concretos; testes antigos do arquivo continuam rodando como regressão |
| Fallback usa mês errado e nunca encontra candidato (regressão silenciosa) | 6 | PREM-03 fixa explicitamente `_ensure_month(db, None)`, não `current_reference_month()`, com a justificativa registrada |

## Análise de consistência (preenchida antes de liberar)

- [x] Todo requisito do objetivo é coberto por ao menos um critério de aceitação (REQ-001 a REQ-007, cada um com comando `pytest -k`).
- [x] Toda etapa consome apenas artefatos criados por etapas anteriores ou pré-existentes verificados (grafo de dependências acima; Etapa 4 depende de 1 e 3; Etapa 6 é independente e usa apenas código já existente hoje).
- [x] Nenhuma contradição entre contratos, exemplos e testes (exemplos E/S das Etapas 2, 3, 4 e 6 batem com os testes 1-5, 6-10, 11-13 e 15 do plano, respectivamente).
- [x] Nenhuma frase delega julgamento — pontos que pareciam exigir julgamento (ordem de decisão done/skipped/api_error, âncora do intervalo de ano, qual mês usar no fallback) foram resolvidos em PREM-01 a PREM-06 e no contrato de `_resolve_target_years`/`_process_one_fipe_lookup`/`_fallback_fipe_price_via_catalog`.
