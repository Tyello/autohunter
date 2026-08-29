# 012 — Paralelização dos grupos de URL em run_source_for_all_wishlists

## Tier

`[spec-kit: T3 — 9pts: arquivos=2 (source_execution_service.py + settings.py + novo módulo concurrency), decisões=2 (semântica de falha, escopo do paralelismo — já resolvidas via AskUserQuestion), risco=2 (afeta caminho crítico de scheduler/queue em produção), novidade=2 (1º uso de ThreadPoolExecutor + SQLAlchemy multi-thread no repo), verif=2 (testes novos de concorrência + benchmark)]`

## Objetivo

Em `app/services/source_execution_service.py`, a função `run_source_for_all_wishlists` executa o loop `for url, g in groups.items()` (scrape+ingest+match por grupo de URL de uma mesma source) **sequencialmente** e, hoje, **aborta a execução no primeiro grupo que falha** (blocked/error/bug): grupos restantes nunca chegam a ser scrapeados nesse tick. Esta spec paraleliza esse loop com `ThreadPoolExecutor`, respeitando:

- (a) rate-limit/backoff por source (`source_states`, via `source_backoff_service`) — decisão de backoff continua sendo tomada **uma vez** por chamada, na thread principal;
- (b) um teto de concorrência configurável (`settings`);
- (c) isolamento de `Session` SQLAlchemy por thread (nunca compartilhar a `Session` recebida como parâmetro `db` entre threads).

Não muda o resultado do matching/ingestão para os grupos que **de fato rodam** — só a ordem/concorrência e a cobertura (grupos que antes eram pulados por causa de uma falha anterior na lista agora rodam, conforme decisão do usuário, ver Decisões).

## Não-objetivos

- Não paraleliza entre **sources diferentes** (o loop em `app/scheduler/run.py` que itera sobre múltiplas sources continua sequencial). Fora de escopo por decisão explícita do usuário.
- Não muda a lógica de `scrape_ingest_match`, `classify_error`, matching, dedupe ou ingestão em si — apenas quem chama, com qual `Session`/`ctx`/`HealthCollector`, e em qual ordem/concorrência.
- Não adiciona retry automático de grupos falhos dentro do mesmo tick.
- Não muda o schema do banco nem `source_states`/`source_runs`.

## Decisões tomadas (via AskUserQuestion, já resolvidas — não reabrir)

- **DEC-01 (semântica de falha)**: "Isolar falhas" — todos os grupos rodam até o fim independentemente de falhas em outros grupos. A decisão de backoff/status do RUN (o dict retornado por `run_source_for_all_wishlists` e o `SourceRun`/`SourceState` gravados) é baseada na **primeira falha por ordem original de `groups.items()`** (não por ordem de conclusão — concorrência não pode tornar o resultado não-determinístico). Grupos bem-sucedidos que rodaram antes ou depois dessa falha, na ordem original, têm seu scrape+ingest+match **efetivado e contabilizado** no agregado (`total_found`, `total_inserted`, etc.) mesmo quando outro grupo falhou.
- **DEC-02 (escopo)**: Paralelismo é só entre grupos de URL dentro de uma mesma chamada/source. O semáforo "por-source" existe para limitar quantas requisições concorrentes batem no mesmo site **mesmo quando duas chamadas concorrentes de `run_source_for_all_wishlists` para a mesma source acontecem ao mesmo tempo** (ex.: scheduler tick + queue worker), não para paralelizar entre sources.
- **DEC-03 (sessão)**: Cada grupo processado em paralelo abre sua própria `Session` via `SessionLocal()` (`app/db/session.py`), faz commit e fecha ao final do seu processamento. A `Session` `db` recebida como parâmetro pela função só é usada na thread principal (checks iniciais, decisão de backoff, `record_run`, `mark_*`, `emit_event`, `log`, `reconcile_listing_activity_for_source_run`, commit final).

## Premissas assumidas (PREM)

