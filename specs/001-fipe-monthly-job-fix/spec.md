# Spec: Job mensal FIPE — jobstore persistente + crawler automático  [spec-kit: T3]

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Verificação final: spec-verifier independente, fix loop máx. 3 iterações
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 20 iterações totais
- Parada: veredito APROVADO do verifier | orçamento estourado → humano
- Registro: specs/001-fipe-monthly-job-fix/RUN.md (append-only)

## Objetivo
O job mensal de atualização de preços FIPE nunca populou a tabela `fipe_catalog_entries`/`fipe_prices` em produção. Investigação encontrou duas causas raiz independentes: (1) `fipe_monthly_update_enabled` é `False` por padrão e nunca foi ligado — o job, quando dispara, faz no-op silencioso ("kill switch disabled"); (2) o pipeline depende de um arquivo local em `fipe_monthly_update_input_path` que nunca foi gerado nem enviado ao Pi — não existe hoje nenhum cliente/crawler que consulte a FIPE automaticamente. Adicionalmente, o `BackgroundScheduler` usa `MemoryJobStore` (padrão, em memória) sem jobstore persistente — se o processo reiniciar durante a janela exata de disparo (dia 5, 05:00–06:00 UTC), a execução daquele mês é perdida silenciosamente (`misfire_grace_time=3600`).

Esta spec resolve as três coisas: adiciona um jobstore persistente (`SQLAlchemyJobStore` no mesmo Postgres/Supabase já usado pelo app), implementa um cliente Python que consulta a API pública (sem chave) do site oficial `veiculos.fipe.org.br/api/veiculos` — espelhando a abordagem do projeto de referência `github.com/caiopizzol/fipe-data-pipeline` — e integra esse crawler diretamente no job mensal, eliminando a dependência de um arquivo pré-existente.

## Requisitos
- REQ-001: QUANDO o processo do scheduler reinicia (systemd restart) O SISTEMA DEVE manter os jobs agendados persistidos em Postgres, sem precisar reagendar do zero — verificado por: `pytest tests/test_scheduler_jobstore_persistence.py`
- REQ-002: QUANDO `start_scheduler()` é chamado O SISTEMA DEVE construir o `BackgroundScheduler` com `jobstores={"default": SQLAlchemyJobStore(url=settings.database_url)}` — verificado por: `pytest tests/test_scheduler_jobstore_persistence.py::test_scheduler_uses_sqlalchemy_jobstore`
- REQ-003: QUANDO o `FipeApiClient` consulta `ConsultarTabelaDeReferencia` O SISTEMA DEVE retornar a tabela de referência mais recente (primeiro item da lista retornada pela API) — verificado por: `pytest tests/test_fipe_api_client.py::test_get_latest_reference_table`
- REQ-004: QUANDO qualquer chamada ao `FipeApiClient` recebe HTTP 429 O SISTEMA DEVE aplicar backoff exponencial (base 5000ms, dobrando a cada tentativa) e respeitar o header `Retry-After` quando presente, até `fipe_api_max_retries` tentativas — verificado por: `pytest tests/test_fipe_api_client.py::test_429_backoff`
- REQ-005: QUANDO qualquer chamada ao `FipeApiClient` recebe uma resposta de erro no formato `{"erro": "..."}` O SISTEMA DEVE levantar `FipeApiError` com a mensagem original — verificado por: `pytest tests/test_fipe_api_client.py::test_fipe_error_response_raises`
- REQ-006: QUANDO o crawler completa uma varredura de marcas/modelos/anos/preços O SISTEMA DEVE produzir uma lista de dicts no formato aceito por `normalize_external_fipe_rows` (chaves `tipo_veiculo`, `marca`, `modelo`, `ano`, `combustivel`, `codigo_fipe`, `valor`; `mes_referencia` é OMITIDO de propósito — o campo `MesReferencia` da API vem como `"agosto/2026"`, não `YYYY-MM`, e falharia a validação regex do adapter; o mês vem do `reference_month` passado por `run_monthly_fipe_sync`, não do crawler) — verificado por: `pytest tests/test_fipe_catalog_crawler.py::test_crawl_output_shape_matches_adapter`
- REQ-007: QUANDO `job_monthly_fipe_update` roda E `fipe_monthly_update_input_path` NÃO está configurado O SISTEMA DEVE executar o crawler (sem sessão de DB aberta), escrever o resultado em um arquivo JSON temporário, e só então abrir a sessão de DB para chamar `run_audited_monthly_fipe_update` com esse arquivo — verificado por: `pytest tests/test_fipe_update_job.py::test_job_crawls_when_no_static_input_path`
- REQ-008: QUANDO `job_monthly_fipe_update` roda E `fipe_monthly_update_input_path` ESTÁ configurado O SISTEMA DEVE pular o crawler e usar o arquivo estático diretamente (comportamento atual preservado, útil para testes/import manual) — verificado por: `pytest tests/test_fipe_update_job.py::test_job_uses_static_input_path_when_configured`
- REQ-009: QUANDO o arquivo JSON temporário gerado pelo crawler é consumido pelo pipeline de sync O SISTEMA DEVE apagá-lo ao final (sucesso ou falha), nunca deixando lixo em disco — verificado por: `pytest tests/test_fipe_update_job.py::test_temp_file_cleaned_up_on_success_and_failure`
- REQ-010: QUANDO `start_scheduler()` registra `monthly_fipe_update` O SISTEMA DEVE usar o executor dedicado `"fipe"` (pool de 1 worker), não o executor `"default"`, para não bloquear os demais jobs periódicos durante uma varredura longa — verificado por: `pytest tests/test_scheduler_fipe_registration.py::test_monthly_fipe_update_uses_dedicated_executor`
- REQ-011: QUANDO um operador roda `python scripts/run_fipe_monthly_job.py --force` O SISTEMA DEVE executar o job mensal completo (crawler + sync) imediatamente, ignorando o agendamento — verificado por: execução manual documentada em README da spec (não testável em CI sem rede; ver Plano de testes)
- REQ-012: QUANDO um operador roda `python scripts/run_fipe_monthly_job.py --force --limit-brands N` O SISTEMA DEVE limitar o crawler às primeiras N marcas retornadas pela API, para permitir smoke test rápido — verificado por: `pytest tests/test_fipe_catalog_crawler.py::test_limit_brands_bounds_crawl`

