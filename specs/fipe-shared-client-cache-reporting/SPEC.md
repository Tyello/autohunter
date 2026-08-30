# Spec: Compartilhar FipeApiClient no batch on-demand e reportar hit-rate do cache [spec-kit: T2]

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 12 iterações totais
- Parada: todos os REQs verdes | orçamento estourado → humano
- Registro: specs/fipe-shared-client-cache-reporting/RUN.md (append-only)

## Contexto (achado da investigação, não repetir análise)
- `resolve_listing_to_fipe_candidates` já consulta `FipeCatalogEntry` (fonte quente) ANTES de qualquer
  chamada à API FIPE — isso já existe e não muda.
- `FipeApiClient` já tem `_CatalogTTLCache` (TTL configurável via `settings.fipe_catalog_cache_ttl_s`)
  para `reference_tables`/`brands`/`models`/`model_years` — isso já existe e não muda.
- `FipeRateLimiter.acquire()` bloqueia a thread chamadora com `time.sleep`, mas o job `fipe_lookup`
  já roda isolado em `ThreadPoolExecutor(2)` próprio (`app/scheduler/run.py:224`), separado dos pools
  `http` e `browser` (`run.py:220-221`). Ou seja, o bloqueio hoje NÃO prende `http`/`browser`.
- **Bug real encontrado**: em `process_pending_fipe_lookups` (app/services/fipe_on_demand_lookup_service.py:799),
  um único `reactive_client = FipeApiClient()` é compartilhado entre as requests do caminho REATIVO
  (linha 814), mas o caminho CLÁSSICO (`_process_one_fipe_lookup`, linha ~650) cria seu próprio
  `bootstrap_client = FipeApiClient()` A CADA REQUEST que precisa de bootstrap. Isso perde o cache TTL
  de marca/modelo/ano E cria um `FipeRateLimiter` novo (estado de throttle isolado) a cada request
  clássica, mesmo dentro do mesmo batch.

## Objetivo
Unificar em UM único `FipeApiClient` por chamada de `process_pending_fipe_lookups`, compartilhado entre
o caminho reativo e o caminho clássico, para que o cache TTL de catálogo e o estado do rate limiter
sejam reaproveitados entre TODAS as requests do batch (não só entre as reativas). Reportar hit-rate do
cache e volume de chamadas evitadas no log existente do batch (`system_logs` componente `fipe_lookup`).
Não alterar o modelo de threading/pool do rate limiter (já isolado, ver Contexto).

## Requisitos
- REQ-001: QUANDO `process_pending_fipe_lookups` processa um batch com pelo menos 1 request pendente,
  O SISTEMA DEVE criar no máximo 1 instância de `FipeApiClient` para o batch inteiro, usada tanto pelo
  caminho reativo quanto pelo clássico — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -k shared_client`
- REQ-002: QUANDO `_process_one_fipe_lookup` precisa de bootstrap, O SISTEMA DEVE usar o client recebido
  como parâmetro em vez de instanciar um novo `FipeApiClient()` — verificado por:
  `pytest tests/test_fipe_on_demand_lookup_service.py -k bootstrap_reuses_shared_client`
- REQ-003: QUANDO `process_pending_fipe_lookups` termina de processar um batch com pelo menos 1 request
  pendente, O SISTEMA DEVE incluir no dict de retorno a chave `fipe_cache` com `{"hits": int, "misses": int, "hit_rate": float}`
  (`hit_rate` = `hits / (hits + misses)` arredondado com `round(x, 4)`, ou `0.0` se `hits + misses == 0`)
  — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -k cache_stats_reported`
- REQ-004: QUANDO `process_pending_fipe_lookups` é chamado sem nenhuma request pendente, O SISTEMA DEVE
  retornar o dict de counters sem a chave `fipe_cache` (nenhum client foi criado) — verificado por:
  `pytest tests/test_fipe_on_demand_lookup_service.py -k no_pending_no_cache_key`
- REQ-005: QUANDO existem requests reativas E clássicas no mesmo batch e ambas resolvem a mesma marca/modelo
  via API, O SISTEMA DEVE registrar pelo menos 1 hit de cache atribuível ao reaproveitamento entre os dois
  caminhos — verificado por: `pytest tests/test_fipe_on_demand_lookup_service.py -k cross_path_cache_hit`

## Não-objetivos
- Não alterar `FipeRateLimiter` (nem sua API, nem seu modelo de threading/sleep).
- Não alterar `_CatalogTTLCache` (TTL, chaves, escopo por instância) — já atende ao objetivo de cache.
- Não alterar `resolve_listing_to_fipe_candidates` nem o uso de `FipeCatalogEntry` como fonte quente —
  já existe e já é usado antes de qualquer chamada à API.