- **PREM-01**: `ScrapeContext` (`app/sources/types.py`) é um dataclass congelado mas mutado via `object.__setattr__` como canal lateral (`_last_adapter_meta`, ver `app/services/source_execution_helpers.py`) para carregar metadados do adapter de volta ao chamador. Hoje `ctx` é construído **uma vez** (`build_scrape_context(db, src)`, linha ~374) e reusado por todos os grupos — isso **não é thread-safe**: dois grupos rodando em paralelo escrevendo em `ctx._last_adapter_meta` colidem. Esta spec assume que a correção é construir um `ctx` **novo por grupo/thread** (chamando `build_scrape_context` com a Session da própria thread), nunca reusar a instância entre threads. `[não verificada — assumida por leitura do código, mas é o único caminho seguro identificado]`
- **PREM-02**: `HealthCollector` (`app/health/collector.py`) faz `self._counters[name] += inc` sem lock — não é thread-safe para chamadas concorrentes de `.inc()`/`.count()`/`.add_note()`/`.set_error()` no mesmo objeto (pode haver leituras/escritas perdidas). Esta spec assume que a correção é dar a **cada grupo/thread seu próprio `HealthCollector`** e, ao final, mesclar os contadores/notas/último-erro no `HealthCollector` principal (só na thread principal, sem lock necessário porque a mescla é sequencial pós-`join`).
- **PREM-03**: O teto de concorrência do `ThreadPoolExecutor` (quantas threads processam grupos de uma mesma chamada) e o teto do semáforo por-source (quantas requisições de rede concorrentes por source, entre chamadas) são dois números diferentes e configuráveis separadamente. Nomes assumidos: `source_group_max_workers` (padrão 4) e `source_max_concurrent_per_source` (padrão 2). Se o usuário preferir nomes diferentes, é um ajuste mecânico, não uma re-abertura da spec.
- **PREM-04**: SQLite (usado nos testes, `tests/conftest.py`, `SessionLocal`/`engine` compartilhados com `check_same_thread=False`) tolera múltiplas Sessions concorrentes escrevendo desde que o timeout padrão do driver (5s) não estoure — não precisamos configurar `busy_timeout` explicitamente para os testes desta spec (poucos grupos, commits rápidos). Se um teste flakar por "database is locked", isso é sinal de que essa premissa caiu e deve ser tratada como escalação, não contornada com retry solto no teste.

## Contratos / assinaturas

### `app/core/settings.py` — novos campos (Etapa 1)
```python
# Concorrência de scraping por grupo de URL dentro de uma mesma source (ver specs/012)
source_group_max_workers: int = 4
source_max_concurrent_per_source: int = 2
```

### `app/services/source_concurrency.py` (novo módulo, Etapa 2)
```python
def get_source_semaphore(source: str) -> threading.Semaphore:
    """Retorna (criando se necessário) o semáforo compartilhado para `source`,
    dimensionado por settings.source_max_concurrent_per_source no momento da criação.
    Thread-safe: criação protegida por lock; chamadas concorrentes para a mesma
    source sempre recebem a MESMA instância de Semaphore (processo/módulo, não por-request)."""
```

### `app/services/source_execution_service.py` — refatoração (Etapas 3 e 4)

Extrair uma função pura de classificação de falha (Etapa 3, sem mudança de comportamento):
```python
def _classify_group_error(
    *, res: dict, src: str, url: str, health: HealthCollector
) -> dict:
    """Reproduz exatamente a lógica hoje inline (linhas ~427-478) que decide
    category/status_cls/retryable/http_status/bucket/wm_diag a partir de `res`,
    e aplica os efeitos correspondentes no `health` recebido (inc/count/add_note/set_error).
    Não toca `db`. Retorna um dict com essas chaves para o chamador decidir o que
    gravar (mark_blocked/mark_error/mark_bug, record_run, emit_event, log)."""
```