## Não-objetivos
- Não implementar backfill histórico de meses anteriores (o projeto de referência faz isso; aqui só a tabela de referência mais recente é consultada).
- Não migrar `source_backoff_service`/`source_rate_limit_service` para cobrir este crawler — o throttle é intra-execução (ms) e self-contained no `FipeApiClient`, diferente do backoff entre ciclos de polling que esses serviços resolvem.
- Não adicionar Alembic migration para a tabela `apscheduler_jobs` — `SQLAlchemyJobStore` cria a tabela automaticamente (`CREATE TABLE IF NOT EXISTS`) na primeira conexão.
- Não trocar `requests` por `httpx`/`aiohttp` — segue a convenção existente do repo.
- Não ligar `FIPE_MONTHLY_UPDATE_ENABLED=true` no `.env` real do Raspberry Pi — isso é uma ação operacional em produção, fora do escopo de código; a spec entrega a capacidade e documenta o passo, mas o usuário decide quando ligar.

## Premissas assumidas (gate de fechamento)
- PREM-01: O tipo de veículo é sempre "carro" (`codigoTipoVeiculo=1`), igual ao projeto de referência — não há indicação de que o produto precise de motos/caminhões.
- PREM-02: `SQLAlchemyJobStore` usa `settings.database_url` diretamente (mesma engine/URL do app, tabela default `apscheduler_jobs`) — não precisa de uma conexão/engine separada, já que o DB alvo é o mesmo Supabase Postgres.
- PREM-03: A API pública da FIPE (`veiculos.fipe.org.br/api/veiculos`) responde em JSON, POST, sem autenticação — confirmado pelo cliente do projeto de referência lido nesta sessão; se o contrato mudar no futuro isso é um problema operacional, não de código.
- PREM-04: O executor dedicado `"fipe"` roda com 1 worker (`ThreadPoolExecutor(1)`), suficiente já que `max_instances=1` no job garante que nunca há mais de uma varredura simultânea.
- PREM-05: Uma varredura completa (todas marcas/modelos/anos de carros) pode levar horas dado o throttle de ~800ms entre chamadas; isso é aceitável porque o job roda 1x/mês em background, sem bloquear os demais jobs (REQ-010) e sem segurar conexão de DB durante o crawl (REQ-007).

## Decisões tomadas
- Crawler mira exatamente o formato de linha que `fipe_external_pipeline_adapter.normalize_external_fipe_rows` já aceita (chaves em português, ex. `marca`, `modelo`, `valor`) em vez do formato já-normalizado de `FipeCatalogEntry` — reaproveita 100% do adapter já testado (parsing de preço "R$ 95.000,00", etc.), menos código novo.
- Arquivo de saída do crawler é um JSON temporário (`tempfile`), não um CSV — reaproveita `load_monthly_fipe_input` sem tocar nele, e JSON preserva tipos melhor que CSV para uma lista de dicts.
- `fipe_monthly_update_input_path`, se configurado, sempre tem prioridade sobre o crawler — preserva o caminho manual/import existente (usado por `scripts/import_fipe_prices.py` e testes) sem quebrar nada.
- Throttle do `FipeApiClient` é self-contained (estado em memória da instância: `_last_request_time`, `_current_throttle_ms`), não usa `source_backoff_service` — motivo no Não-objetivos.
- `FipeApiClient` usa `requests` (já é dependência do projeto) com `timeout=settings.fipe_api_timeout_s` em toda chamada — nunca uma chamada sem timeout.

