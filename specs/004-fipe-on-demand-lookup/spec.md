# Spec: Busca FIPE sob demanda ao cadastrar wishlist  [spec-kit: T3]

`[spec-kit: T3 — 9pts: arquivos=2 (5+: novo model, nova migration, novo service, novo job, scheduler/run.py, wishlists_service.py), decisões=2 (como resolver "o veículo" de uma wishlist em texto livre, como refrescar 1 vínculo específico sem crawl completo), risco=2 (nova tabela/migration em produção, novo executor no scheduler), novidade=1 (variação do padrão fila+poller já usado no repo para scraping), verif=1 (testável com os padrões de mock já estabelecidos)]`

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Verificação final: spec-verifier independente, fix loop máx. 3 iterações
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 20 iterações totais
- Parada: veredito APROVADO do verifier | orçamento estourado → humano
- Registro: specs/004-fipe-on-demand-lookup/RUN.md (append-only)

## Contexto (investigação feita nesta sessão, e decisões já tomadas com o usuário)

`Wishlist` (`app/models/wishlist.py`) **não tem campos estruturados de marca/modelo** — só `query` (texto livre, já sem as diretivas de ano/preço extraídas por regex em `add_wishlist`) e uma relação `filters` (`WishlistFilter`, campos genéricos `field/operator/value`, ex: `{"field":"year","operator":"gte","value":"2018"}`). Não existe hoje nenhuma função que receba `(marca, modelo, ano)` soltos e devolva um preço FIPE.

O que já existe e será reaproveitado (decisão do usuário: "reusar o resolver fuzzy existente"):
- `app/services/fipe_catalog_resolver_service.py::resolve_listing_to_fipe_candidates(db, *, listing, reference_month, limit=10) -> dict` — recebe um objeto com atributos `make`, `model`, `year` (obrigatórios — se qualquer um faltar, retorna `{"status": "insufficient_data", ...}` sem tentar), `version`/`fuel_type` (opcionais), faz matching tokenizado com confidence score contra `FipeCatalogEntry`, devolve `best_candidate` (uma `FipeCatalogEntry` ou `None`) + `status` + confiança.
- `app/services/fipe_monthly_sync_service.py::upsert_fipe_catalog_entries` — já sabe gravar/atualizar `FipeCatalogEntry` de forma idempotente por `(reference_month, vehicle_type, source, identity_key)`.
- `app/services/fipe_api_client.py::FipeApiClient` — já sabe chamar a API FIPE com throttle/retry/backoff.
- Todos os 4 pontos de criação de wishlist (`add_wishlist`, `create_wishlist_with_filters`, `add_wishlist_with_initial_summary`, `create_wishlist_with_filters_and_initial_summary`, todos em `app/services/wishlists_service.py`) convergem para o mesmo padrão de "fire-and-forget pós-criação": cada um chama `trigger_initial_run_for_wishlist(db, wishlist, ...)` exatamente uma vez, nas linhas 710, 1168, 1197 e 1248. Esses são os 4 pontos onde a wishlist e seus filtros já estão persistidos e comitados.

Mecanismo de disparo assíncrono escolhido: **não** é o `enqueue_job`/`ScrapeJob` (esse é o job-queue de scraping, com schema específico de scraping — reaproveitá-lo para FIPE poluiria um domínio não relacionado) nem `asyncio.create_task` (o processo do bot e o processo do scheduler/APScheduler são processos **separados** em produção — `app/main.py` só inicia `start_scheduler()` dentro do processo da API/FastAPI; o bot roda como outro processo, sem acesso ao objeto `BackgroundScheduler` em memória). A opção compatível com múltiplos processos é o mesmo padrão de **fila persistida em Postgres + poller do APScheduler** já usado para `FipeUpdateRun`/`ScrapeJob`: uma tabela nova pequena, e um job periódico curto (poll a cada N segundos) que processa a fila. Isso é literalmente "o mesmo mecanismo de fila/scheduler já usado no projeto", só que como tabela dedicada ao domínio FIPE (mesmo padrão de `FipeSyncRun`/`FipeUpdateRun`, tabelas de tracking próprias por domínio, em vez de reaproveitar `ScrapeJob`).

## Objetivo