Função de processamento por grupo, chamada em thread própria (Etapa 4):
```python
def _process_group_isolated(
    *, src: str, url: str, g: dict, flags, plugin, v2_scraper, kind: str, cfg
) -> dict:
    """Abre sua própria Session via SessionLocal(), constrói seu próprio ScrapeContext
    (build_scrape_context) e seu próprio HealthCollector, roda scrape_ingest_match,
    classifica erro (via _classify_group_error) se aplicável, faz commit, fecha a Session
    no finally, e retorna um dict serializável (sem objetos SQLAlchemy anexados à Session
    fechada) com tudo que a thread principal precisa: ok, res, health_snapshot
    (contadores/buckets/notas/last_error do HealthCollector local), url, query.
    NUNCA deixa exceção escapar: qualquer exceção não capturada por scrape_ingest_match
    vira um resultado sintético {"ok": False, "reason": "error", "is_bug": True, ...} —
    isso é o que garante que 1 grupo falhando (inclusive por bug de infraestrutura,
    não só erro de scrape) não derruba o ThreadPoolExecutor nem os demais grupos."""
```

## Arquivos e mudanças

1. **`app/core/settings.py`** — adicionar os dois campos de PREM-03, com comentário curto citando `specs/012`.
2. **`app/services/source_concurrency.py`** (novo) — `get_source_semaphore`.
3. **`app/services/source_execution_service.py`**:
   - Extrair `_classify_group_error` (Etapa 3) a partir do bloco `if not res.get("ok"):` atual (linhas ~427-478), preservando exatamente os mesmos valores calculados (`category`, `retryable`, `http_status`, `status_cls`, `bucket`, `wm_diag`) e os mesmos efeitos em `health` (`health.inc("blocked",1)`, `health.inc("errors",1)`, `health.count(bucket,1)`, `health.add_note(...)`, `health.set_error(...)`). Os call sites que hoje fazem `mark_blocked`/`mark_error`/`mark_bug`/`record_run`/`emit_event`/`log`/`return` continuam onde estão, mas passam a consumir os valores retornados por `_classify_group_error` em vez de recalculá-los inline.
   - Adicionar `_process_group_isolated` (Etapa 4).
   - Substituir o `for url, g in groups.items(): ...` por: montar `group_items = list(groups.items())` (ordem original preservada), submeter cada item a um `ThreadPoolExecutor(max_workers=min(len(group_items), max(1, settings.source_group_max_workers)))`, com cada tarefa adquirindo `get_source_semaphore(src)` antes de chamar `scrape_ingest_match` (o `with` do semáforo deve envolver só a chamada de rede/scrape+ingest, não a abertura/fechamento da Session), coletar os resultados na **ordem original** de `group_items` (usar `dict` de future→índice ou `executor.map`-like ordenado — não pode ordenar por conclusão), e então:
     - Mesclar os `HealthCollector` locais no `health` principal, na ordem original.
     - Encontrar a **primeira** entrada com `ok=False` na ordem original (se houver) e aplicar exatamente o mesmo tratamento que existe hoje para essa condição (mark_blocked/mark_error/mark_bug + record_run + emit_event + log + return), usando o resultado de `_classify_group_error` já computado para aquele grupo.
     - Para **todas** as entradas com `ok=True` (independentemente de estarem antes ou depois da falha, na ordem original), aplicar exatamente o mesmo acumulo que existe hoje (`group_summaries.append(...)`, `total_found +=`, etc.).
     - Se não houver nenhuma falha, seguir o caminho de sucesso existente inalterado.

## Plano de testes (escrito antes da implementação)

Todos os testes existentes que chamam `run_source_for_all_wishlists` (listados abaixo) devem continuar passando **sem modificação**, pois cada um usa 1 wishlist ⇒ 1 grupo ⇒ paralelismo é um no-op observável:
`tests/test_source_execution_service.py`, `tests/test_listing_activity_service.py`, `tests/test_wishlist_initial_run.py`, `tests/test_search_dedup_routing.py`, `tests/test_source_execution_wishlist_eligibility.py`, `tests/test_scheduler_source_config_bootstrap.py`, `tests/test_scheduler_shutdown.py`.

Novos testes (arquivo sugerido: `tests/test_source_execution_parallel_groups.py`):