## Contratos e schemas

### `app/services/fipe_api_client.py` (novo módulo)

```python
class FipeApiError(Exception):
    """Levantado quando a API FIPE retorna {"erro": "..."} ou HTTP não-2xx após esgotar retries."""

class FipeApiClient:
    BASE_URL = "https://veiculos.fipe.org.br/api/veiculos"
    VEHICLE_TYPE_CAR = 1

    def __init__(self, *, rate_limit_ms: int | None = None, max_throttle_ms: int | None = None,
                 max_retries: int | None = None, timeout_s: int | None = None) -> None:
        """Lê defaults de settings.fipe_api_rate_limit_ms / fipe_api_max_throttle_ms /
        fipe_api_max_retries / fipe_api_timeout_s quando o parâmetro correspondente é None."""

    def get_reference_tables(self) -> list[dict]:
        """POST ConsultarTabelaDeReferencia {} -> list[{"Codigo": int, "Mes": str}]."""

    def get_latest_reference_table(self) -> dict:
        """Retorna get_reference_tables()[0] (API retorna ordenado do mais recente pro mais antigo).
        Levanta FipeApiError se a lista vier vazia."""

    def get_brands(self, reference_code: int) -> list[dict]:
        """POST ConsultarMarcas {codigoTabelaReferencia, codigoTipoVeiculo=1} -> list[{"Label": str, "Value": str}]."""

    def get_models(self, reference_code: int, brand_code: str) -> list[dict]:
        """POST ConsultarModelos {codigoTabelaReferencia, codigoTipoVeiculo=1, codigoMarca} ->
        dict com chave "Modelos": list[{"Label": str, "Value": str}] (extrai e retorna só essa lista)."""

    def get_model_years(self, reference_code: int, brand_code: str, model_code: str) -> list[dict]:
        """POST ConsultarAnoModelo {codigoTabelaReferencia, codigoTipoVeiculo=1, codigoMarca, codigoModelo} ->
        list[{"Label": str, "Value": str}] onde Value = "{ano}-{codigoCombustivel}", ex "2020-1"."""

    def get_price(self, *, reference_code: int, brand_code: str, model_code: str,
                   model_year: int, fuel_code: str) -> dict:
        """POST ConsultarValorComTodosParametros {codigoTabelaReferencia, codigoTipoVeiculo=1,
        codigoMarca, codigoModelo, anoModelo, codigoTipoCombustivel, tipoVeiculo=1,
        tipoConsulta="tradicional"} -> dict com chaves Valor, Marca, Modelo, AnoModelo,
        Combustivel, CodigoFipe, MesReferencia, TipoVeiculo, SiglaCombustivel."""

    def _request(self, endpoint: str, body: dict) -> dict | list:
        """Implementa throttle adaptativo + retry/backoff, igual ao cliente TS de referência:
        - Antes de cada request: aguarda até (rate_limit_ms atual) desde a última chamada.
        - Em 429: dobra o throttle atual (até max_throttle_ms), espera Retry-After (se
          presente) ou backoff exponencial base 5000ms, tenta de novo até max_retries.
        - Em erro de rede ou HTTP não-2xx não-429: backoff exponencial base 1000ms, retry
          até max_retries.
        - Em resposta JSON {"erro": str}: levanta FipeApiError(msg) imediatamente, sem retry.
        - Esgotados os retries: levanta FipeApiError com a última causa."""
```

### `app/services/fipe_catalog_crawler.py` (novo módulo)

```python
def crawl_latest_fipe_prices(client: FipeApiClient, *, limit_brands: int | None = None,
                              on_progress: Callable[[str], None] | None = None) -> list[dict]:
    """Varre tabela de referência mais recente -> todas as marcas (ou as primeiras
    limit_brands, se informado) -> todos os modelos de cada marca -> todos os
    ano/combustível de cada modelo -> preço de cada combinação.

    Retorna list[dict] no formato aceito por normalize_external_fipe_rows:
    {"mes_referencia": str, "tipo_veiculo": "car", "marca": str, "modelo": str,
     "ano": int, "combustivel": str, "codigo_fipe": str, "valor": str}

    on_progress, se informado, é chamado com uma string curta a cada marca concluída
    (ex: "Toyota: 42/42 modelos"), só para logging — não afeta o retorno.

    Erros de uma combinação individual (ex: FipeApiError num modelo específico) são
    logados via on_progress e a combinação é pulada — não aborta a varredura inteira.
    """
```

### `app/scheduler/fipe_update_job.py` (modificado)