1. Ao criar uma wishlist, enfileirar (insert em tabela nova, sem chamada de rede) um pedido de lookup FIPE — a resposta ao usuário nunca espera por rede.
2. Um job periódico novo (executor dedicado, não o mesmo usado pelo crawl mensal — para não ficar bloqueado pelas horas que o crawl mensal ocupa) processa a fila: para cada pedido, tenta resolver o veículo da wishlist contra o catálogo já existente; se achar um candidato com confiança suficiente E atualizado há menos de `fipe_lookup_freshness_days` (30), reusa sem chamar a API; senão, faz uma chamada **direcionada** (poucas requisições, não um crawl completo) à API FIPE só para aquele veículo, e grava o resultado em `FipeCatalogEntry`.
3. Falha (rede, veículo não encontrado na API, dados insuficientes na wishlist para resolver) nunca derruba o fluxo — é logada, o pedido é marcado e, após `fipe_lookup_max_attempts` tentativas, fica definitivamente sem resolução automática; o veículo permanece elegível para ser coberto pelo próximo sync mensal completo (spec 003), que não depende desta fila.
4. Sync mensal completo continua cobrindo todo o catálogo (decisão já tomada com o usuário: manter full crawl, não reduzir escopo) — esta spec não altera `fipe_catalog_crawler.py`/`fipe_update_job.py`.

## Não-objetivos

- Não adicionar campos estruturados de marca/modelo à `Wishlist` (decisão já tomada: reusar o resolver fuzzy sobre o texto livre existente, não mudar o schema/fluxo de cadastro).
- Não reduzir o escopo do sync mensal (spec 003 mantém full crawl).
- Não usar `ScrapeJob`/`enqueue_job` (schema de domínio errado) nem `asyncio.create_task` (processos separados bot/scheduler em produção).
- Não implementar retry com backoff exponencial sofisticado para os pedidos da fila — `fipe_lookup_max_attempts` simples (contagem) é suficiente, dado que o sync mensal já é a rede de segurança final.
- Não bloquear ou atrasar `add_wishlist` por causa de falha ao enfileirar — o insert do pedido de lookup é best-effort (try/except), igual ao padrão já usado pelo próprio `add_wishlist` para `rebuild_tokens_for_wishlist` (linhas 697-701, já engole exceção com `db.rollback()`).

## Premissas assumidas (gate de fechamento)

- PREM-01: `make` = primeiro token de `wishlist.query` (após diretivas de ano/preço já removidas por `add_wishlist`), `model` = tokens restantes; se `query` tiver só 1 token, `make = model = query` inteiro (dá uma chance ao matching mesmo sem separação real de marca, aceitando confiança tipicamente mais baixa que será filtrada pelo `min_confidence`). É uma heurística best-effort — o padrão de digitação mais comum é "marca modelo" (ex: "audi a6", "honda civic touring"), mas não é garantido. Quando a heurística erra, o resultado é apenas confiança baixa → `status` diferente de `ok`/match → pedido marcado `skipped`, não um erro.
- PREM-02: `year` do pseudo-listing vem de `WishlistFilter` (`field="year"`): usa o valor `gte` se existir, senão `lte`, senão `None`. Se `None`, o resolver retorna `insufficient_data` (ele exige `year`) e o pedido é marcado `skipped` — ou seja, wishlists sem nenhuma diretiva de ano no texto original (ex: só "civic") não conseguem lookup sob demanda; ficam para o sync mensal. Aceito porque é uma limitação inerente ao resolver já existente (reaproveitado como aprovado), não uma nova limitação desta spec.
- PREM-03: `brand_code`/`model_code` de uma `FipeCatalogEntry` de um mês anterior continuam válidos para consultar `ConsultarAnoModelo`/`ConsultarValorComTodosParametros` na tabela de referência MAIS RECENTE (a FIPE não costuma renumerar marcas/modelos entre meses consecutivos — não há documentação oficial que garanta isso). Se a suposição falhar (API retornar erro/lista vazia para esses códigos sob a nova tabela), o pedido é tratado como falha comum (log + attempts++, sem crash) — risco aceito, mitigado por fallback ao sync mensal.
- PREM-04: `fipe_lookup_min_confidence` usa o mesmo valor (80) já usado como default em `run_monthly_fipe_sync`/`apply_fipe_price_plan` (`app/services/fipe_monthly_pipeline_service.py:100`), por consistência — não há indicação de que o contexto de wishlist precise de um limiar diferente.
- PREM-05: Só 1 instância do scheduler roda em produção hoje (confirmado pela spec 001/002, `max_instances=1` já é o padrão adotado) — o "claim" de pedidos pendentes na fila não precisa de `SELECT ... FOR UPDATE SKIP LOCKED`; um `UPDATE ... WHERE status='pending'` simples é suficiente porque não há concorrência real entre processos.

