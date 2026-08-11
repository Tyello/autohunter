# Spec: Job mensal FIPE — paralelismo controlado + batching de escrita  [spec-kit: T3]

`[spec-kit: T3 — 9pts: arquivos=2 (5+: fipe_api_client.py, fipe_catalog_crawler.py, fipe_monthly_sync_service.py, settings.py, scheduler/fipe_update_job.py), decisões=2 (desenho de rate limiter compartilhado, estratégia de commit em lote), risco=1 (não altera schema/contrato público, mas toca pipeline de produção), novidade=1 (concorrência é variação de padrão já usado no repo — ThreadPoolExecutor não existe ainda para IO, mas threading já é usado em outros pontos), verif=2 (concorrência exige testes de thread-safety, não triviais)]`

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Verificação final: spec-verifier independente, fix loop máx. 3 iterações
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 20 iterações totais
- Parada: veredito APROVADO do verifier | orçamento estourado → humano
- Registro: specs/003-fipe-monthly-job-perf/RUN.md (append-only)

## Contexto (investigação feita nesta sessão)

A spec `001-fipe-monthly-job-fix` (implementada, commit `765cb69`) resolveu o problema de o job nunca rodar, adicionando um crawler (`app/services/fipe_catalog_crawler.py`) que varre `ConsultarTabelaDeReferencia → ConsultarMarcas → ConsultarModelos → ConsultarAnoModelo → ConsultarValorComTodosParametros`. O job agora roda, mas leva **~10 horas**.

Duas causas raiz identificadas por leitura direta do código (não estimativa):

1. **Execução 100% sequencial, um único worker.** `crawl_latest_fipe_prices` (`app/services/fipe_catalog_crawler.py:8-84`) é 4 loops `for` aninhados (marca → modelo → ano/combustível → preço), cada iteração da folha faz exatamente 1 chamada HTTP síncrona via `client.get_price(...)`. Para o catálogo completo de carros (~85-90 marcas × ~30 modelos × ~15 combinações ano/combustível em média) isso é da ordem de **40.000+ chamadas HTTP**, cada uma bloqueando a thread até a resposta completa antes de sequer começar a preparar a próxima. Com `fipe_api_rate_limit_ms=800` (`app/core/settings.py:324`) e latência de rede típica de uma API pública não otimizada, o tempo real por chamada é `max(800ms, latência_de_rede)` **somado sequencialmente** — não há sobreposição alguma entre "esperando resposta da chamada N" e "preparando/pausando para a chamada N+1". 40.000 × 800ms já são ~8,9h só de throttle; a latência de rede não sobreposta explica o restante até ~10h.
2. **Throttle nunca se recupera após um 429.** `FipeApiClient._increase_throttle()` (`app/services/fipe_api_client.py:117-118`) dobra `_current_throttle_ms` a cada 429 (até `fipe_api_max_throttle_ms=5000`) mas **não existe nenhum mecanismo de recuperação** — uma vez dobrado, o throttle fica nesse patamar mais lento pelo resto da varredura inteira (podem ser horas), mesmo que os 429s tenham sido um pico isolado no início. Isso significa que qualquer 429 esporádico infla desproporcionalmente o tempo total.

Separadamente, a escrita em banco (`upsert_fipe_catalog_entries`, `app/services/fipe_monthly_sync_service.py:93-153`) já faz um único `db.commit()` no final (não é 1 commit por linha), mas faz **1 `SELECT` por linha** (`db.query(FipeCatalogEntry).filter(...).first()`, linha 135-140) para checar se a entrada já existe — para 40.000+ linhas isso é 40.000+ round-trips de leitura ao Supabase antes mesmo de considerar os writes, contribuindo ao Disk IO Budget.

## Objetivo

1. Paralelizar a varredura do crawler com um pool de workers controlado, mantendo o **mesmo teto agregado de requisições/segundo** já configurado (`fipe_api_rate_limit_ms`) — a paralelização elimina o tempo ocioso de esperar cada resposta antes de iniciar a próxima chamada (latência não mais serializada), sem aumentar a taxa real de chamadas ao servidor FIPE.
2. Adicionar recuperação gradual do throttle após 429s (hoje só sobe, nunca desce), para que um pico isolado de 429 não penalize o restante da varredura inteira.
3. Eliminar o padrão de 1 SELECT por linha em `upsert_fipe_catalog_entries`, pré-buscando as entradas existentes em lote (chunks) e comitando em lotes periódicos (não 1 transação gigante nem 1 commit por linha).
4. Adicionar logging de progresso (throughput, ETA, tempo decorrido) e duração total registrada, para monitorar execuções futuras sem precisar instrumentar manualmente.