- Não mudar o pool/executor do scheduler (`app/scheduler/run.py`) — isolamento já existe e é suficiente.
- Não adicionar infraestrutura de métricas nova (dashboard, tabela) — reporte vai só no log existente.

## Premissas assumidas (gate de fechamento)
- PREM-01: "reduzir chamadas externas" no cenário de bootstrap é atendido por reaproveitar o cache TTL
  já existente entre caminhos, não por criar um cache novo — confirmado pelo usuário (resposta à pergunta
  de clarificação: "Sim, esse é o gap real").
- PREM-02: o rate limiter não precisa de fila/pacer dedicado porque o isolamento de pool já existe —
  confirmado pelo usuário (resposta: "Só documentar + corrigir o bug do client duplicado").
- PREM-03: o relatório de hit-rate vai no log `system_logs` componente `fipe_lookup` já existente —
  confirmado pelo usuário (resposta: "No log existente do batch").
- PREM-04: quando `pending` está vazio, nenhum `FipeApiClient` é criado (evita custo de criar `requests.Session`
  à toa) e portanto `fipe_cache` não aparece no retorno — comportamento já existente para o `reactive_client`
  atual, mantido igual para o client unificado.

## Decisões tomadas
- O client compartilhado é criado incondicionalmente quando `pending` não é vazio (independente de haver
  request reativa) — simplifica a condição atual (`any(r.listing_make is not None for r in pending)`) e
  cobre o caso "só requests clássicas" que hoje NÃO tem client compartilhado nenhum.
- `_process_one_fipe_lookup` passa a receber `client: FipeApiClient` como parâmetro obrigatório (mesma
  posição usada por `_process_one_reactive_fipe_lookup(db, client, request)`, para manter a mesma convenção
  de assinatura entre os dois caminhos).
- Testes existentes que fazem `monkeypatch.setattr(svc, "_process_one_fipe_lookup", wrapper)` com wrapper de
  assinatura `(db_arg, request_arg)` precisam ser atualizados para `(db_arg, client_arg, request_arg)` como
  parte desta spec (não é escopo separado — é consequência mecânica da mudança de assinatura).
- `hit_rate` é calculado no momento do report (não armazenado no `_CatalogTTLCache`), reaproveitando
  `client.cache_stats()` que já existe e retorna `{"hits": int, "misses": int}`.

## Etapas

### Etapa 1: Unificar client no batch e propagar para o caminho clássico (REQ-001, REQ-002, REQ-004)
- FAZ:
  1. Em `app/services/fipe_on_demand_lookup_service.py`, altere a assinatura de `_process_one_fipe_lookup`
     de `def _process_one_fipe_lookup(db: Session, request: FipeLookupRequest) -> str:` para
     `def _process_one_fipe_lookup(db: Session, client: FipeApiClient, request: FipeLookupRequest) -> str:`.
  2. Dentro de `_process_one_fipe_lookup`, remova a linha `bootstrap_client = FipeApiClient()` (atualmente
     dentro do bloco `if not bootstrap_attempted and pseudo_listing.make and pseudo_listing.model and year is not None:`)
     e substitua todo uso de `bootstrap_client` nesse escopo pelo parâmetro `client` recebido (isso inclui
     a chamada a `_resolve_fipe_brand_and_models(bootstrap_client, ...)` → `_resolve_fipe_brand_and_models(client, ...)`
     e a chamada a `_bootstrap_fipe_catalog_entries_for_year(db, bootstrap_client, ...)` → `_bootstrap_fipe_catalog_entries_for_year(db, client, ...)`).
     Mantenha a variável `bootstrap_resolved`/`bootstrap_attempted` como estão (só a origem do client muda).
  3. Em `process_pending_fipe_lookups`, substitua o bloco:
     ```python
     reactive_client = FipeApiClient() if any(r.listing_make is not None for r in pending) else None
     ```
     por:
     ```python
     client = FipeApiClient() if pending else None
     ```
     e atualize o comentário acima dela para refletir que agora é compartilhado por AMBOS os caminhos
     (reativo e clássico) do batch, não só o reativo.
  4. Atualize as duas chamadas dentro do loop `for request in pending:`:
     - `outcome = _process_one_reactive_fipe_lookup(db, reactive_client, request)` → `outcome = _process_one_reactive_fipe_lookup(db, client, request)`
     - `outcome = _process_one_fipe_lookup(db, request)` → `outcome = _process_one_fipe_lookup(db, client, request)`
  5. Atualize o bloco final de cache stats (linhas ~841-842) que hoje referencia `reactive_client` para
     referenciar `client` (ver Etapa 2 para o formato completo do relatório — não implemente REQ-003 ainda
     nesta etapa, só troque o nome da variável para não quebrar).