## Decisões tomadas

- Nova tabela `fipe_lookup_requests` (modelo `app/models/fipe_lookup_request.py`, mesmo estilo de `FipeUpdateRun`): `id` (UUID), `wishlist_id` (FK `wishlists.id`, `ondelete="CASCADE"`), `status` (`pending`/`done`/`skipped`/`failed`), `attempts` (int, default 0), `last_error` (text, nullable), `created_at`/`updated_at` (TimestampMixin), `processed_at` (nullable). Índice em `(status, created_at)` para o poller.
- Novo executor dedicado `"fipe_lookup"` (`ThreadPoolExecutor(2)`) em `app/scheduler/run.py`, **separado** do executor `"fipe"` já usado pelo crawl mensal (spec 001/003) — o crawl mensal pode ocupar o executor `"fipe"` por horas 1x/mês; o poller de lookup sob demanda não pode ficar bloqueado nesse período, senão cadastros de wishlist durante a janela mensal nunca recebem preço FIPE fresco.
- Job `job_process_fipe_lookups()` (`app/scheduler/fipe_lookup_job.py`), registrado com `trigger="interval"`, `seconds=settings.fipe_lookup_poll_interval_s` (default 60), `executor="fipe_lookup"`, `id="fipe_lookup_poll"`, `max_instances=1`.
- `enqueue_fipe_lookup_for_wishlist(db, wishlist)` (`app/services/fipe_on_demand_lookup_service.py`, novo módulo): insere 1 `FipeLookupRequest` `status="pending"` — mas só se `settings.fipe_lookup_enabled` for `True` (kill switch, mesmo padrão de `fipe_monthly_update_enabled`) e se não existir já um pedido `pending` para o mesmo `wishlist_id` (evita acúmulo se o usuário reeditar filtros repetidamente antes do poller processar). Chamado (envolto em `try/except` que só loga e faz `db.rollback()` em caso de erro, nunca propaga) nos 4 pontos de criação: `wishlists_service.py:710, 1168, 1197, 1248`, logo ao lado de cada chamada existente a `trigger_initial_run_for_wishlist`.
- `process_pending_fipe_lookups(db, *, limit=None) -> dict`: claim simples (`UPDATE fipe_lookup_requests SET status='processing' WHERE status='pending' ORDER BY created_at LIMIT :limit` via SQLAlchemy — ou, mais simples e portável entre Postgres/SQLite dado que os testes rodam em SQLite: `SELECT` com `limit`, e marcar `processing` linha a linha antes de processar, aceitável dado PREM-05 — nenhuma concorrência real). Cada pedido é processado em isolamento (try/except por pedido, uma falha não aborta o lote — mesmo padrão de isolamento por regra já usado na spec 002).
- Resolução de "fresco o suficiente": usa `resolve_listing_to_fipe_candidates(db, listing=pseudo_listing, reference_month=None, limit=5)` (o `reference_month=None` deve ser propagado até `_ensure_month`, que resolve para o mês mais recente com dados no catálogo — reaproveita a função privada `_ensure_month` já existente, importada diretamente do módulo). Se `best_candidate` existe com confiança `>= fipe_lookup_min_confidence` E `best_candidate.updated_at >= now - fipe_lookup_freshness_days dias` → pedido marcado `done`, nenhuma chamada à API, nenhum novo registro gravado (reusa o existente).
- Refresh direcionado (quando há candidato mas está velho, ou quando `best_candidate` existe mas de um mês anterior ao mais recente): usa os `brand_code`/`model_code` do `best_candidate` contra a tabela de referência FIPE mais recente (`client.get_latest_reference_table()` → `client.get_model_years(ref_code, best_candidate.brand_code, best_candidate.model_code)`, localizando o item cujo `Value.split("-", 1)` bate com `(best_candidate.model_year, best_candidate.fuel)` — se não achar exato, tenta achar só pelo ano, usando o primeiro combustível disponível daquele ano como fallback documentado) → `client.get_price(...)` → grava via `upsert_fipe_catalog_entries(db, [row], reference_month=<mês atual>, source="on_demand")` reaproveitando a função já testada da spec 001, sem duplicar lógica de parsing/validação.
- Se `best_candidate` for `None` (sem match nenhum, `status` != algo utilizável) → pedido marcado `skipped` (nada a fazer, dado insuficiente — não é erro, não conta como tentativa falha).
- Se a chamada à API FIPE (`get_latest_reference_table`/`get_model_years`/`get_price`) levantar `FipeApiError` ou qualquer exceção → `attempts += 1`, `last_error` gravado, `status` volta a `pending` se `attempts < fipe_lookup_max_attempts` (retry na próxima janela do poller) ou vira `failed` se esgotou as tentativas — nunca propaga para fora de `_process_one_fipe_lookup`.