## Não-objetivos

- Não aumentar `fipe_api_rate_limit_ms` além do valor atual nem remover o throttle — a paralelização não deve elevar o número de requisições/segundo enviadas ao servidor FIPE, apenas eliminar espera ociosa. Se o usuário decidir no futuro que a API tolera mais volume, isso é uma mudança de config operacional, não desta spec.
- Não mudar o formato de saída do crawler (`normalize_external_fipe_rows` continua recebendo o mesmo shape de linha).
- Não mudar o escopo do crawl (continua full catalog — decisão já tomada na clarificação: manter full crawl, paralelizar+batchear em vez de reduzir escopo).
- Não migrar para `asyncio`/`aiohttp` — usa `concurrent.futures.ThreadPoolExecutor` (threading), consistente com `requests` já usado no projeto (spec 001 já decidiu não trocar `requests` por lib assíncrona).
- Não alterar `FipeSyncRun`/`FipeUpdateRun` schemas.

## Premissas assumidas (gate de fechamento)

- PREM-01: O verdadeiro limite de requisições/segundo tolerado pela API pública da FIPE é desconhecido (não documentado oficialmente) — o valor `fipe_api_rate_limit_ms=800` continua sendo o teto de referência; esta spec não o valida nem o desafia, apenas garante que múltiplos workers, juntos, não excedam esse teto agregado.
- PREM-02: `requests.Session` não é thread-safe para mutação concorrente de estado compartilhado (headers/cookies são geralmente seguros para leitura, mas a doc oficial recomenda 1 sessão por thread para uso pesado concorrente) — cada worker do pool usa sua própria instância de `FipeApiClient` (e portanto sua própria `Session`), mas todas compartilham o mesmo objeto `FipeRateLimiter` para pacing.
- PREM-03: O Supabase Postgres tolera transações um pouco maiores que "1 commit por linha" sem estourar IO budget, desde que não seja "1 transação gigante para 40k linhas" — chunking em lotes de `fipe_catalog_upsert_chunk_size` (default 1000) linhas por commit é o meio-termo assumido, sem dado de produção para calibrar precisamente; se o Disk IO Budget não melhorar o suficiente, é um ajuste de config futuro (não desta spec).
- PREM-04: `on_progress` (usado para logging humano) pode ser chamado de múltiplas threads concorrentemente; não precisa ser thread-safe internamente além de garantir que a escrita de log (via `system_logs_service.log`/`print`) não corrompa a saída — um lock simples em torno da chamada resolve.

## Decisões tomadas