1. **REQ-001** (isolamento de falha): com 3 wishlists gerando 3 grupos distintos, mockar `scrape_ingest_match`/o dispatch para que o **2º grupo** (por ordem original) falhe (`ok=False, reason="error"`) e os outros dois tenham sucesso. Usar um contador thread-safe (`threading.Lock` + dict, ou `queue.Queue`) para provar que os 3 grupos foram de fato invocados (nenhum foi pulado por causa da falha de outro). Assertar que o retorno da função reflete a falha do grupo 2 (mesma semântica de erro que o código sequencial produziria se só o grupo 2 existisse) e que isso é determinístico mesmo rodando o teste várias vezes (ex.: `pytest --count=5` local ou um loop de 5 iterações dentro do teste).
2. **REQ-002** (ordem determinística da falha "vencedora"): com 2 grupos falhando (grupo A na posição 0, grupo B na posição 2, sucesso na posição 1), independentemente de qual thread termina primeiro (forçar isso com um `time.sleep` maior no grupo A do mock), o erro reportado deve ser sempre o do grupo A (posição 0), nunca o do grupo B.
3. **REQ-003** (isolamento de Session): monkeypatch em `SessionLocal` (ou no ponto onde `_process_group_isolated` a invoca) para registrar o `id()` de cada Session aberta; com N≥2 grupos, assertar que N Sessions distintas foram abertas e que nenhuma delas é a `db` passada como parâmetro para `run_source_for_all_wishlists`, e que cada Session foi fechada (`session.close()` chamado) ao final.
4. **REQ-004** (teto de concorrência respeitado): com `settings.source_group_max_workers` monkeypatchado para 2 e 5 grupos cujo mock de scrape dorme um curto intervalo e incrementa/decrementa um contador de "em voo", assertar que o pico de "em voo" nunca excede 2.
5. **REQ-005** (semáforo por-source entre chamadas concorrentes): com `settings.source_max_concurrent_per_source` monkeypatchado para 1, disparar duas chamadas de `run_source_for_all_wishlists` para a MESMA source em threads diferentes (cada uma com 1 grupo cujo mock dorme um curto intervalo) e assertar que elas nunca executam a seção crítica (a chamada de scrape) ao mesmo tempo (medir sobreposição de intervalos).
6. **REQ-006** (latência do tick — benchmark, não assert de performance dura): com N=8 wishlists/grupos e um mock de scrape com `time.sleep(0.05)` cada, medir `duration_ms` retornado pela função ANTES (rodando a versão sequencial simulada, chamando os grupos um a um fora da função, como baseline documentado no teste) e DEPOIS (chamando `run_source_for_all_wishlists` de fato, paralelo). Assertar que o tempo paralelo é menor que 60% do tempo sequencial esperado (8 * 0.05s = 0.4s ⇒ esperar < 0.24s com `source_group_max_workers=4`). Não é um teste de regressão de performance rígido (não falha o CI por variação de máquina além dessa margem folgada) — é a evidência pedida de "medir latência do tick antes/depois".
7. **REQ-007** (agregação preservada no caminho feliz): com N grupos todos com sucesso e valores de `found`/`inserted`/`matched` distintos por grupo, assertar que os totais agregados batem com a soma esperada — prova que paralelizar não muda o RESULTADO de matching/ingestão reportado, só a ordem de execução.

## Critérios de aceitação (EARS)

- **REQ-001**: QUANDO um grupo entre vários falha, o sistema DEVE continuar executando (scrape+ingest+match) todos os demais grupos da mesma chamada, sem pular nenhum.
- **REQ-002**: QUANDO mais de um grupo falha na mesma chamada, o sistema DEVE reportar/aplicar backoff com base no grupo que falhou primeiro na ORDEM ORIGINAL de `groups.items()`, independentemente da ordem de conclusão das threads.
- **REQ-003**: O sistema NUNCA DEVE usar a `Session` `db` recebida como parâmetro da função para o scrape/ingest/match de um grupo processado em thread separada — cada grupo DEVE abrir e fechar sua própria `Session`.
- **REQ-004**: O sistema DEVE limitar o número de grupos processados simultaneamente ao valor de `settings.source_group_max_workers`.
- **REQ-005**: O sistema DEVE limitar, via semáforo por-source compartilhado entre chamadas concorrentes, o número de requisições de scrape simultâneas para a mesma source ao valor de `settings.source_max_concurrent_per_source`.
- **REQ-006**: A latência do tick (campo `duration_ms` do retorno) para N grupos com custo de scrape simulado DEVE ser mensuravelmente menor em paralelo do que a soma sequencial equivalente (evidenciado por teste/benchmark).
- **REQ-007**: Para grupos bem-sucedidos, os totais agregados (`found`, `inserted`, `matched`, `queued`, `already_notified`, `reason_buckets`, `thumb_present`) retornados pela função DEVEM ser idênticos ao que a soma por grupo produziria — o conteúdo do resultado de matching/ingestão não muda, só a execução.