```python
def job_monthly_fipe_update() -> None:
    """Se settings.fipe_monthly_update_input_path estiver configurado, comportamento
    atual preservado (abre sessão de DB, chama run_audited_monthly_fipe_update com esse
    path). Caso contrário: roda o crawler SEM sessão de DB aberta, escreve o resultado
    num arquivo JSON temporário (tempfile.NamedTemporaryFile(suffix=".json", delete=False)),
    só então abre a sessão de DB e chama run_audited_monthly_fipe_update com o path
    temporário, e remove o arquivo temporário no finally (sucesso ou exceção)."""
```

### `app/core/settings.py` (novos campos, junto aos `fipe_*` existentes)

```python
fipe_api_rate_limit_ms: int = 800
fipe_api_max_throttle_ms: int = 5000
fipe_api_max_retries: int = 5
fipe_api_timeout_s: int = 20
```

## Plano de testes

### Antes de escrever o plano de testes — amostragem feita
Convenções confirmadas (via exploração do repo nesta sessão): `pytest.ini` com `testpaths = tests`, `addopts = -q`; comando de execução `pytest tests/<arquivo>.py -q`; mocking de chamadas externas via `monkeypatch.setattr` direto na função/método do módulo (sem `responses`/`respx`); fixture `db` de `tests/conftest.py` reutilizada sem setup extra; testes de registro do scheduler usam uma classe `_FakeScheduler` local com `monkeypatch.setattr(run_mod, "BackgroundScheduler", _FakeScheduler)` e inspecionam `sched.jobs`/`sched.jobstores`/`sched.executors` conforme o que o fake captura.

### Testes (14 total, todos novos exceto onde indicado "existente")