- Novo módulo `app/services/fipe_rate_limiter.py` com classe `FipeRateLimiter`: encapsula `_current_throttle_ms`, `_last_request_time`, contador de sucessos consecutivos, tudo protegido por `threading.Lock`. Expõe `acquire()` (bloqueia até poder prosseguir, igual à `_throttle()` atual) e `on_success()` / `on_429()` para reportar o resultado de cada chamada.
- `FipeApiClient` passa a aceitar um `rate_limiter: FipeRateLimiter | None = None` no construtor; se `None`, cria um próprio (comportamento atual preservado para uso single-thread e para os testes existentes que não passam `rate_limiter`). O crawler cria **um único `FipeRateLimiter`** e o compartilha entre N instâncias de `FipeApiClient` (uma por worker), garantindo que o teto agregado de requisições/segundo continue sendo `1000/rate_limit_ms`, não importa quantos workers existam.
- Recuperação de throttle: após `fipe_throttle_recovery_after_successes` (default 20) chamadas bem-sucedidas consecutivas (sem 429 no meio), `_current_throttle_ms` é reduzido pela metade da distância até `rate_limit_ms` base (nunca abaixo dele), e o contador de sucessos zera. Um 429 zera o contador de sucessos e dobra o throttle imediatamente (comportamento atual preservado).
- Concorrência do crawler: `fipe_crawler_concurrency` (novo setting, default 6) workers via `concurrent.futures.ThreadPoolExecutor`. O crawl é feito em 3 rodadas paralelas com dependência estrita entre rodadas (cada rodada só pode iniciar após a anterior terminar, pois usa os códigos retornados por ela): Rodada 1 já é 1 chamada (tabela de referência) + 1 chamada (marcas) — sequencial, barato. Rodada 2 (modelos por marca) paraleliza `client.get_models` entre marcas. Rodada 3 (anos por modelo) paraleliza `client.get_model_years` entre pares (marca, modelo). Rodada 4 (preço por combinação) paraleliza `client.get_price` entre todas as combinações (marca, modelo, ano, combustível) — a rodada dominante em volume.
- Erros de chamadas individuais continuam sendo capturados por combinação (`FipeApiError` → loga e pula), sem abortar a varredura, igual ao comportamento atual — agora também deve capturar exceções genéricas por task no `ThreadPoolExecutor` (uma falha em uma `Future` nunca deve derrubar as demais).
- `upsert_fipe_catalog_entries` pré-busca em lote: antes do loop principal, monta a lista de `identity_key` candidatas (calculadas a partir das linhas de entrada, mesma lógica de `_build_identity_key`), busca todas as `FipeCatalogEntry` existentes que casam `(reference_month, vehicle_type, source, identity_key IN (...))` em chunks de `fipe_catalog_upsert_chunk_size` (default 1000) identity_keys por `SELECT ... WHERE identity_key IN (...)`, monta um dict `{identity_key: FipeCatalogEntry}` em memória, e o loop principal consulta esse dict em vez de fazer um `SELECT` por linha. Commits acontecem a cada `fipe_catalog_upsert_chunk_size` linhas processadas (não 1 gigante, não 1 por linha).
- Logging de progresso: o crawler loga (via `on_progress`, que o job mensal encaminha para `system_logs_service.log` com throttle de frequência) a cada marca concluída (comportamento já existente) mais um log agregado a cada `fipe_crawler_progress_log_every` (default 10) marcas concluídas com: chamadas feitas até agora, tempo decorrido, taxa de chamadas/segundo, ETA estimado (linear, baseado no total de combinações já enumeradas na Rodada 3). `FipeUpdateRun.duration_ms` já registra a duração total ao final — nenhuma mudança de schema necessária.

## Contratos e schemas

### `app/services/fipe_rate_limiter.py` (novo módulo)

```python
class FipeRateLimiter:
    def __init__(self, *, rate_limit_ms: int, max_throttle_ms: int, recovery_after_successes: int = 20) -> None:
        """Estado compartilhado, protegido por threading.Lock: _current_throttle_ms
        (inicia em rate_limit_ms), _last_request_time (monotonic), _consecutive_successes."""

    def acquire(self) -> None:
        """Bloqueia (sob lock) a chamada até que _current_throttle_ms tenha decorrido
        desde a última chamada liberada por qualquer worker. Atualiza _last_request_time
        antes de liberar, igual à semântica de FipeApiClient._throttle() atual, mas
        thread-safe (múltiplos workers competem pelo mesmo relógio de emissão)."""

    def on_success(self) -> None:
        """Incrementa _consecutive_successes; se atingir recovery_after_successes,
        reduz _current_throttle_ms pela metade da distância até rate_limit_ms base
        (current = base + (current - base) / 2, arredondado, nunca abaixo de rate_limit_ms)
        e zera o contador."""

    def on_429(self) -> None:
        """Zera _consecutive_successes; dobra _current_throttle_ms até max_throttle_ms
        (mesma lógica de _increase_throttle() atual)."""
```

### `app/services/fipe_api_client.py` (modificado)

```python
class FipeApiClient:
    def __init__(self, *, rate_limit_ms=None, max_throttle_ms=None, max_retries=None,
                 timeout_s=None, rate_limiter: "FipeRateLimiter | None" = None) -> None:
        """Se rate_limiter for None, cria um FipeRateLimiter próprio (comportamento atual,
        preserva testes existentes que não passam rate_limiter). Se informado, usa o
        compartilhado em vez de manter _current_throttle_ms/_last_request_time locais."""
```
`_throttle()`, `_increase_throttle()` são substituídos por chamadas a `self._rate_limiter.acquire()` / `self._rate_limiter.on_429()` / `self._rate_limiter.on_success()` (novo — chamado após toda resposta 2xx sem `{"erro":...}`, para alimentar a recuperação).

