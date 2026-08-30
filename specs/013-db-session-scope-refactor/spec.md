# 013 — Unit-of-work `session_scope()` + migração dos hot-paths de execução

`[spec-kit: T3 — 9pts: arquivos=2 (5+ arquivos), decisoes=2 (padrão de concorrência/thread-safety novo), risco=2 (toca o factory de Session usado por toda a app), novidade=2 (guard de thread inexistente hoje), verif=1 (testável com pytest + threads)]`

## Objetivo

Substituir o padrão ad-hoc `SessionLocal()` / `with SessionLocal() as db:` (127 ocorrências em `app/`) por um unit-of-work único — `with session_scope() as db:` — que centraliza commit/rollback/close, e detecta em runtime qualquer `Session` que seja usada a partir de uma thread diferente daquela que a criou. Migrar os 10 arquivos do caminho crítico de execução em background (scheduler + thread pools) como primeira onda.

## Decisões tomadas (não delegar ao executor)

1. **Onde vive o helper**: `app/db/session.py`, ao lado de `SessionLocal`/`engine` (mesmo módulo, sem novo arquivo). Import: `from app.db.session import session_scope`.
2. **Semântica de `session_scope()`**:
   - Cria `db = SessionLocal()`.
   - `yield db`.
   - Sem exceção → `db.commit()`.
   - Exceção → `db.rollback()` e **re-raise** (nunca engole silenciosamente).
   - `finally` → `db.close()` sempre.
   - Commits intermediários explícitos que já existam dentro do bloco (`db.commit()` no meio da função, para persistir unidades lógicas parciais) **permanecem** — `session_scope` só garante o commit/rollback *final*, não impede commits parciais deliberados.
3. **Guard de thread**: `SessionLocal` passa a usar uma subclasse `ThreadSafeSession(Session)` como `class_` do `sessionmaker`. Ela grava `self._owner_thread = threading.get_ident()` no `__init__` e valida em `execute`, `flush`, `commit`, `rollback`, `close`, `query` — se o thread atual (`threading.get_ident()`) for diferente do owner, levanta `RuntimeError` com mensagem explicando que Sessions do SQLAlchemy não são thread-safe e a thread worker deve abrir seu próprio `session_scope()`. Isso vale tanto para `session_scope()` quanto para `SessionLocal()` chamado diretamente (não migrado ainda) — a proteção é no factory, não no helper, então cobre 100% dos call-sites, migrados ou não.
   - Overhead: um `threading.get_ident()` (syscall barato, sem lock) por chamada interceptada — aceitável, não há budget de perf nesta spec.
4. **Contrato do `_process_group_isolated`** em `source_execution_service.py`: já abre um `SessionLocal()` novo dentro da própria worker thread e nunca compartilha a do caller — comportamento correto, migração é só estilística (trocar para `with session_scope() as thread_db:`, remover o `try/finally` manual de rollback/close que o helper já cobre).
5. **Injeção de Session nas camadas de serviço**: funções de serviço (`app/services/*.py`) continuam recebendo `db: Session` como parâmetro — isso já é o padrão predominante (`matching_service.py`, `notifications_queue_service.py` não têm nenhum `SessionLocal()` direto, já são compliant). `session_scope()` é chamado apenas no nível de entrypoint (job do scheduler, handler, script), nunca dentro de uma função de serviço que recebe `db` por parâmetro.

## Não-objetivos

- Migrar os handlers do bot Telegram (`app/bot/handlers_core.py` e afins — maior contagem bruta de `SessionLocal()`, mas rodam na event loop assíncrona do PTB, não em worker threads; sem risco de cruzamento de thread hoje). Fica para uma spec futura.
- Migrar os demais 8 arquivos do scheduler não listados na Onda 2 (`cleanup_job.py`, `weekly_wishlist_digest_job.py`, `market_stats_job.py`, etc.) ou scripts fora de `app/scheduler` e `app/services`.
- Alterar `app/db/deps.py` (`get_db`, dependency do FastAPI) — fora do caminho de background jobs, sem migração nesta spec.
- Mudar configuração do engine/pool (`_engine_kwargs`, `pool_size`, etc.).
- Adicionar retry/backoff a nível de session — fora de escopo.