## Contratos e schemas

### `app/models/fipe_lookup_request.py` (novo)

```python
class FipeLookupRequest(TimestampMixin, Base):
    __tablename__ = "fipe_lookup_requests"

    id: Mapped[uuid.UUID]  # PK, default uuid4
    wishlist_id: Mapped[uuid.UUID]  # FK wishlists.id, ondelete="CASCADE", nullable=False
    status: Mapped[str]  # default "pending"; CHECK IN ('pending','processing','done','skipped','failed')
    attempts: Mapped[int]  # default 0
    last_error: Mapped[str | None]
    processed_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("status IN ('pending','processing','done','skipped','failed')", name="ck_fipe_lookup_requests_status"),
        Index("ix_fipe_lookup_requests_status_created", "status", "created_at"),
    )
```

### `app/services/fipe_on_demand_lookup_service.py` (novo módulo)

```python
def enqueue_fipe_lookup_for_wishlist(db: Session, wishlist: Wishlist) -> FipeLookupRequest | None:
    """Retorna o pedido criado, ou None se: kill switch desligado, ou já existe um
    pedido pending para essa wishlist. Nunca levanta exceção (try/except interno,
    loga erro e faz db.rollback() em falha, retorna None)."""

def process_pending_fipe_lookups(db: Session, *, limit: int | None = None) -> dict:
    """limit default settings.fipe_lookup_batch_size (20). Retorna
    {"claimed": int, "done": int, "skipped": int, "refreshed": int, "failed_temp": int, "failed_final": int}.
    Processa cada pedido isoladamente (try/except por pedido)."""

def _build_pseudo_listing(wishlist: Wishlist, filters: list[WishlistFilter]):
    """Retorna um objeto simples (SimpleNamespace) com atributos make, model, year,
    version=None, fuel_type=None, id=wishlist.id, conforme PREM-01/PREM-02."""
```

### `app/scheduler/fipe_lookup_job.py` (novo)

```python
def job_process_fipe_lookups() -> None:
    """Abre SessionLocal(), chama process_pending_fipe_lookups, loga resultado via
    system_logs_service.log (component='fipe_lookup'), comita, captura exceção e
    loga erro sem propagar — mesmo padrão de app/scheduler/operational_data_cleanup_job.py."""
```

### `app/core/settings.py` (novos campos, junto ao bloco `fipe_*` existente)

```python
fipe_lookup_enabled: bool = True
fipe_lookup_freshness_days: int = 30
fipe_lookup_min_confidence: int = 80
fipe_lookup_poll_interval_s: int = 60
fipe_lookup_batch_size: int = 20
fipe_lookup_max_attempts: int = 3
```

### `migrations/versions/<nova>_fipe_lookup_requests.py` (nova)

`down_revision = "b2c4d6e8f0a1"` (head mais recente tocado por trabalho FIPE, spec 002). Cria a tabela `fipe_lookup_requests` conforme o modelo acima, com `CREATE TABLE` padrão (não é índice condicional a Postgres como as migrations de índice — tabela nova é portável Postgres/SQLite via Alembic normal).

## Plano de testes