### `app/services/fipe_catalog_crawler.py` (reescrito)

```python
def crawl_latest_fipe_prices(
    client_factory: Callable[[], FipeApiClient],
    *,
    limit_brands: int | None = None,
    concurrency: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """Assinatura muda de `client: FipeApiClient` para `client_factory: Callable[[], FipeApiClient]`
    (uma factory que cria uma nova instância por worker, todas compartilhando o mesmo
    rate_limiter — o crawler não sabe do rate_limiter diretamente, só chama a factory
    N vezes onde N = concurrency, default settings.fipe_crawler_concurrency).

    Fluxo: 1 client "coordenador" (primeira instância da factory) busca referência e
    marcas sequencialmente (barato). Rodada 2/3/4 usam ThreadPoolExecutor(max_workers=
    concurrency), cada worker pega uma instância própria de client via factory (round-robin
    ou 1 client por worker-slot, reaproveitada entre submits do mesmo worker), submete
    get_models/get_model_years/get_price por task. Resultados agregados com lock em volta
    da lista `rows` e do `on_progress`. Exceção de uma task (FipeApiError OU qualquer
    Exception) é capturada por task, logada via on_progress, não propaga.
    """
```
Nota de compatibilidade: chamadores existentes que hoje passam `client: FipeApiClient` direto (scripts, testes) precisam migrar para `client_factory=lambda: client` — mudança de assinatura é aceitável porque `crawl_latest_fipe_prices` é código interno (não é API pública externa), e todos os call sites estão neste mesmo repo (verificar com grep antes de codar a Etapa correspondente).

### `app/services/fipe_monthly_sync_service.py` (modificado)

```python
def upsert_fipe_catalog_entries(db, rows, *, reference_month, source="external_pipeline",
                                 dry_run=False, chunk_size: int | None = None) -> dict:
    """chunk_size default settings.fipe_catalog_upsert_chunk_size (1000). Pré-busca em lote:
    para cada chunk de identity_keys calculadas das rows válidas, 1 SELECT ... WHERE
    identity_key IN (...) AND reference_month=... AND vehicle_type=... AND source=...
    monta dict local. Loop principal usa o dict em vez de query individual. db.commit()
    a cada chunk_size linhas processadas (não 1 por linha, não 1 gigante no final)."""
```

### `app/core/settings.py` (novos campos, junto ao bloco `fipe_api_*` existente, linha 327)

```python
fipe_crawler_concurrency: int = 6
fipe_throttle_recovery_after_successes: int = 20
fipe_catalog_upsert_chunk_size: int = 1000
fipe_crawler_progress_log_every: int = 10
```

## Plano de testes

Convenções confirmadas (mesmas de spec 001): `pytest tests/<arquivo>.py -q`, `monkeypatch` direto em métodos/funções, sem libs de mock de HTTP externas, `time.sleep`/`time.monotonic` mockados para testes de timing.