## Grafo de dependências entre etapas

```
Etapa 1 (settings)  ──┐
Etapa 2 (semáforo)  ──┼──> Etapa 3 (extrair _classify_group_error, sem mudar comportamento)
                       │         │
                       │         v
                       └──> Etapa 4 (concorrência real: ThreadPoolExecutor + Session/ctx/health por thread)
                                  │
                                  v
                            Etapa 5 (testes novos + benchmark + fechamento)
```
Etapas 1 e 2 são independentes entre si (poderiam rodar em paralelo), mas ambas precisam terminar antes da Etapa 4. Etapa 3 é pré-requisito de Etapa 4 (mesmo arquivo, mudança sequencial). Etapa 5 depende de tudo.

## Etapas de execução

### Etapa 1 — Settings [não sensível]
**Objetivo**: adicionar `source_group_max_workers: int = 4` e `source_max_concurrent_per_source: int = 2` em `app/core/settings.py`, próximos aos outros campos de scheduler/backoff (~linha 279-294).
**Toca**: `app/core/settings.py`.
**Valida com**: `python -c "from app.core.settings import settings; assert settings.source_group_max_workers == 4; assert settings.source_max_concurrent_per_source == 2"`.
**Condição de escalação**: nenhuma prevista (mudança mecânica).

### Etapa 2 — Módulo de semáforo por-source [não sensível]
**Objetivo**: criar `app/services/source_concurrency.py` com `get_source_semaphore(source: str) -> threading.Semaphore`, thread-safe (lock de criação), dimensionado por `settings.source_max_concurrent_per_source` no momento da primeira criação para aquela source; chamadas repetidas com o mesmo `source` (case-insensitive, mesma normalização `.strip().lower()` usada no resto do arquivo) retornam a MESMA instância.
**Toca**: `app/services/source_concurrency.py` (novo), `tests/test_source_concurrency.py` (novo).
**Valida com**: teste novo que (a) chama `get_source_semaphore("olx")` duas vezes e assert `is` a mesma instância; (b) chama para `"OLX"` e `"olx"` e assert mesma instância (normalização); (c) chama para `"webmotors"` e assert instância DIFERENTE da de `"olx"`; (d) monkeypatcha `settings.source_max_concurrent_per_source` para 3 antes de criar uma semáforo novo e confirma `semaphore._value == 3` (CPython; comentar que é implementação-específica mas aceitável para teste).
**Condição de escalação**: se `threading.Semaphore` não expuser `_value` de forma confiável no ambiente de teste, reportar e usar alternativa (ex.: adquirir 3x e confirmar que a 4ª tentativa com `acquire(blocking=False)` falha).

### Etapa 3 — Extrair `_classify_group_error` (refactor, sem mudança de comportamento) [sensível]
**Objetivo**: extrair a lógica hoje inline em `run_source_for_all_wishlists` (bloco `if not res.get("ok"):` até o cálculo de `run_summary_err`, aproximadamente linhas 427-478) para uma função `_classify_group_error(*, res: dict, src: str, url: str, health: HealthCollector) -> dict` que retorna pelo menos `{"reason", "category", "retryable", "http_status", "status_cls", "bucket", "wm_diag"}`. A função aplica no `health` recebido os mesmos efeitos que o código já aplica hoje (`health.inc(...)`, `health.count(...)`, `health.add_note(...)`, `health.set_error(...)`). Os call sites (`mark_blocked`/`mark_error`/`mark_bug`/`record_run`/`emit_event`/`log`/`return`) continuam fazendo exatamente o que fazem hoje, só passam a ler os campos do dict retornado em vez de variáveis locais calculadas inline. **Nenhum teste existente pode mudar de comportamento** — isso é puramente extração.
**Toca**: `app/services/source_execution_service.py`.
**Valida com**: suíte completa relevante roda sem alterações e sem falhas: `pytest tests/test_source_execution_service.py tests/test_listing_activity_service.py tests/test_wishlist_initial_run.py tests/test_search_dedup_routing.py tests/test_source_execution_wishlist_eligibility.py tests/test_scheduler_source_config_bootstrap.py tests/test_scheduler_shutdown.py -q`.
**Condição de escalação**: se extrair a função exigir mudar a ordem de qualquer side-effect observável (ex.: ordem de chamadas a `health.inc` vs `health.count`), escalar — a extração deve ser comportamentalmente idêntica byte a byte no que é observável por teste.