- TOCA: `app/services/fipe_on_demand_lookup_service.py`
- VALIDA COM: `python -m py_compile app/services/fipe_on_demand_lookup_service.py` sem erro; nenhuma
  referência a `bootstrap_client` ou `reactive_client` remanescente no arquivo
  (`grep -n "bootstrap_client\|reactive_client" app/services/fipe_on_demand_lookup_service.py` retorna vazio).
- ESCALA SE: a função `_process_one_fipe_lookup` tiver outro ponto de criação de `FipeApiClient()` além do
  já identificado na linha ~650, ou a assinatura atual do arquivo já não corresponder ao trecho citado acima
  (arquivo mudou desde a investigação).

### Etapa 2: Implementar relatório de cache stats com hit_rate (REQ-003, REQ-004)
- FAZ:
  1. Em `app/services/fipe_on_demand_lookup_service.py`, adicione uma função auxiliar antes de
     `process_pending_fipe_lookups`:
     ```python
     def _fipe_cache_report(client: FipeApiClient) -> dict:
         stats = client.cache_stats()
         hits = stats.get("hits", 0)
         misses = stats.get("misses", 0)
         total = hits + misses
         hit_rate = round(hits / total, 4) if total else 0.0
         return {"hits": hits, "misses": misses, "hit_rate": hit_rate}
     ```
  2. Substitua o bloco final de `process_pending_fipe_lookups` (o que hoje faz
     `if reactive_client is not None and hasattr(reactive_client, "cache_stats"): counters["fipe_cache"] = reactive_client.cache_stats()`)
     por:
     ```python
     if client is not None and hasattr(client, "cache_stats"):
         counters["fipe_cache"] = _fipe_cache_report(client)
     ```
- TOCA: `app/services/fipe_on_demand_lookup_service.py`
- VALIDA COM: `python -m py_compile app/services/fipe_on_demand_lookup_service.py` sem erro.
- ESCALA SE: `client.cache_stats()` não existir mais ou retornar formato diferente de `{"hits": int, "misses": int}`.

### Etapa 3: Atualizar testes existentes afetados pela mudança de assinatura (REQ-001, REQ-002)
- FAZ:
  1. Em `tests/test_fipe_on_demand_lookup_service.py`, localize o wrapper `def flaky(db_arg, request):`
     (próximo à linha 842, que chama `original(db_arg, request)` onde `original = svc._process_one_fipe_lookup`).
     Altere para `def flaky(db_arg, client_arg, request):` chamando `original(db_arg, client_arg, request)`.
  2. Localize o wrapper `def tracked_classic(db_arg, request_arg):` (próximo à linha 1613, que chama
     `original_classic(db_arg, request_arg)` onde `original_classic = svc._process_one_fipe_lookup`).
     Altere para `def tracked_classic(db_arg, client_arg, request_arg):` chamando
     `original_classic(db_arg, client_arg, request_arg)`.
  3. Rode a suíte completa do arquivo e corrija QUALQUER outra chamada direta a `_process_one_fipe_lookup(db, request)`
     com 2 argumentos posicionais que a busca abaixo revelar (mesma correção: inserir o client na 2ª posição).
     Busca: `grep -n "_process_one_fipe_lookup(" tests/test_fipe_on_demand_lookup_service.py`