1. `tests/test_fipe_lookup_request_model.py::test_status_check_constraint` — insert com `status` inválido levanta erro (Postgres) ou é aceito sem constraint em SQLite — seguir o padrão já usado em `tests/test_fipe_update_job_service.py` para constraints similares (se SQLite não reforça CHECK, o teste foca no default/campos, não na constraint em si).
2. `tests/test_fipe_on_demand_lookup_service.py::test_enqueue_inserts_pending_request` — cria wishlist fake, chama `enqueue_fipe_lookup_for_wishlist`, assert 1 `FipeLookupRequest` `status="pending"` criado.
3. `tests/test_fipe_on_demand_lookup_service.py::test_enqueue_skips_when_disabled` — `monkeypatch.setattr(settings, "fipe_lookup_enabled", False)`; assert nenhum pedido criado, retorno `None`.
4. `tests/test_fipe_on_demand_lookup_service.py::test_enqueue_dedupes_existing_pending` — 2 chamadas seguidas para a mesma wishlist; assert só 1 `FipeLookupRequest` existe no total.
5. `tests/test_fipe_on_demand_lookup_service.py::test_enqueue_never_raises_on_db_error` — `db.add`/`db.commit` mockado para levantar exceção; assert que a função retorna `None` sem propagar.
6. `tests/test_fipe_on_demand_lookup_service.py::test_pseudo_listing_single_token_query` (PREM-01) — wishlist com `query="civic"`; assert `_build_pseudo_listing(...).make == "civic"` e `.model == "civic"`.
7. `tests/test_fipe_on_demand_lookup_service.py::test_pseudo_listing_multi_token_query` (PREM-01) — `query="honda civic touring"`; assert `.make == "honda"`, `.model == "civic touring"`.
8. `tests/test_fipe_on_demand_lookup_service.py::test_pseudo_listing_year_prefers_gte` (PREM-02) — filtros `year gte=2018` e `year lte=2020`; assert `.year == 2018`.
9. `tests/test_fipe_on_demand_lookup_service.py::test_pseudo_listing_no_year_filter_is_none` (PREM-02) — sem filtro de ano; assert `.year is None`.
10. `tests/test_fipe_on_demand_lookup_service.py::test_process_reuses_fresh_candidate_without_api_call` (REQ central) — `FipeCatalogEntry` existente com `updated_at` de hoje e confiança alta simulada (via `monkeypatch` em `resolve_listing_to_fipe_candidates` retornando `{"status": "matched", "best_candidate": entry, "confidence": 90}`); `FipeApiClient` mockado para levantar exceção se qualquer método for chamado (prova que NÃO houve chamada de rede); assert pedido marcado `done`.
11. `tests/test_fipe_on_demand_lookup_service.py::test_process_refreshes_stale_candidate_via_targeted_api_call` (REQ central) — candidato com `updated_at` de 60 dias atrás; `FipeApiClient` mockado (`get_latest_reference_table`, `get_model_years`, `get_price` com dados fixos); assert que exatamente essas 3 chamadas foram feitas (não um crawl completo — `get_brands`/`get_models` NUNCA chamados) e que uma nova `FipeCatalogEntry` (`source="on_demand"`) foi gravada com o preço retornado.
12. `tests/test_fipe_on_demand_lookup_service.py::test_process_marks_skipped_when_no_candidate` — resolver mockado retornando `{"status": "no_match", "best_candidate": None}`; assert pedido `skipped`, nenhuma chamada à API.
13. `tests/test_fipe_on_demand_lookup_service.py::test_process_marks_skipped_when_insufficient_data` — pseudo-listing sem `year` (query sem diretiva de ano); assert pedido `skipped` sem levantar exceção.
14. `tests/test_fipe_on_demand_lookup_service.py::test_process_retries_then_fails_after_max_attempts` — `FipeApiClient` mockado sempre levanta `FipeApiError`; roda `process_pending_fipe_lookups` `fipe_lookup_max_attempts` vezes (simulando execuções sucessivas do poller); assert que nas primeiras `N-1` execuções o pedido volta a `pending` com `attempts` incrementando, e na última vira `failed`.
15. `tests/test_fipe_on_demand_lookup_service.py::test_process_isolates_failure_per_request` (não-raso, padrão da spec 002) — 2 pedidos no lote, o 1º levanta exceção não tratada dentro do processamento (simulando um bug inesperado), o 2º é válido e deve completar; assert que o 2º foi processado corretamente mesmo com o 1º falhando.
16. `tests/test_fipe_lookup_job.py::test_job_calls_service_and_logs` — mesmo padrão de `tests/test_operational_data_cleanup_job.py`; `process_pending_fipe_lookups` mockado; assert que o job chama a função, loga via `system_logs_service.log` com `component="fipe_lookup"`, comita.
17. `tests/test_scheduler_fipe_lookup_registration.py::test_fipe_lookup_job_registered_on_dedicated_executor` — mesmo padrão de `tests/test_scheduler_fipe_registration.py`; assert que `job_process_fipe_lookups` é registrado com `id="fipe_lookup_poll"`, `executor="fipe_lookup"`, `interval seconds=settings.fipe_lookup_poll_interval_s`; assert que `sched.executors` contém a chave `"fipe_lookup"` **distinta** de `"fipe"`.
18. `tests/test_wishlists_service.py::test_add_wishlist_enqueues_fipe_lookup` (regressão/integração, nome de arquivo existente a confirmar antes de codar) — `enqueue_fipe_lookup_for_wishlist` espiado; chama `add_wishlist(...)`; assert que foi chamado exatamente 1 vez com a wishlist criada. Repetir variante equivalente para os outros 3 entry points (`create_wishlist_with_filters`, `add_wishlist_with_initial_summary`, `create_wishlist_with_filters_and_initial_summary`) — 4 sub-testes ou 1 parametrizado.