1. `tests/test_fipe_rate_limiter.py::test_acquire_paces_single_thread` — sem threads, chama `acquire()` 2x com `time.monotonic`/`time.sleep` mockados, assert que a 2ª chamada dorme `~rate_limit_ms`.
2. `tests/test_fipe_rate_limiter.py::test_concurrent_acquire_respects_aggregate_rate` — spawna N=5 threads reais chamando `acquire()` em loop M vezes cada (rate_limit_ms baixo tipo 10ms para o teste rodar rápido); mede o tempo total decorrido (`time.monotonic()` real, sem mock — teste de integração leve) e assert que `total_calls * rate_limit_ms <= elapsed * 1.5` (tolerância) — prova que o agregado nunca excede a taxa combinada, mesmo com concorrência (teste não-raso: se o rate limiter não fosse thread-safe/compartilhado, N threads emitiriam muito mais rápido que o teto).
3. `tests/test_fipe_rate_limiter.py::test_on_429_doubles_then_recovers_after_successes` — chama `on_429()` (assert `_current_throttle_ms` dobrou), depois `on_success()` `recovery_after_successes` vezes, assert que `_current_throttle_ms` diminuiu (não voltou 100% de uma vez, mas é menor que o valor pós-429) — prova que a recuperação é gradual, não instantânea.
4. `tests/test_fipe_rate_limiter.py::test_recovery_never_goes_below_base_rate` — várias rodadas de sucesso sem nenhum 429 prévio; assert `_current_throttle_ms == rate_limit_ms` (nunca abaixo).
5. `tests/test_fipe_api_client.py::test_shared_rate_limiter_used_when_provided` — cria um `FipeRateLimiter` mock/spy, passa via `rate_limiter=`, faz uma chamada, assert que `acquire()`/`on_success()` do objeto passado foram chamados (não um interno).
6. `tests/test_fipe_api_client.py::test_default_rate_limiter_created_when_none` (regressão) — sem passar `rate_limiter`, comportamento idêntico ao atual (reexecuta os testes 429/backoff já existentes da spec 001 contra a nova implementação interna).
7. `tests/test_fipe_catalog_crawler.py::test_crawl_uses_client_factory_and_concurrency` — `client_factory` como `Mock` contável; roda com `concurrency=3` e um conjunto pequeno de marcas/modelos/anos fake; assert que a factory foi chamada múltiplas vezes (≥ 1 por worker) e que o resultado final é idêntico ao que o crawler sequencial antigo produziria para a mesma entrada (mesmo shape, mesmas linhas, ordem pode variar — comparar como `set`/chave).
8. `tests/test_fipe_catalog_crawler.py::test_individual_task_error_does_not_abort_crawl` (regressão, adaptado de spec 001) — uma das tasks de preço levanta exceção; assert que as demais completam e a exceção não propaga.
9. `tests/test_fipe_catalog_crawler.py::test_crawl_output_shape_matches_adapter` (regressão da spec 001, adaptada à nova assinatura) — mantém o teste não-raso de shape passando pelo adapter real.
10. `tests/test_fipe_catalog_crawler.py::test_progress_logging_reports_throughput_and_eta` — `on_progress` capturado numa lista; roda crawl com N marcas fake maior que `fipe_crawler_progress_log_every`; assert que pelo menos 1 mensagem de progresso agregado (contendo algo como "ETA"/tempo decorrido) foi emitida, além das mensagens por-marca já existentes.
11. `tests/test_fipe_monthly_sync_service.py::test_upsert_batches_select_instead_of_per_row` (REQ central, não-raso) — `db.query` espiado (contando chamadas); roda `upsert_fipe_catalog_entries` com 50 linhas fake e `chunk_size=10`; assert que o número de `SELECT`s emitidos é proporcional a `50/10 = 5` (chunks), não 50 (1 por linha) — prova a mudança real de padrão de IO.
12. `tests/test_fipe_monthly_sync_service.py::test_upsert_commits_per_chunk_not_once_or_per_row` — `db.commit` espiado; mesma entrada; assert contagem de commits ≈ número de chunks, não 1 nem 50.
13. `tests/test_fipe_monthly_sync_service.py::test_upsert_batched_result_matches_unbatched_baseline` (regressão, não-raso) — mesma lista de linhas rodada com `chunk_size=1000` (1 chunk) e com `chunk_size=5` (múltiplos chunks); assert que os counters finais (`inserted`, `updated`, `skipped_invalid`) são idênticos nos dois casos, e que o estado final do banco (query direta pós-run) é idêntico — prova que chunking não muda o resultado, só o padrão de IO.
14. `tests/test_fipe_update_job.py::test_job_passes_concurrency_setting_to_crawler` (regressão, adaptado) — `monkeypatch.setattr(settings, "fipe_crawler_concurrency", 3)`; `crawl_latest_fipe_prices` mockado capturando kwargs; assert `concurrency == 3` foi passado.

Total: **14 testes** (10 novos + 4 regressão adaptados de spec 001, contados porque a assinatura muda).

## Grafo de dependências

Onda 1 (paralelas, sem dependência mútua):
- Etapa 1: Novas settings

Onda 2 (depende da Etapa 1):
- Etapa 2: `FipeRateLimiter` (novo módulo)

Onda 3 (depende da Etapa 2):
- Etapa 3: `FipeApiClient` aceita `rate_limiter` compartilhado