- TOCA: `tests/test_fipe_on_demand_lookup_service.py`
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q` — todos os testes existentes (contagem
  igual à anterior à mudança) devem passar em verde, nenhum teste removido.
- ESCALA SE: houver alguma chamada direta a `_process_one_fipe_lookup` no arquivo de teste cujo contexto
  não deixe claro qual client passar (ex.: nenhum client mockado disponível no escopo do teste).

### Etapa 4: Novos testes de contrato para REQ-001 a REQ-005
- FAZ: adicione a `tests/test_fipe_on_demand_lookup_service.py` (próximo aos testes existentes de
  `process_pending_fipe_lookups`, reaproveitando os helpers `_make_wishlist`/`_make_catalog_entry`/fakes
  de `FipeApiClient` já usados no arquivo, ex. o padrão de `FakeClient` da linha ~1621):

  1. `test_shared_client_used_for_both_paths` (REQ-001): crie 1 request reativa (`listing_make` setado) e
     1 request clássica (`listing_make=None`) no mesmo batch. Monkeypatch `svc.FipeApiClient` para uma
     factory que conta quantas vezes foi instanciada (`call_count["n"] += 1` em `__init__`) e retorna um
     fake funcional (reuse do `FakeClient` já existente no arquivo, adaptando para contar instâncias).
     Rode `svc.process_pending_fipe_lookups(db, limit=10)`. Assert `call_count["n"] == 1`.

  2. `test_bootstrap_reuses_shared_client` (REQ-002): monkeypatch `svc.FipeApiClient` com uma classe fake
     que registra `id(self)` em uma lista de instâncias criadas a cada `__init__`, e cujos métodos
     (`get_latest_reference_table`, `get_brands`, `get_models`, `get_model_years`, `get_price`) retornam
     dados válidos mínimos (reuse do padrão de `FakeClient` da linha ~1621). Crie 2 requests clássicas
     (`listing_make=None`) que ambas caiam no branch de bootstrap (mock `resolve_listing_to_fipe_candidates`
     para retornar `{"status": "no_match", "best_candidate": None}`, wishlist com make/model/year setados).
     Rode o batch. Assert que a lista de instâncias criadas tem tamanho 1 (mesma instância usada nas 2
     requests clássicas).

  3. `test_cache_stats_reported` (REQ-003): monkeypatch `svc.FipeApiClient` com uma fake cujo `cache_stats()`
     retorna `{"hits": 3, "misses": 1}`. Rode o batch com pelo menos 1 request pendente. Assert
     `out["fipe_cache"] == {"hits": 3, "misses": 1, "hit_rate": 0.75}`.

  4. `test_no_pending_no_cache_key` (REQ-004): rode `svc.process_pending_fipe_lookups(db, limit=10)` sem
     nenhuma `FipeLookupRequest` pendente no banco. Assert `"fipe_cache" not in out`.

  5. `test_cross_path_cache_hit` (REQ-005): monkeypatch `svc.FipeApiClient` com uma fake que usa um
     `_CatalogTTLCache`-like real (pode ser o próprio `_CatalogTTLCache` importado de
     `app.services.fipe_api_client`, instanciado dentro do fake) para `get_brands`/`get_models`, de forma
     que a 2ª chamada com a mesma marca/modelo seja um hit. Crie 1 request reativa e 1 clássica que resolvam
     para a MESMA marca/modelo (ex. ambas "honda civic"), ambas caindo em bootstrap. Rode o batch. Assert
     `out["fipe_cache"]["hits"] >= 1`.

- TOCA: `tests/test_fipe_on_demand_lookup_service.py`
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q` — os 5 novos testes citados passam,
  mais todos os testes pré-existentes do arquivo continuam verdes.
- ESCALA SE: os fakes de `FipeApiClient` já existentes no arquivo não exportarem hooks suficientes para
  contar instâncias/hits sem duplicar lógica de negócio (nesse caso, decida a forma mínima de instrumentação
  e prossiga — não é decisão de design, é detalhe de teste).

### Etapa 5: Documentar achado sobre isolamento do rate limiter (sem mudança funcional)
- FAZ: em `app/services/fipe_rate_limiter.py`, no docstring da classe `FipeRateLimiter` (linhas 8-16),
  adicione ao final do docstring existente (não reescreva o resto):
  ```
  Nota: acquire() bloqueia a thread chamadora via time.sleep. Isso é seguro porque o job
  fipe_lookup roda isolado em seu próprio ThreadPoolExecutor (ver app/scheduler/run.py,
  executor "fipe_lookup"), separado dos pools "http" e "browser" — o bloqueio aqui não
  afeta outros workers do scheduler.
  ```
- TOCA: `app/services/fipe_rate_limiter.py`
- VALIDA COM: `pytest tests/test_fipe_rate_limiter.py -q` — todos os testes continuam passando inalterados
  (mudança é só de docstring).
- ESCALA SE: o arquivo `app/scheduler/run.py` não tiver mais um executor nomeado `"fipe_lookup"` isolado
  (nesse caso a premissa documentada seria falsa — pare e reporte).

## Critérios de aceitação globais
1. Todos os REQ-001 a REQ-005 cobertos por teste com evidência (arquivo:linha) — 5 novos testes na Etapa 4.
2. Suíte completa dos arquivos tocados verde: `pytest tests/test_fipe_on_demand_lookup_service.py tests/test_fipe_rate_limiter.py tests/test_fipe_lookup_job.py tests/test_fipe_api_client.py -q`
3. Nenhum teste pré-existente removido ou com asserção enfraquecida.