Total: **18 testes** (17 novos + 1 conjunto de regressão parametrizado nos 4 entry points de wishlist).

## Grafo de dependências

Onda 1 (paralelas, sem dependência mútua):
- Etapa 1: Novas settings
- Etapa 2 [sensível]: Modelo `FipeLookupRequest` + migration

Onda 2 (depende da Etapa 2):
- Etapa 3: `fipe_on_demand_lookup_service.py` (enqueue + build_pseudo_listing)

Onda 3 (depende da Etapa 3):
- Etapa 4: `fipe_on_demand_lookup_service.py` (process_pending_fipe_lookups + refresh direcionado)

Onda 4 (depende da Etapa 4):
- Etapa 5: `fipe_lookup_job.py`

Onda 5 (depende da Etapa 5)  [sensível]:
- Etapa 6: Registro no `app/scheduler/run.py` (novo executor `"fipe_lookup"` + `add_job`)

Onda 6 (depende da Etapa 3, independente das Etapas 4-6):
- Etapa 7: Integração em `wishlists_service.py` (4 call sites)

Onda 7 (depende de todas):
- Etapa 8: Regressão completa

## Etapas

### Etapa 1: Novas settings FIPE lookup  (contrato de settings acima)
- FAZ: Adicionar em `app/core/settings.py`, junto ao bloco `fipe_*` existente, os 6 campos do contrato. Adicionar as mesmas variáveis (comentadas com default) em `.env.example`.
- TOCA: `app/core/settings.py`, `.env.example`
- VALIDA COM: `python -c "from app.core.settings import settings; assert settings.fipe_lookup_enabled is True; assert settings.fipe_lookup_freshness_days == 30; assert settings.fipe_lookup_min_confidence == 80; assert settings.fipe_lookup_poll_interval_s == 60; assert settings.fipe_lookup_batch_size == 20; assert settings.fipe_lookup_max_attempts == 3; print('OK')"` deve imprimir `OK`
- ESCALA SE: nenhuma condição especial prevista

### Etapa 2: Modelo `FipeLookupRequest` + migration  [sensível]
- FAZ: Criar `app/models/fipe_lookup_request.py` exatamente conforme o contrato (mesmo estilo de `app/models/fipe_update_run.py`). Registrar o import no ponto onde os demais models `fipe_*` são importados para o Alembic enxergar (verificar `migrations/env.py` ou `app/models/__init__.py` — seguir o padrão já usado por `FipeUpdateRun`). Gerar migration nova em `migrations/versions/` com `down_revision = "b2c4d6e8f0a1"`, criando a tabela via `op.create_table(...)` (não é migration condicional a dialeto — tabela nova via Alembic padrão, testável em SQLite e Postgres).
- TOCA: `app/models/fipe_lookup_request.py` (novo), `migrations/versions/<nova>.py` (novo), ponto de registro de models (o mesmo arquivo que já registra `FipeUpdateRun`)
- VALIDA COM: `pytest tests/test_fipe_lookup_request_model.py -q` (teste 1); `python -c "from app.models.fipe_lookup_request import FipeLookupRequest; print('import OK')"`; confirmar via `alembic heads` (ou equivalente `py -m alembic heads`) que a nova migration aparece como head alcançável a partir de `b2c4d6e8f0a1`
- ESCALA SE: `migrations/env.py`/registro de models não seguir o padrão usado por `FipeUpdateRun` de forma óbvia (decisão residual sobre onde registrar)