Onda 4 (depende da Etapa 3):
- Etapa 4 [sensível]: `fipe_catalog_crawler.py` reescrito com concorrência + client_factory + progresso

Onda 5 (independente da Onda 2-4, pode rodar em paralelo):
- Etapa 5 [sensível]: `upsert_fipe_catalog_entries` com pré-busca em lote + commits por chunk

Onda 6 (depende das Etapas 4 e 5):
- Etapa 6: Ajustar `app/scheduler/fipe_update_job.py` e `scripts/run_fipe_monthly_job.py` (client_factory, concurrency) para a nova assinatura do crawler

Onda 7 (depende de todas):
- Etapa 7: Rodar suíte completa de regressão (`pytest tests/test_fipe*.py tests/test_scheduler_fipe*.py -q`) e ajustar quebras não previstas

## Etapas

### Etapa 1: Novas settings de performance  (contrato de settings acima)
- FAZ: Adicionar em `app/core/settings.py`, logo após o bloco `fipe_api_*` (linha 327), os 4 campos do contrato acima. Adicionar as mesmas variáveis (comentadas com default) em `.env.example`, junto ao bloco `FIPE_API_*` (linhas 179-182).
- TOCA: `app/core/settings.py`, `.env.example`
- VALIDA COM: `python -c "from app.core.settings import settings; assert settings.fipe_crawler_concurrency == 6; assert settings.fipe_throttle_recovery_after_successes == 20; assert settings.fipe_catalog_upsert_chunk_size == 1000; assert settings.fipe_crawler_progress_log_every == 10; print('OK')"` deve imprimir `OK`
- ESCALA SE: bloco `fipe_api_*` não estiver na linha 324-327 como descrito (realidade ≠ spec)

### Etapa 2: `FipeRateLimiter`  (contrato acima; testes 1-4)
- FAZ: Criar `app/services/fipe_rate_limiter.py` implementando exatamente `FipeRateLimiter` do contrato — `threading.Lock` protegendo `_current_throttle_ms`, `_last_request_time` (via `time.monotonic()`), `_consecutive_successes`. `acquire()` reusa a lógica de `_throttle()` atual (dormir a diferença), mas sob lock (cuidado: o `time.sleep` NÃO deve segurar o lock — copiar o padrão "calcular wait sob lock, liberar lock, dormir fora do lock, e no fim de acquire só readquirir lock para atualizar `_last_request_time`" para não travar outros workers enquanto um dorme).
- TOCA: `app/services/fipe_rate_limiter.py` (novo)
- VALIDA COM: `pytest tests/test_fipe_rate_limiter.py -q` (testes 1-4) — 4 testes verdes
- ESCALA SE: decisão residual sobre o desenho exato do lock/sleep (ex: se o teste 2 mostrar contenção que o desenho simples não resolve) — reportar com os números observados

### Etapa 3: `FipeApiClient` usa `FipeRateLimiter` compartilhado  (contrato acima; testes 5-6)
- FAZ: Modificar `app/services/fipe_api_client.py`: construtor aceita `rate_limiter: FipeRateLimiter | None = None`; se `None`, cria `FipeRateLimiter(rate_limit_ms=self._rate_limit_ms, max_throttle_ms=self._max_throttle_ms, recovery_after_successes=settings.fipe_throttle_recovery_after_successes)`. Remove `_current_throttle_ms`/`_last_request_time`/`_throttle()`/`_increase_throttle()` do `FipeApiClient` (agora vivem só no `FipeRateLimiter`). `_request()` chama `self._rate_limiter.acquire()` no lugar de `self._throttle()`; chama `self._rate_limiter.on_429()` no branch de 429 (no lugar de `self._increase_throttle()`); chama `self._rate_limiter.on_success()` logo após uma resposta 2xx sem `{"erro":...}` ser aceita (novo).
- TOCA: `app/services/fipe_api_client.py`
- VALIDA COM: `pytest tests/test_fipe_api_client.py -q` (todos, incluindo testes 5-6 novos e os 6 testes da spec 001 que devem continuar verdes sem mudança de comportamento observável)
- ESCALA SE: algum teste existente da spec 001 (429/backoff/timeout) quebrar de um jeito que não seja resolvido só redirecionando as chamadas para o rate limiter (indicaria acoplamento que a spec não previu)