## Requisitos (EARS)

- **REQ-001**: O SISTEMA DEVE fornecer `session_scope()` em `app/db/session.py` como context manager que cria uma `Session`, faz `yield`, comita em sucesso, reverte e propaga a exceção em falha, e sempre fecha a `Session`.
- **REQ-002**: QUANDO uma `Session` criada por `SessionLocal()` (diretamente ou via `session_scope()`) for usada (`execute`/`flush`/`commit`/`rollback`/`close`/`query`) a partir de uma thread diferente da que a criou, o SISTEMA DEVE levantar `RuntimeError` imediatamente, antes de tocar o banco.
- **REQ-003**: O SISTEMA DEVE migrar os 10 arquivos listados na Onda 2 para usar `with session_scope() as db:` no lugar de `SessionLocal()`/`with SessionLocal() as db:`, preservando o comportamento observável de cada job (commits parciais, tratamento de exceção existente, logs).
- **REQ-004**: A suíte de testes existente (incluindo `tests/test_browser_queue_job_session_lifecycle.py`, que já cobre `PendingRollbackError` e status de retry do `browser_queue_job`) DEVE continuar passando sem alteração no arquivo de teste.
- **REQ-005**: O SISTEMA DEVE ter um teste automatizado que prove REQ-002: cria uma `Session` na thread principal, tenta usá-la a partir de uma segunda thread, e verifica que `RuntimeError` é levantado (e que o mesmo uso a partir da thread que a criou funciona normalmente).

## Premissas assumidas

- **PREM-01**: "10 arquivos mais quentes" = caminho crítico de execução em background (scheduler + thread pools), não a contagem textual bruta de `SessionLocal()` — confirmado com o usuário. Lista fixada na Onda 2 abaixo, cobrindo todos os 6 `ThreadPoolExecutor` nomeados em `run.py` (`default`, `http`, `browser`, `sender`, `fipe`, `fipe_lookup`) mais o ponto de isolamento de thread em `source_execution_service.py`.
- **PREM-02**: A migração de `source_execution_service.py` é majoritariamente cosmética (o isolamento por thread já está correto) — confirmado com o usuário, entra na Onda 2 por consistência.
- **PREM-03**: `matching_service.py` e `notifications_queue_service.py`, citados no pedido original como hot-paths, já recebem `db: Session` por parâmetro e não têm nenhum `SessionLocal()` direto — nenhuma migração necessária neles; registrado aqui para não ficar "esquecido" silenciosamente.
- **PREM-04**: O guard de thread usa `threading.get_ident()` comparado no momento da criação vs. no momento do uso — não cobre o caso (fora de escopo) de uma mesma OS-thread ser reciclada por um thread-pool e reusar um `ident` antigo de forma colidente; isso é considerado risco residual aceitável dado que `ThreadPoolExecutor` do Python não recicla `ident` de threads vivas simultaneamente.

## Contratos / assinaturas

