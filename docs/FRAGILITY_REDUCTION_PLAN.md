# AutoHunter — Fragility Reduction Plan (diagnóstico real)

Data do diagnóstico: **2026-04-24**.
Escopo: estado atual do código (sem inferir produção).

## Classificação de achados
Legenda: **bug real** | **risco operacional** | **melhoria técnica** | **melhoria operacional** | **melhoria de produto**.

## 1) Onde `source_execution_service.py` concentra responsabilidades

### Fatos confirmados
- O serviço concentra, no mesmo fluxo, validação de config runtime (`ensure_source_configs`, enable, sched, backoff), seleção de adapter (`v1/v2/dual`), execução scrape+ingest+matching, classificação de erro, persistência de run/state/event/log, e reconciliação de activity pós-run.
- O método público `run_source_for_all_wishlists(...)` é o ponto único usado por scheduler/admin runall.

### Achado
- **Concentração alta de responsabilidades no runner central** → **melhoria técnica** + **risco operacional**.

## 2) Funções extraíveis com baixo risco

### Candidatas (confirmadas no código)
- Seleção de caminho de scrape/adapter (`v1/v2/dual`) com preenchimento de `ctx._last_adapter_meta`.
- Montagem de payload de run (success/error/blocked/bug) com campos híbridos e run_summary.
- Helpers de elegibilidade já existem parcialmente (`_wishlist_eligibility_snapshot`).

### Decisão desta intervenção
- Extraído para `app/services/source_execution_helpers.py`:
  - `build_scrape_dispatch(...)`
  - `build_run_payload(...)`

Classificação: **melhoria técnica** (baixo risco, comportamento preservado).

## 3) Contratos críticos que não podem mudar

### Confirmado
- Assinatura e semântica de `run_source_for_all_wishlists(...)` (usada por scheduler e admin).
- Status operacionais persistidos: `success|blocked|error|skipped` em `source_runs`/`source_states`.
- Contrato DB-driven de source (`source_configs` + `source_states`).
- Contratos de fila `scrape_jobs` (`queued|running|done|failed`) e pipeline de notificação.

Classificação: **risco operacional**.

## 4) Como caminhos `v1/v2/dual` são selecionados

### Confirmado
- O runner lê flags por `read_source_impl_flags(cfg.extra)`.
- Se `impl=v2` e houver scraper v2 (`get_scraper(src)`), usa adapter v2.
- Se `impl=dual` e houver v2, roda `execute_dual_run(...)` e atualmente normaliza pelo caminho v1 (`dual_v1`) com relatório comparativo.
- Fallback padrão: scrape plugin + adapter v1.

Classificação: **melhoria técnica** (documentação/observabilidade), com **risco operacional** se alterado sem teste.

## 5) Como scheduler decide due/backoff/enqueue

### Confirmado (`app/scheduler/run.py`)
- Tick periódico por source.
- Gating por `is_enabled`, implementação disponível, Playwright habilitado (quando browser).
- Due por `last_effective_run_at + sched_minutes`.
- Backoff via `is_source_allowed(...)`.
- Enqueue em `scrape_jobs` (`queue=http|browser`) com dedupe/cap.

Classificação: **melhoria operacional** (monitoramento) + **risco operacional** (se quebrar due/backoff).

## 6) Como workers processam `scrape_jobs`

### Confirmado
- Jobs são consumidos por workers HTTP/Browser agendados no scheduler.
- Cada worker executa source run e atualiza status/result/error no job.
- Há mecanismos de stale recovery/requeue (já cobertos por testes no repo).

Classificação: **risco operacional**.

## 7) Onde matching e notification queue são chamados

### Confirmado
- `scrape_ingest_match_many(...)` no pipeline chama matching e fila de notifications por wishlist.
- O diagnóstico de `queued=0` com match>0 usa buckets/explicação (`queue_notifications_for_matches_diag`, `health.explain`).

Classificação: **melhoria operacional**.

## 8) Comandos admin sensíveis

### Confirmado
Sensíveis no runtime atual:
- `/admin ...` (sources/runall/requeue/matchdebug/errors/users/deploy/tokens/health/fb_sessions)
- `/debug`
- `/setplan`
- `/setlimit`

Classificação: **risco operacional**.

## 9) Cobertura `is_admin` em comandos sensíveis

### Confirmado
- `/admin` bloqueia na entrada (`cmd_admin`) usando `app.bot.admin.is_admin`.
- `/debug` bloqueia na entrada com `is_admin`.
- `/setplan` e `/setlimit` passam por `_ensure_admin` (que delega para `is_admin`).

### Melhoria aplicada
- Testes de guarda adicionados para garantir bloqueio sem efeitos colaterais quando não-admin.

Classificação: **melhoria técnica** + **melhoria operacional**.

## 10) Alertas reais disponíveis (estado atual)

### Confirmado no código
- scheduler stale: sim (heartbeat + stale check em admin sources/health).
- source stale: sim (staleness por source).
- fila travada: parcial (havia dados de pool; agora health inclui `running` travado em `scrape_jobs`).
- sender parado: parcial (agora health inclui `queued_old` em notifications).
- source bloqueada: sim (`blocked`, backoff, eventos/logs).
- erro recorrente: sim (consecutive_failures e últimas falhas por source).

Classificação: antes **risco operacional parcial**; após intervenção: **melhoria operacional**.

---

## Resumo das ações nesta etapa
1. Refatoração incremental de baixo risco no `source_execution_service` (extração de helpers).
2. Auditoria e testes de autorização admin para comandos sensíveis.
3. Enriquecimento de `/admin health` para visão operacional Telegram-first.
4. Plano/documentação de sources frágeis e backup/restore operacional mínimo (documentos dedicados).