### Etapa 4: Crawler com concorrência  [sensível]  (contrato acima; testes 7-10)
- FAZ: Reescrever `app/services/fipe_catalog_crawler.py`: `crawl_latest_fipe_prices` muda a assinatura para `client_factory: Callable[[], FipeApiClient]` (documentar a quebra de compatibilidade no docstring). Fluxo: 1 instância "coordenadora" via `client_factory()` busca `get_latest_reference_table()` e `get_brands()` (sequencial). Rodada 2 (modelos): `ThreadPoolExecutor(max_workers=concurrency or settings.fipe_crawler_concurrency)`, cada task chama `client_factory().get_models(...)` para 1 marca (pode instanciar 1 client por task ou reusar via `threading.local()` — decisão livre do executor, desde que cada thread não compartilhe `Session` entre si). Rodada 3 (anos): mesmo padrão, 1 task por par (marca, modelo) resultante da rodada 2. Rodada 4 (preços): mesmo padrão, 1 task por combinação (marca, modelo, ano, combustível) resultante da rodada 3 — a rodada dominante. Cada task individual captura `FipeApiError` e `Exception` genérica, chama `on_progress` (sob lock) com mensagem de erro, e retorna `None`/lista vazia em vez de propagar — o `as_completed()`/`executor.map` do orquestrador nunca deve ver uma exceção não tratada de uma task de folha. Acumula `rows` sob lock. A cada `fipe_crawler_progress_log_every` marcas concluídas (rodada 4), emite via `on_progress` uma linha com: total de combinações processadas até agora, tempo decorrido desde o início do crawl, taxa (combinações/segundo), ETA (linear, baseado no total de combinações já enumeradas na rodada 3 menos as já feitas).
- TOCA: `app/services/fipe_catalog_crawler.py`
- VALIDA COM: `pytest tests/test_fipe_catalog_crawler.py -q` (testes 7-10, mais o teste 9 de regressão de shape) — todos verdes
- ESCALA SE: a mudança de assinatura (`client` → `client_factory`) quebra algum call site fora deste repo (não deveria existir, mas verificar com `grep -rn "crawl_latest_fipe_prices" --include=*.py .` antes de reescrever — se aparecer em código fora de `app/`, `scripts/`, `tests/`, escalar)

### Etapa 5: `upsert_fipe_catalog_entries` com pré-busca em lote  [sensível]  (contrato acima; testes 11-13)
- FAZ: Modificar `app/services/fipe_monthly_sync_service.py`: adicionar parâmetro `chunk_size: int | None = None` (default `settings.fipe_catalog_upsert_chunk_size`). Antes do loop principal, para cada linha válida (após as mesmas validações já existentes de `model_name`/`price`/`identity_key`), acumular `(payload, identity_key)` em uma lista. Depois, iterar essa lista em fatias de `chunk_size`: para cada fatia, montar a lista de `identity_key`s, rodar `db.query(FipeCatalogEntry).filter(FipeCatalogEntry.reference_month==month, FipeCatalogEntry.vehicle_type==payload["vehicle_type"], FipeCatalogEntry.source==source_norm, FipeCatalogEntry.identity_key.in_(chunk_keys)).all()` (nota: `vehicle_type` pode variar por linha — se todas as linhas do lote tiverem o mesmo `vehicle_type`/`source` na prática atual, agrupar a pré-busca por esse par; caso contrário, incluir `vehicle_type` na chave do dict local em vez de no filtro SQL, e no WHERE filtrar só por `reference_month`+`source`+`identity_key IN (...)`, filtrando `vehicle_type` em memória — decisão do executor, documentar qual optou), montar dict `{(vehicle_type, identity_key): entry}`, aplicar insert/update em memória (mesma lógica atual de `setattr`/`FipeCatalogEntry(**payload)`), `db.commit()` ao final de cada fatia (não a cada linha, não só no final de tudo).
- TOCA: `app/services/fipe_monthly_sync_service.py`
- VALIDA COM: `pytest tests/test_fipe_monthly_sync_service.py -q` (testes 11-13, mais os testes existentes desse arquivo sem regressão)
- ESCALA SE: `FipeCatalogEntry` não tiver as colunas `reference_month`/`vehicle_type`/`source`/`identity_key` como hoje (realidade ≠ spec — não deveria acontecer, é o modelo já lido nesta sessão)