1. `tests/test_scheduler_jobstore_persistence.py::test_scheduler_uses_sqlalchemy_jobstore` (REQ-001, REQ-002) — Fake `BackgroundScheduler.__init__` captura kwargs; chama `start_scheduler()` com `monkeypatch` no `SessionLocal`/bootstrap para não tocar DB real; asserta que `jobstores["default"]` é uma instância de `SQLAlchemyJobStore` (ou que foi chamada com `url=settings.database_url` — usar `monkeypatch.setattr` no próprio `SQLAlchemyJobStore` para capturar os kwargs de construção, já que não dá pra inspecionar estado interno facilmente). Não-raso: assert falha se `jobstores` kwarg estiver ausente ou for `{}`.
2. `tests/test_scheduler_jobstore_persistence.py::test_jobstore_url_matches_database_url` (REQ-002) — captura o kwarg `url` passado ao `SQLAlchemyJobStore` e compara com `settings.database_url` (via `monkeypatch.setattr(settings, "database_url", "postgresql://fake/db")` antes de chamar `start_scheduler()`).
3. `tests/test_fipe_api_client.py::test_get_latest_reference_table` (REQ-003) — `monkeypatch` em `FipeApiClient._request` retornando `[{"Codigo": 320, "Mes": "agosto/2026"}, {"Codigo": 319, "Mes": "julho/2026"}]`; asserta que `get_latest_reference_table()` retorna o primeiro item (`Codigo: 320`).
4. `tests/test_fipe_api_client.py::test_get_latest_reference_table_empty_raises` (REQ-003) — `_request` retorna `[]`; asserta `pytest.raises(FipeApiError)`.
5. `tests/test_fipe_api_client.py::test_429_backoff` (REQ-004) — `monkeypatch` em `requests.post` (via `session.post` ou `requests.post` conforme implementação) para retornar 429 na 1ª chamada (com header `Retry-After: 2`) e 200 na 2ª; `monkeypatch` em `time.sleep` para capturar o valor esperado sem esperar de verdade; asserta que `sleep` foi chamado com `~2.0` (do header) e que a 2ª tentativa retornou o corpo 200 com sucesso.
6. `tests/test_fipe_api_client.py::test_429_exhausts_retries_raises` (REQ-004) — todas as tentativas retornam 429; asserta `pytest.raises(FipeApiError)` após exatamente `max_retries` tentativas (assert no call count do mock).
7. `tests/test_fipe_api_client.py::test_fipe_error_response_raises` (REQ-005) — resposta 200 com corpo `{"erro": "Parametros invalidos"}`; asserta `pytest.raises(FipeApiError, match="Parametros invalidos")` e que NENHUM retry ocorreu (call count == 1).
8. `tests/test_fipe_api_client.py::test_timeout_passed_to_requests` (contrato de decisão, não-REQ numerado mas cobre "nunca uma chamada sem timeout") — captura kwargs de `requests.post`/`session.post`, asserta `timeout == settings.fipe_api_timeout_s`.
9. `tests/test_fipe_catalog_crawler.py::test_crawl_output_shape_matches_adapter` (REQ-006) — `client` fake (objeto simples ou `unittest.mock.Mock(spec=FipeApiClient)`) com `get_latest_reference_table`, `get_brands`, `get_models`, `get_model_years`, `get_price` retornando dados fixos de 1 marca/1 modelo/1 ano; chama `crawl_latest_fipe_prices(client)`; asserta que o resultado é `list[dict]` com exatamente as chaves `{"mes_referencia", "tipo_veiculo", "marca", "modelo", "ano", "combustivel", "codigo_fipe", "valor"}` e então passa o resultado por `normalize_external_fipe_rows` (import real, não mock) e asserta que não levanta exceção e retorna >=1 linha normalizada — este é o teste não-raso central: prova que o crawler produz dado que o adapter real aceita, não só que os campos existem.
10. `tests/test_fipe_catalog_crawler.py::test_limit_brands_bounds_crawl` (REQ-012) — client fake com `get_brands` retornando 5 marcas; chama `crawl_latest_fipe_prices(client, limit_brands=2)`; asserta que `client.get_models` foi chamado exatamente 2 vezes (uma por marca), não 5.
11. `tests/test_fipe_catalog_crawler.py::test_individual_combination_error_does_not_abort_crawl` (comportamento documentado no contrato) — client fake onde `get_price` levanta `FipeApiError` na 1ª combinação e retorna sucesso na 2ª; asserta que o crawl retorna 1 linha (a que teve sucesso), não levanta exceção, e que `on_progress` foi chamado com uma mensagem mencionando o erro.
12. `tests/test_fipe_update_job.py::test_job_crawls_when_no_static_input_path` (REQ-007) — `monkeypatch.setattr(settings, "fipe_monthly_update_input_path", None)`; `monkeypatch` em `crawl_latest_fipe_prices` para retornar rows fixas; `monkeypatch` em `run_audited_monthly_fipe_update` para capturar o `input_path` recebido; chama `job_monthly_fipe_update()`; asserta que `run_audited_monthly_fipe_update` foi chamado com um `Path` cujo conteúdo (lido do disco antes do cleanup, ou capturado via side_effect) é igual às rows fixas serializadas em JSON. Não-raso: valida o CONTEÚDO do arquivo, não só que foi chamado.
13. `tests/test_fipe_update_job.py::test_job_uses_static_input_path_when_configured` (REQ-008) — `monkeypatch.setattr(settings, "fipe_monthly_update_input_path", "/tmp/fixed.json")`; `monkeypatch` em `crawl_latest_fipe_prices` para levantar exceção se chamado (prova que não é chamado); `monkeypatch` em `run_audited_monthly_fipe_update` capturando `input_path`; asserta que foi chamado com `Path("/tmp/fixed.json")` exatamente.
14. `tests/test_fipe_update_job.py::test_temp_file_cleaned_up_on_success_and_failure` (REQ-009) — dois casos no mesmo teste (ou dois testes): (a) `run_audited_monthly_fipe_update` mockado retorna normalmente — asserta que o path temporário capturado não existe mais no disco após `job_monthly_fipe_update()` retornar; (b) mockado levanta exceção — asserta o mesmo (arquivo não existe), e que a exceção NÃO propaga para fora de `job_monthly_fipe_update()` (job não deve derrubar o scheduler).
15. `tests/test_scheduler_fipe_registration.py::test_monthly_fipe_update_uses_dedicated_executor` (REQ-010) — estende o `_FakeScheduler` já existente nesse arquivo para capturar o kwarg `executor` em `add_job`; chama `start_scheduler()` (com os mocks de bootstrap já usados nos outros testes desse arquivo); localiza o job `id="monthly_fipe_update"` em `sched.jobs`; asserta `executor == "fipe"`. Também asserta (extensão do teste existente) que `sched.executors` (capturado do construtor) contém uma chave `"fipe"`.