```python
# app/db/session.py — adições

import threading
from contextlib import contextmanager
from sqlalchemy.orm import Session, sessionmaker


class ThreadSafeSession(Session):
    """Session que detecta uso a partir de uma thread diferente da que a criou."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._owner_thread_id = threading.get_ident()

    def _assert_owner_thread(self) -> None:
        current = threading.get_ident()
        if current != self._owner_thread_id:
            raise RuntimeError(
                f"Session criada na thread {self._owner_thread_id} usada na thread {current}. "
                "SQLAlchemy Sessions não são thread-safe: abra um novo `session_scope()` "
                "dentro da worker thread em vez de reutilizar uma Session de outra thread."
            )

    def execute(self, *args, **kwargs):
        self._assert_owner_thread()
        return super().execute(*args, **kwargs)

    def flush(self, *args, **kwargs):
        self._assert_owner_thread()
        return super().flush(*args, **kwargs)

    def commit(self, *args, **kwargs):
        self._assert_owner_thread()
        return super().commit(*args, **kwargs)

    def rollback(self, *args, **kwargs):
        self._assert_owner_thread()
        return super().rollback(*args, **kwargs)

    def close(self, *args, **kwargs):
        self._assert_owner_thread()
        return super().close(*args, **kwargs)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=ThreadSafeSession)


@contextmanager
def session_scope():
    """Unit-of-work único: commit em sucesso, rollback + re-raise em falha, close sempre."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

Entrada/saída de `session_scope()`: nenhum parâmetro; produz uma `Session` (via `yield`); não retorna valor.
Entrada/saída de `ThreadSafeSession._assert_owner_thread()`: nenhum parâmetro além de `self`; sem retorno; efeito colateral é levantar `RuntimeError` ou não fazer nada.

## Plano de testes (escrito antes da implementação)

Novo arquivo `tests/test_session_scope_thread_safety.py`:

1. `test_session_scope_commits_on_success` — usa `session_scope()`, insere uma linha (ex. `SystemLog` ou tabela simples já usada em outros testes), sai do bloco sem exceção, abre nova `SessionLocal()` e confirma que a linha foi persistida.
2. `test_session_scope_rolls_back_and_reraises_on_exception` — usa `session_scope()`, insere uma linha, levanta uma exceção proposital dentro do bloco, verifica que a exceção propaga (`pytest.raises`) e que a linha NÃO foi persistida (nova sessão não a encontra).
3. `test_session_used_from_creating_thread_works` — cria `db = SessionLocal()` na thread principal, chama `db.execute(text("SELECT 1"))` na mesma thread, não levanta.
4. `test_session_used_from_other_thread_raises` — cria `db = SessionLocal()` na thread principal, dispara uma `threading.Thread` que chama `db.execute(text("SELECT 1"))`, captura a exceção dentro da thread (via variável compartilhada, já que exceções de thread não propagam sozinhas), e no teste principal assere que foi `RuntimeError` com a mensagem esperada. Repete para `db.commit()` como segunda chamada interceptada, para cobrir mais de um método guardado.
5. `test_session_scope_session_is_thread_safe_instance` — confirma que `type(db)` dentro do `session_scope()` é `ThreadSafeSession` (garante que a proteção está de fato ativa, não só documentada).

Testes de regressão obrigatórios (não escritos aqui, já existem — rodar como parte da validação):
- `tests/test_browser_queue_job_session_lifecycle.py` — cobre exatamente o cenário de commit parcial + exceção que a migração de `browser_queue_job.py` precisa preservar.
- Suíte completa `pytest -q` ao final da Onda 2 (Etapa final).

## Decisão residual resolvida durante execução — padrão "except loga e comita"

Vários jobs do scheduler seguem o idioma:
```python
with SessionLocal() as db:
    try:
        <trabalho>
        db.commit()
    except Exception as e:
        db.rollback()
        log(db, "error", ...)
        db.commit()
```
(sem `raise` — o except SILENCIA a exceção, já que quem chama é o APScheduler e não há caller para propagar).

**Regra de migração (vale para toda etapa da Onda 2 que encontrar este padrão exato, não precisa escalar de novo):**
```python
with session_scope() as db:
    try:
        <trabalho>
    except Exception as e:
        db.rollback()
        log(db, "error", ...)
        # SEM db.commit() aqui — a saída limpa do `with` (nenhuma exceção escapou,
        # pois o except não fez `raise`) já aciona o commit implícito de session_scope(),
        # que persiste o log de erro escrito acima.