### Etapa 6: Integrar nos call sites  (REQ implícito de não quebrar o job)
- FAZ: Ajustar `app/scheduler/fipe_update_job.py` e `scripts/run_fipe_monthly_job.py` (e qualquer outro call site encontrado via `grep -rn "crawl_latest_fipe_prices\|FipeApiClient(" --include=*.py app/ scripts/`) para: criar 1 `FipeRateLimiter` compartilhado, passar `client_factory=lambda: FipeApiClient(rate_limiter=shared_limiter)` para `crawl_latest_fipe_prices`, passar `concurrency=settings.fipe_crawler_concurrency`.
- TOCA: `app/scheduler/fipe_update_job.py`, `scripts/run_fipe_monthly_job.py`
- VALIDA COM: `pytest tests/test_fipe_update_job.py -q` (teste 14 e regressão) — todos verdes
- ESCALA SE: existir um call site adicional não mapeado pela spec que use `crawl_latest_fipe_prices(client=...)` posicionalmente de um jeito incompatível com a nova assinatura

### Etapa 7: Regressão completa
- FAZ: Rodar a suíte completa de testes FIPE e corrigir quebras não previstas pela spec (sem mudar o comportamento pretendido das etapas anteriores).
- TOCA: qualquer arquivo de teste FIPE que precise de ajuste pontual não coberto nas etapas 1-6
- VALIDA COM: `pytest tests/test_fipe_api_client.py tests/test_fipe_catalog_crawler.py tests/test_fipe_monthly_sync_service.py tests/test_fipe_update_job.py tests/test_scheduler_fipe_registration.py tests/test_fipe_rate_limiter.py -q` — 100% verde
- ESCALA SE: uma quebra exigir revisitar uma decisão já tomada em etapa anterior (não é mais "ajuste pontual", é retrabalho de design)

## Riscos conhecidos e mitigação

| Risco | Etapa | Mitigação já embutida na spec |
|---|---|---|
| Concorrência introduz race condition que corrompe `rows` ou duplica linhas | 4 | Lock explícito em volta do append à lista compartilhada; teste 7 compara resultado com baseline sequencial |
| Rate limiter compartilhado vira gargalo de lock e anula o ganho de paralelismo | 2 | `acquire()` libera o lock antes de dormir (só segura o lock para ler/escrever o relógio); teste 2 mede empiricamente que o agregado ainda bate o teto configurado |
| Pré-busca em lote consome muita memória para catálogos muito grandes | 5 | Chunking (não carrega tudo de uma vez); `chunk_size` configurável para ajuste fino se necessário |
| Mudança de assinatura de `crawl_latest_fipe_prices` quebra algo fora do previsto | 4, 6 | `grep` explícito por todos os call sites antes de reescrever (documentado nas condições de escala) |
| Recuperação de throttle volta rápido demais e provoca nova onda de 429s | 2 | Recuperação é "metade da distância até a base", não instantânea; 429 zera o contador e dobra de novo imediatamente — resposta reativa continua mais rápida que a recuperação |

## Análise de consistência (preenchida antes de liberar)
- [x] Todo objetivo (paralelismo, batching, progresso/logging) é coberto por etapas com VALIDA COM verificável
- [x] Toda etapa consome apenas artefatos de etapas anteriores: Etapa 3 usa `FipeRateLimiter` da Etapa 2; Etapa 4 usa `FipeApiClient` com rate_limiter da Etapa 3; Etapa 6 usa o crawler da Etapa 4 e o upsert da Etapa 5 (ondas 4/5 paralelas, convergem na Etapa 6)
- [x] Nenhuma contradição entre contratos e testes — cruzado `FipeRateLimiter` (4 métodos) contra testes 1-4, `FipeApiClient` contra testes 5-6, crawler contra testes 7-10, upsert contra testes 11-13
- [x] Nenhuma frase delega julgamento sem critério mecânico — único ponto de flexibilidade documentado é a Etapa 5 (agrupar pré-busca por vehicle_type ou filtrar em memória), explicitamente marcado como "decisão do executor, documentar qual optou" porque ambas são corretas e a spec não tem informação para preferir uma sem rodar o código