Total: **15 testes** (ajustado de 14 para 15 ao contar o teste #8, que valida timeout — mantendo a contagem explícita para o verifier).

## Grafo de dependências

Onda 1 (paralelas, sem dependência mútua):
- Etapa 1: Settings novas
- Etapa 2: Jobstore persistente + executor dedicado no scheduler

Onda 2 (depende da Etapa 1):
- Etapa 3: `FipeApiClient`

Onda 3 (depende da Etapa 3):
- Etapa 4: `fipe_catalog_crawler.py`

Onda 4 (depende das Etapas 2 e 4):
- Etapa 5: Integrar crawler em `job_monthly_fipe_update` + registrar no executor `"fipe"`

Onda 5 (depende da Etapa 5):
- Etapa 6: CLI manual `scripts/run_fipe_monthly_job.py`
- Etapa 7 [sensível]: Documentação de deploy (.env.example, README do Pi) — não bloqueia Etapa 6, mas depende de tudo existir para documentar precisamente

## Etapas

### Etapa 1: Novas settings FIPE  (REQ-003, REQ-004, contrato de fipe_api_client)
- FAZ: Adicionar em `app/core/settings.py`, logo após o bloco `fipe_monthly_update_*` existente (linhas 319-323), os campos:
  ```python
  fipe_api_rate_limit_ms: int = 800
  fipe_api_max_throttle_ms: int = 5000
  fipe_api_max_retries: int = 5
  fipe_api_timeout_s: int = 20
  ```
  Adicionar as mesmas 4 variáveis (com os mesmos defaults, comentadas) em `.env.example`, próximo às linhas `FIPE_*` existentes (se `.env.example` não tiver nenhuma `FIPE_*` hoje, adicionar uma seção nova `# FIPE monthly update`).
- TOCA: `app/core/settings.py`, `.env.example`
- VALIDA COM: `py -c "from app.core.settings import settings; assert settings.fipe_api_rate_limit_ms == 800; assert settings.fipe_api_max_throttle_ms == 5000; assert settings.fipe_api_max_retries == 5; assert settings.fipe_api_timeout_s == 20; print('OK')"` deve imprimir `OK`
- ESCALA SE: `app/core/settings.py` não tiver uma classe `Settings` com campos `fipe_monthly_update_*` nas linhas 319-323 como descrito (realidade ≠ spec)

### Etapa 2: Jobstore persistente + executor dedicado  [sensível]  (REQ-001, REQ-002, REQ-010)
- FAZ: Em `app/scheduler/run.py`, dentro de `start_scheduler()`:
  1. Adicionar import `from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore` no topo do arquivo, junto aos outros imports do apscheduler.
  2. No construtor `BackgroundScheduler(...)`, adicionar o kwarg `jobstores={"default": SQLAlchemyJobStore(url=settings.database_url)}` (antes ou depois de `executors=`, mantendo `timezone`, `executors`, `job_defaults` como estão).
  3. No dict `executors={...}` existente, adicionar uma nova entrada `"fipe": ThreadPoolExecutor(1)`.
  4. NÃO alterar o registro de nenhum outro job neste passo — isso é feito na Etapa 5.
- TOCA: `app/scheduler/run.py`
- VALIDA COM: `pytest tests/test_scheduler_jobstore_persistence.py -q` (testes 1-2 do plano) deve passar; `pytest tests/test_scheduler_fipe_registration.py -q` (testes já existentes, sem a Etapa 15 ainda) deve continuar passando sem regressão
- ESCALA SE: `BackgroundScheduler` já tiver um kwarg `jobstores=` configurado com valor diferente (realidade ≠ spec — decisão residual sobre merge de jobstores)

### Etapa 3: `FipeApiClient`  (REQ-003, REQ-004, REQ-005)
- FAZ: Criar `app/services/fipe_api_client.py` implementando exatamente a classe `FipeApiClient` e exceção `FipeApiError` do contrato acima. Usar `requests.Session()` (guardada como atributo de instância) para reuso de conexão. `_request` deve: aplicar throttle (dormir a diferença entre `rate_limit_ms` atual e o tempo desde a última chamada, usando `time.monotonic()` e `time.sleep`), fazer `session.post(f"{BASE_URL}/{endpoint}", json=body, timeout=self._timeout_s)`, tratar 429 (dobrar throttle até `max_throttle_ms`, usar `Retry-After` se presente senão backoff exponencial base 5000ms), tratar outros HTTP não-2xx e `requests.RequestException` (backoff exponencial base 1000ms), tratar corpo `{"erro": ...}` levantando `FipeApiError` imediatamente sem retry, e levantar `FipeApiError` ao esgotar `max_retries`. `get_models` deve extrair a lista da chave `"Modelos"` da resposta (a API retorna `{"Modelos": [...], "Anos": [...]}` para esse endpoint).
- TOCA: `app/services/fipe_api_client.py` (novo)
- EXEMPLO E/S: `client.get_latest_reference_table()` com `_request` mockado retornando `[{"Codigo": 320, "Mes": "agosto/2026"}]` → retorna `{"Codigo": 320, "Mes": "agosto/2026"}`
- VALIDA COM: `pytest tests/test_fipe_api_client.py -q` (testes 3-8 do plano, a serem escritos nesta mesma etapa) — 6 testes, todos verdes
- ESCALA SE: validação falha 2x seguidas sem causa óbvia (ex: incerteza sobre onde o throttle deve ser medido — `time.monotonic()` vs `time.time()`)

### Etapa 4: `fipe_catalog_crawler.py`  (REQ-006, REQ-012)
- FAZ: Criar `app/services/fipe_catalog_crawler.py` implementando `crawl_latest_fipe_prices` exatamente conforme o contrato. Fluxo: `ref = client.get_latest_reference_table()` → `brands = client.get_brands(ref["Codigo"])[:limit_brands]` (se `limit_brands` for `None`, não fatiar) → para cada marca, `models = client.get_models(...)` → para cada modelo, `years = client.get_model_years(...)` (cada item de `years` tem `Value` no formato `"{ano}-{codigo_combustivel}"`, split por `"-"` para extrair `ano` e `codigo_combustivel`) → para cada ano/combustível, `price = client.get_price(...)`, e monta o dict de saída usando os campos da resposta (`Valor`→`valor`, `Marca`→`marca`, `Modelo`→`modelo`, `AnoModelo`→`ano`, `Combustivel`→`combustivel`, `CodigoFipe`→`codigo_fipe`, `MesReferencia`→`mes_referencia`, mais `"tipo_veiculo": "car"` fixo). Envolver a chamada de `get_price` (por combinação individual) em `try/except FipeApiError`, logando via `on_progress(f"erro em {marca}/{modelo}/{ano}: {exc}")` e continuando o loop sem abortar.
- TOCA: `app/services/fipe_catalog_crawler.py` (novo)
- EXEMPLO E/S: client fake com 1 marca, 1 modelo, 1 ano/combustível → retorna lista com exatamente 1 dict, chaves `{"mes_referencia", "tipo_veiculo", "marca", "modelo", "ano", "combustivel", "codigo_fipe", "valor"}`
- VALIDA COM: `pytest tests/test_fipe_catalog_crawler.py -q` (testes 9-11 do plano) — 3 testes, todos verdes; e `python -c "from app.services.fipe_external_pipeline_adapter import normalize_external_fipe_rows; from app.services.fipe_catalog_crawler import crawl_latest_fipe_prices; print('import OK')"` sem erro
- ESCALA SE: `app/services/fipe_external_pipeline_adapter.py` não tiver uma função `normalize_external_fipe_rows(rows, *, reference_month)` com essa assinatura (realidade ≠ spec)

### Etapa 5: Integrar crawler no job mensal  [sensível]  (REQ-007, REQ-008, REQ-009, REQ-010)
- FAZ:
  1. Em `app/scheduler/fipe_update_job.py`, reescrever `job_monthly_fipe_update()` conforme o contrato: se `settings.fipe_monthly_update_input_path` truthy, comportamento atual (abrir `SessionLocal()`, chamar `run_audited_monthly_fipe_update(db)` sem passar `input_path` explícito — ele já lê de settings internamente, conforme código atual). Caso contrário: chamar `crawl_latest_fipe_prices(FipeApiClient())` SEM sessão de DB aberta; serializar o resultado com `json.dump` em um `tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")`; guardar o path; em `try/finally`, dentro do `try` abrir `with SessionLocal() as db: run_audited_monthly_fipe_update(db, input_path=Path(temp_path))`, e no `finally` fazer `Path(temp_path).unlink(missing_ok=True)`.
  2. Em `app/scheduler/run.py`, no bloco de registro de `monthly_fipe_update` (por volta da linha 475), adicionar o kwarg `executor="fipe"` à chamada `sched.add_job(...)`.
- TOCA: `app/scheduler/fipe_update_job.py`, `app/scheduler/run.py`
- VALIDA COM: `pytest tests/test_fipe_update_job.py -q` (testes 12-14 do plano) e `pytest tests/test_scheduler_fipe_registration.py -q` (incluindo o novo teste 15) — todos verdes
- ESCALA SE: `run_audited_monthly_fipe_update` não aceitar um kwarg `input_path` opcional que sobrepõe `settings.fipe_monthly_update_input_path` (decisão residual: precisa decidir se a assinatura da função muda, o que é uma mudança de contrato público — se acontecer, escalar em vez de decidir sozinho)

### Etapa 6: CLI manual  (REQ-011, REQ-012)
- FAZ: Criar `scripts/run_fipe_monthly_job.py` seguindo o padrão de `scripts/run_monthly_fipe_sync.py` (mesmo estilo de `argparse`/`main()`/`if __name__ == "__main__"`). Argumentos: `--force` (bool flag, default False — quando ausente, o script deve recusar rodar e imprimir instrução para usar `--force`, evitando execução acidental), `--limit-brands N` (int, default None, repassado até `crawl_latest_fipe_prices` via uma variante do fluxo da Etapa 5 que aceita esse parâmetro — para isso, extrair a lógica de `job_monthly_fipe_update` em uma função auxiliar `run_monthly_fipe_update_once(*, limit_brands=None)` reutilizada tanto pelo job do scheduler quanto pelo CLI). Ao final, imprimir status/erro/updated_rows do `FipeUpdateRun` retornado.
- TOCA: `scripts/run_fipe_monthly_job.py` (novo), `app/scheduler/fipe_update_job.py` (extrair função auxiliar reutilizável)
- VALIDA COM: `python scripts/run_fipe_monthly_job.py` (sem `--force`) deve sair com código != 0 e imprimir mensagem pedindo `--force`, sem tocar rede/DB; `python scripts/run_fipe_monthly_job.py --help` deve listar `--force` e `--limit-brands`
- ESCALA SE: a extração da função auxiliar mudar o comportamento coberto pelos testes da Etapa 5 (rodar `pytest tests/test_fipe_update_job.py -q` de novo após a extração — se algum teste da Etapa 5 quebrar, é regressão, escalar)

### Etapa 7: Documentação de deploy  [sensível]  (não mapeia a um REQ verificável por teste — é doc)
- FAZ: Atualizar `.env.example` (se ainda não coberto pela Etapa 1) com um comentário explicando que `FIPE_MONTHLY_UPDATE_ENABLED=true` precisa ser setado manualmente no `.env` de produção do Pi (`/opt/autohunter/.env`) para o job realmente escrever dados (kill switch), e que por padrão ele fica desligado. Adicionar uma nota equivalente em `deploy/raspberry/systemd/autohunter-scheduler.service` como comentário (`#`) acima de `EnvironmentFile=`, ou em um novo `deploy/raspberry/README.md` se já existir um — verificar primeiro se já existe doc de deploy para não duplicar.
- TOCA: `.env.example`, `deploy/raspberry/systemd/autohunter-scheduler.service` (comentário) ou `deploy/raspberry/README.md`
- VALIDA COM: revisão manual do diff — não há comando automatizado para "documentação correta"; o critério é: o texto menciona explicitamente `FIPE_MONTHLY_UPDATE_ENABLED` e o fato de ser `False` por padrão
- ESCALA SE: não há condição mecânica de escalação nesta etapa (é conteúdo textual) — se o executor tiver dúvida sobre ONDE colocar a doc (não existe `deploy/raspberry/README.md` nem outro lugar óbvio), escalar por "decisão residual"

## Riscos conhecidos e mitigação

| Risco | Etapa | Mitigação já embutida na spec |
|---|---|---|
| Varredura completa demora horas e pode expirar a sessão de DB se mal estruturada | 5 | Crawler roda inteiramente ANTES de abrir `SessionLocal()`; DB só é tocado na fase curta de sync (REQ-007) |
| Job mensal trava o scheduler para outros jobs periódicos (ticks de 10-60s) | 2, 5 | Executor dedicado `"fipe"` com 1 worker, isolado de `"default"` (REQ-010) |
| API pública da FIPE muda contrato ou fica fora do ar durante a varredura | 3, 4 | `FipeApiError` explícita + retry/backoff; erro em uma combinação individual não aborta a varredura inteira (loga e pula) |
| CLI manual roda contra produção por engano | 6 | Exige `--force` explícito; sem ele, sai sem tocar rede/DB |
| `SQLAlchemyJobStore` falha ao conectar no boot (DB fora do ar) e derruba o processo | 2 | Comportamento aceito deliberadamente: `Restart=always` do systemd já cobre isso (mesmo padrão de qualquer outra dependência de DB no boot) — não é mitigado na spec, é um Não-objetivo implícito |
| Arquivo temporário do crawler vaza em disco se o processo for morto no meio (SIGKILL) | 5 | Não totalmente mitigável (finally não roda em SIGKILL); mitigação parcial: nome com prefixo `fipe_crawl_` reconhecível para limpeza manual futura, mas isso é aceito como risco residual, não implementado nesta spec |

## Análise de consistência (preenchida antes de liberar)
- [x] Todo requisito do objetivo é coberto por ao menos um critério de aceitação (REQ-001 a REQ-012, todos com comando de verificação)
- [x] Toda etapa consome apenas artefatos criados por etapas anteriores: Etapa 3 usa settings da Etapa 1; Etapa 4 usa `FipeApiClient` da Etapa 3; Etapa 5 usa crawler da Etapa 4 e executor da Etapa 2; Etapa 6 usa a função extraída na própria Etapa 5 (nota: Etapa 6 modifica o arquivo da Etapa 5 novamente para extrair a função auxiliar — isso é uma dependência sequencial estrita Etapa 5 → Etapa 6, refletido no grafo)
- [x] Nenhuma contradição entre contratos, exemplos e testes — verificado cruzando os 4 métodos do `FipeApiClient` contra os testes 3-8 e o `crawl_latest_fipe_prices` contra os testes 9-11
- [x] Nenhuma frase delega julgamento — revisado; único ponto de risco era a Etapa 7 ("verificar primeiro se já existe doc"), mantido como está porque é uma checagem factual (arquivo existe ou não), não uma escolha de design