### Etapa 3: Enqueue + pseudo-listing  (contrato acima; testes 2-9)
- FAZ: Criar `app/services/fipe_on_demand_lookup_service.py` com `enqueue_fipe_lookup_for_wishlist` e `_build_pseudo_listing` exatamente conforme PREM-01/PREM-02 e o contrato. `enqueue_fipe_lookup_for_wishlist` checa `settings.fipe_lookup_enabled`, checa pedido `pending` existente para o `wishlist_id` (`db.query(FipeLookupRequest).filter(wishlist_id=..., status="pending").first()`), envolve o insert em `try/except Exception` (loga via `print`/logger padrão do módulo, faz `db.rollback()`, retorna `None`).
- TOCA: `app/services/fipe_on_demand_lookup_service.py` (novo)
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k "enqueue or pseudo_listing"` (testes 2-9) — 8 testes verdes
- ESCALA SE: `WishlistFilter` não tiver os campos `field`/`operator`/`value` como string conforme já lido nesta sessão (realidade ≠ spec)

### Etapa 4: Processamento da fila + refresh direcionado  [sensível]  (contrato acima; testes 10-15)
- FAZ: Adicionar `process_pending_fipe_lookups` e a lógica interna de processamento por pedido ao mesmo módulo da Etapa 3, conforme a seção "Decisões tomadas" (resolução via `resolve_listing_to_fipe_candidates` com `reference_month=None` → `_ensure_month`; checagem de frescor via `updated_at`; refresh direcionado via `get_latest_reference_table`/`get_model_years`/`get_price`; upsert via `upsert_fipe_catalog_entries` reaproveitado; tratamento de erro com `attempts`/`last_error`/transições de `status` conforme especificado). Cada pedido processado dentro de seu próprio `try/except`, sem abortar o lote em caso de exceção inesperada (Etapa isolada de falha, teste 15).
- TOCA: `app/services/fipe_on_demand_lookup_service.py`
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -q -k "process"` (testes 10-15) — 6 testes verdes
- ESCALA SE: `resolve_listing_to_fipe_candidates` não aceitar `reference_month=None` de forma que resolva para o mês mais recente (realidade ≠ spec — verificar `_ensure_month` antes de codar; se o comportamento real for diferente do assumido, é decisão residual sobre como obter "o mês mais recente")

### Etapa 5: Job do scheduler  (contrato acima; teste 16)
- FAZ: Criar `app/scheduler/fipe_lookup_job.py` com `job_process_fipe_lookups()`, seguindo exatamente o padrão de `app/scheduler/operational_data_cleanup_job.py` (abrir `SessionLocal()`, chamar o serviço, logar via `system_logs_service.log(component="fipe_lookup", ...)`, comitar, capturar exceção e logar erro sem propagar).
- TOCA: `app/scheduler/fipe_lookup_job.py` (novo)
- VALIDA COM: `pytest tests/test_fipe_lookup_job.py -q` (teste 16)
- ESCALA SE: `app/scheduler/operational_data_cleanup_job.py` não existir mais ou tiver mudado de padrão desde a spec 002 (realidade ≠ spec)

### Etapa 6: Registro no scheduler  [sensível]  (teste 17)
- FAZ: Em `app/scheduler/run.py`: adicionar `"fipe_lookup": ThreadPoolExecutor(2)` ao dict `executors={...}` existente (ao lado de `"fipe"`, sem alterá-lo). Registrar `sched.add_job(job_process_fipe_lookups, "interval", seconds=settings.fipe_lookup_poll_interval_s, id="fipe_lookup_poll", executor="fipe_lookup", replace_existing=True, max_instances=1)`.
- TOCA: `app/scheduler/run.py`
- VALIDA COM: `pytest tests/test_scheduler_fipe_lookup_registration.py -q` (teste 17); `pytest tests/test_scheduler_fipe_registration.py -q` (regressão — executor `"fipe"` não deve ser afetado)
- ESCALA SE: `executors={...}` já tiver uma chave `"fipe_lookup"` com outro propósito (realidade ≠ spec)