### Etapa 4 — Concorrência real (ThreadPoolExecutor + Session/ctx/health por thread) [sensível]
**Objetivo**: implementar `_process_group_isolated` e substituir o loop sequencial pelo `ThreadPoolExecutor` conforme especificado em "Arquivos e mudanças", usando `get_source_semaphore` (Etapa 2) e `_classify_group_error` (Etapa 3). Cada grupo processado em thread própria: (1) abre `SessionLocal()`, (2) constrói seu próprio `ScrapeContext` via `build_scrape_context(sua_session, src)` — NUNCA reusa o `ctx` construído na thread principal (ver PREM-01), (3) constrói seu próprio `HealthCollector(source_name=src)` — NUNCA usa o `health` da thread principal diretamente (ver PREM-02), (4) roda `scrape_ingest_match`, (5) faz commit da sua Session, (6) fecha a Session no `finally` mesmo em caso de exceção, (7) nunca deixa exceção escapar da função — qualquer exceção não capturada vira `{"ok": False, "reason": "error", "is_bug": True, "error": f"{type(e).__name__}: {e}"}`. A thread principal: submete todos os grupos ao `ThreadPoolExecutor(max_workers=min(len(group_items), max(1, settings.source_group_max_workers)))`, coleta os resultados preservando a ordem original de `group_items`, mescla os `HealthCollector`s locais no `health` principal (na ordem original), encontra a primeira falha na ordem original (se houver) e aplica o tratamento de erro existente, e acumula os sucessos como hoje.
**Toca**: `app/services/source_execution_service.py`.
**Valida com**: suíte completa da Etapa 3 continua passando (grupos únicos = comportamento sequencial preservado) + testes novos REQ-001 a REQ-005 e REQ-007 de `tests/test_source_execution_parallel_groups.py` (a serem escritos nesta etapa, conforme "Plano de testes").
**Condição de escalação**: se `scrape_ingest_match` ou `build_scrape_dispatch` tiverem alguma outra mutação de estado compartilhado além de `ctx._last_adapter_meta` e dos contadores de `HealthCollector` (ex.: algum cache module-level não thread-safe descoberto durante a implementação), PARAR e escalar — não decidir sozinho se é seguro ignorar.

### Etapa 5 — Benchmark de latência + fechamento [não sensível]
**Objetivo**: adicionar o teste REQ-006 (benchmark antes/depois) em `tests/test_source_execution_parallel_groups.py`, e um `RUN.md` de fechamento resumindo os números observados (duration_ms sequencial simulado vs. paralelo real, para N=8).
**Toca**: `tests/test_source_execution_parallel_groups.py`, `specs/012-parallel-source-group-scraping/RUN.md`.
**Valida com**: `pytest tests/test_source_execution_parallel_groups.py -q` completo (todos os REQs) passando.
**Condição de escalação**: nenhuma prevista.

## Gate de fechamento de requisitos

Todas as perguntas abertas relevantes foram resolvidas via `AskUserQuestion` (DEC-01, DEC-02, DEC-03) antes desta spec. As únicas zonas cinzentas remanescentes (nomes exatos dos settings, uso de `_value` interno do `Semaphore` em teste) estão registradas como PREM-03 e na condição de escalação da Etapa 2, não omitidas.