```
- O `db.rollback()` dentro do `except` **permanece obrigatório** — precisa rodar imediatamente para limpar o estado "pending rollback" antes de qualquer outro uso de `db` (o `log(db, ...)` logo em seguida), o rollback de `session_scope()` só dispararia se a exceção escapasse do `with`, o que não acontece aqui.
- `db.commit()` do caminho de sucesso (fora do except) pode ficar como está (commit intermediário, permitido por "Decisões tomadas #2") ou ser removido a favor do commit implícito final — qualquer uma das duas é aceitável, não precisa escalar por causa disso.
- **Se o except tiver `raise`/re-throw** (padrão diferente, não visto ainda mas pode aparecer): manter o `db.commit()` final do except ANTES do `raise`, para que o log do erro seja persistido mesmo com `session_scope()` fazendo rollback (no-op, pois nada ficou pendente) na exceção repropagada.

## Decisão residual resolvida durante execução — testes que monkeypatcham `SessionLocal`

Vários arquivos de teste (`test_scheduler_jobstore_persistence.py`, `test_sender_job.py`, `test_fipe_lookup_job.py`, `test_fipe_update_job.py`, e possivelmente outros na Onda 2) fazem `monkeypatch(<módulo>.SessionLocal, ...)` para injetar um fake e capturar `commit()`/`rollback()`. Depois da migração, o código de produção chama `session_scope()` — que internamente usa o `SessionLocal` do módulo `app.db.session`, não o `SessionLocal` (agora não-importado, ou importado-mas-não-usado) do módulo do job. O mock antigo vira um no-op silencioso e os testes falham (ex.: contador de commits fica em 0).

**Isso NÃO é uma violação de TOCA nem de REQ-004.** REQ-004 protege `tests/test_browser_queue_job_session_lifecycle.py` especificamente como contrato comportamental imutável (ele testa *comportamento observável* do job, não a identidade do símbolo mockado). Os arquivos de teste acima mockam um **detalhe de implementação** (`SessionLocal` vs `session_scope`) que muda como consequência mecânica direta e inevitável da migração — não há forma de migrar o arquivo de produção sem tornar esses mocks obsoletos.

**Regra de migração (vale para toda etapa da Onda 2 que encontrar este padrão, não precisa escalar de novo):**
- É permitido e esperado editar o arquivo de teste correspondente para: (a) trocar o alvo do monkeypatch de `<módulo>.SessionLocal` para `<módulo>.session_scope`; (b) adaptar o fake para um context manager (`@contextmanager` ou classe com `__enter__`/`__exit__`) que produza o mesmo objeto fake de sessão usado antes.
- O que o teste **assertava sobre comportamento observável** (quais métodos foram chamados, em que ordem, com que payload, contagens de commit/rollback) deve continuar sendo verificado — apenas o mecanismo de injeção muda, não a asserção.
- Se a adaptação exigir inventar comportamento não coberto pelo teste original (ex.: o fake precisa decidir o que fazer em uma exceção que o teste antigo nunca exercitava), aí sim escalar — isso é decisão residual real, não mecânica.

## Etapas

### Onda 1 — Fundação (sequencial, bloqueia a Onda 2)

**Etapa 1 — `[sensível]` Implementar `ThreadSafeSession` + `session_scope()` em `app/db/session.py`** — CONCLUÍDA
- Arquivos: `app/db/session.py`
- Mudança: adicionar a classe `ThreadSafeSession`, trocar `SessionLocal = sessionmaker(...)` para incluir `class_=ThreadSafeSession`, adicionar `session_scope()` conforme contrato acima.
- VALIDA COM: `pytest -q tests/test_db_guardrails.py` deve passar. **NÃO** incluir `tests/test_browser_queue_job_session_lifecycle.py` na validação desta etapa — esse arquivo falha nesta etapa por design: ele exercita um bug real de cruzamento de thread em `browser_queue_job.py` (código ainda não migrado) que o guard agora detecta corretamente. A correção mora na Etapa 4; validar esse arquivo de teste lá.
- Resultado: implementado conforme o contrato da spec (confirmado por leitura direta do arquivo). A escalação recebida foi resolvida por esta atualização da spec, não por enfraquecer o guard.

**Etapa 2 — Criar `tests/test_session_scope_thread_safety.py` conforme o Plano de testes**
- Arquivos: `tests/test_session_scope_thread_safety.py` (novo)
- Depende da Etapa 1.
- VALIDA COM: `pytest -q tests/test_session_scope_thread_safety.py` — todos os 5 casos passam.
- Condição de escalação: se não houver uma tabela/model simples reaproveitável em `tests/conftest.py` para o insert de teste, escalar para decidir qual usar (não inventar um model novo).

### Onda 2 — Migração dos 10 arquivos do caminho crítico (paralelizável entre si, cada etapa depende só da Onda 1)

Para cada etapa: trocar `SessionLocal()` / `with SessionLocal() as db:` por `with session_scope() as db:`; remover `try/except`/`finally` que só duplicam o que `session_scope()` já faz (rollback genérico + close); **preservar** qualquer `db.commit()` intermediário que já exista para persistir unidades lógicas distintas dentro da mesma função; preservar toda lógica de negócio, logging e mensagens de erro inalteradas.

**Etapa 3 — `app/scheduler/run.py`**
- Cobre: bootstrap (`_bootstrap_source_configs_once`), `_log_suppressed_exception`, `job_heartbeat` (hoje sem context manager — `db = SessionLocal()` bare), `job_run_source_for_all_wishlists`, smoke test do Playwright em `start_scheduler`, o `with SessionLocal() as db:` de `auction_cfg`.
- VALIDA COM: `pytest -q tests/ -k "scheduler or heartbeat"` + `python -c "import app.scheduler.run"` (import limpo, sem erro de sintaxe/circular import).
- Escalação: se `job_heartbeat` ou `job_run_source_for_all_wishlists` tiverem algum `except` que hoje depende de a Session ainda estar "viva" após a exceção (uso de `db` dentro do bloco `except`), escalar — `session_scope()` já fechou a Session antes do `except` do chamador rodar.

**Etapa 4 — `[sensível]` `app/scheduler/browser_queue_job.py` — inclui correção de bug real de cruzamento de thread**
- **Achado durante a Etapa 1**: `job_browser_queue_worker()` cria `db = SessionLocal()` na thread principal e passa esse MESMO `db` para `run_source_for_all_wishlists(db, ...)` dentro de uma `threading.Thread` filha (`worker_thread`). Após o `worker_thread.join(timeout=...)`, a thread principal volta a usar o mesmo `db` (commit/rollback/close). Isso é exatamente o padrão que REQ-002 existe para pegar — o guard da Etapa 1 já detecta e bloqueia isso corretamente (`RuntimeError: Acesso de thread cruzada...`), o que quebrou `tests/test_browser_queue_job_session_lifecycle.py::test_internal_commit_failure_does_not_wedge_job_or_mask_status` porque esse teste hoje depende do handoff cross-thread para funcionar.
- **Correção de design (decidida, não delegar)**: a thread filha (`worker_thread`) deixa de receber o `db` da thread principal. Em vez disso, o alvo da thread (`_run_and_capture` ou nome equivalente da função interna hoje passada a `threading.Thread(target=...)`) abre **sua própria** `with session_scope() as child_db:` e chama `run_source_for_all_wishlists(child_db, ...)` dentro desse bloco — a exceção (se houver) continua sendo capturada em `result_box["exc"]` como já é feito hoje; `session_scope()` já faz o rollback/close da `child_db` antes da exceção propagar para `result_box`. A thread principal (`db`) nunca é passada para a child thread e nunca é tocada por ela — ela segue seu próprio ciclo (`with session_scope() as db:` no lugar de `db = SessionLocal()` + `try/finally` manual) só para lock/status/commit final, e ao reencontrar `result_box["exc"]` apenas usa a *mensagem* da exceção (`str(e)`), nunca o objeto de sessão filho.
  - Caminho de timeout/thread órfã (`_reclaim_wedged_lock`/`db2`): já abre sua própria `SessionLocal()` isolada — só precisa trocar para `with session_scope() as db2:`, sem mudança de design.
- Arquivos: `app/scheduler/browser_queue_job.py`
- VALIDA COM: `pytest -q tests/test_browser_queue_job_session_lifecycle.py` — as 3 funções de teste existentes devem passar **sem modificação no arquivo de teste** (a correção de design acima preserva o contrato: `job.error` continua contendo `"this_table_does_not_exist"`, só que a exceção agora se origina da sessão isolada da child thread em vez da sessão compartilhada).
- Escalação: se, mesmo com a child thread usando sua própria `session_scope()`, o teste ainda falhar, ou se `worker_thread.join(timeout=...)` expirar (thread órfã ainda viva) e a lógica atual precisar tocar em algo que só a child_db teria — escalar, não inventar um segundo workaround.
- Marcado `[sensível]`: corrige um bug de concorrência real em código de produção que roda em background continuamente.

**Etapa 5 — `app/scheduler/http_queue_job.py`**
- VALIDA COM: `pytest -q tests/ -k "http_queue"` (se não houver teste dedicado, `python -c "import app.scheduler.http_queue_job"` + revisão manual de que a assinatura pública das funções não mudou).

**Etapa 6 — `app/scheduler/sender_job.py`**
- VALIDA COM: `pytest -q tests/ -k "sender"` ou import limpo conforme Etapa 5.

**Etapa 7 — `app/scheduler/fipe_update_job.py`**
- VALIDA COM: `pytest -q tests/ -k "fipe_update"` ou import limpo.

**Etapa 8 — `app/scheduler/fipe_lookup_job.py`**
- VALIDA COM: `pytest -q tests/test_fipe_lookup_job.py`

**Etapa 9 — `app/scheduler/autopilot_job.py`**
- VALIDA COM: `pytest -q tests/ -k "autopilot"` ou import limpo.

**Etapa 10 — `app/services/source_execution_service.py`**
- Foco: `_process_group_isolated` — trocar para `with session_scope() as thread_db:`, remover o `try/except`/`finally` manual de rollback/close (o helper já cobre); manter a conversão de exceção em `{"ok": False, ...}` que a função já faz.
- VALIDA COM: `pytest -q tests/ -k "source_execution"` (se existir) + `pytest -q tests/test_browser_queue_job_session_lifecycle.py` (chamador indireto).

**Etapa 11 — `app/scheduler/auction_notification_job.py`**
- VALIDA COM: `pytest -q tests/ -k "auction_notification"` ou import limpo.

**Etapa 12 — `app/scheduler/tracking_alerts_job.py`**
- VALIDA COM: `pytest -q tests/ -k "tracking_alerts"` ou import limpo.

### Onda 3 — Fechamento

**Etapa 13 — Suíte completa + varredura de regressão**
- VALIDA COM: `pytest -q` (suíte inteira, exceto testes marcados `postgres` se não houver Postgres disponível localmente) sem novas falhas.
- Condição de escalação: qualquer falha fora dos arquivos tocados nesta spec.

## Critérios de aceitação

- `session_scope()` e `ThreadSafeSession` existem em `app/db/session.py` e são usados pelos 10 arquivos da Onda 2.
- REQ-005 comprovado por teste automatizado (`tests/test_session_scope_thread_safety.py`).
- `tests/test_browser_queue_job_session_lifecycle.py` passa sem modificação no arquivo.
- `pytest -q` sem falhas novas.
- Nenhum dos 10 arquivos da Onda 2 contém mais `SessionLocal()` direto fora de dentro do próprio `session_scope()`.

## Registro

Ver `RUN.md` neste diretório (append-only).