### Etapa 7: Integração na criação de wishlist  (teste 18)
- FAZ: Em `app/services/wishlists_service.py`, adicionar `enqueue_fipe_lookup_for_wishlist(db, w)` (ou o nome da variável local da wishlist em cada função) imediatamente ao lado de cada uma das 4 chamadas existentes a `trigger_initial_run_for_wishlist` (linhas 710, 1168, 1197, 1248 — confirmar números de linha exatos no momento da implementação, podem ter deslocado). A chamada nunca deve impedir o retorno normal da função (a própria `enqueue_fipe_lookup_for_wishlist` já não propaga exceções, conforme Etapa 3 — não é necessário `try/except` adicional no call site, mas adicionar um comentário curto não é necessário; só a chamada direta).
- TOCA: `app/services/wishlists_service.py`
- VALIDA COM: `pytest tests/test_wishlists_service.py -q -k fipe_lookup` (teste 18, 4 sub-casos) — todos verdes; suíte completa de wishlist (`pytest tests/test_wishlist*.py tests/test_guided_wishlist_creation.py -q`) sem regressão
- ESCALA SE: algum dos 4 call sites já tiver sido refatorado de forma que não exista mais uma chamada única e clara a `trigger_initial_run_for_wishlist` naquele ponto (realidade ≠ spec)

### Etapa 8: Regressão completa
- FAZ: Rodar a suíte completa relacionada e corrigir quebras pontuais não previstas.
- TOCA: qualquer arquivo de teste tocado pelas etapas anteriores que precise de ajuste pontual
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py tests/test_fipe_lookup_job.py tests/test_scheduler_fipe_lookup_registration.py tests/test_fipe_lookup_request_model.py tests/test_wishlists_service.py -q` — 100% verde
- ESCALA SE: uma quebra exigir revisitar uma decisão já tomada em etapa anterior

## Riscos conhecidos e mitigação

| Risco | Etapa | Mitigação já embutida na spec |
|---|---|---|
| Heurística marca/modelo (PREM-01) erra na maioria das queries reais, deixando a maior parte dos pedidos `skipped` | 3, 4 | Aceito como risco residual — o mecanismo é best-effort por decisão explícita do usuário; o sync mensal (spec 003) continua sendo a cobertura completa e confiável |
| `brand_code`/`model_code` não são estáveis entre tabelas de referência (PREM-03) | 4 | Erro tratado como falha comum (log + retry + eventual `failed`), nunca crash; se acontecer sistematicamente, é sinal para revisitar a spec, não um bug silencioso |
| Poller compete por conexão de DB com o crawl mensal durante a janela de 1x/mês | 5, 6 | Executor dedicado `"fipe_lookup"` separado do `"fipe"` (spec 001/003) — não fica bloqueado esperando o crawl mensal liberar o worker |
| Fila cresce sem limite se `process_pending_fipe_lookups` falhar silenciosamente por um período | 4 | `fipe_lookup_batch_size` limita processamento por tick, mas a fila em si não tem TTL — aceito porque `fipe_lookup_max_attempts` garante que pedidos com erro persistente não ficam re-tentando para sempre (viram `failed`, saem da fila `pending`) |
| Nova migration em produção falha por causa dos múltiplos heads pré-existentes (documentado nas specs 001/002) | 2 | `down_revision` explicitamente ancorado no head mais recente do domínio FIPE (`b2c4d6e8f0a1`), mesmo padrão já usado com sucesso pela spec 002 |

## Análise de consistência (preenchida antes de liberar)
- [x] Todo requisito do objetivo do usuário (não bloquear cadastro, checar frescor antes de chamar API, falhar sem quebrar fluxo, decisão sobre sync mensal) está coberto por REQ/decisão rastreável a uma etapa
- [x] Toda etapa consome apenas artefatos de etapas anteriores: Etapa 3 usa o modelo da Etapa 2; Etapa 4 estende o serviço da Etapa 3; Etapa 5 usa a função da Etapa 4; Etapa 6 usa o job da Etapa 5; Etapa 7 usa a função da Etapa 3 (não depende de 4-6, por isso está em onda paralela)
- [x] Nenhuma contradição entre contratos, PREMs e testes — cruzado `_build_pseudo_listing` contra PREM-01/02 e testes 6-9; `process_pending_fipe_lookups` contra os testes 10-15
- [x] Nenhuma frase delega julgamento sem critério mecânico — os dois pontos de heurística (split marca/modelo, escolha de gte sobre lte) são decisões explícitas já tomadas na spec (PREM-01/PREM-02), não deixadas para o executor decidir
