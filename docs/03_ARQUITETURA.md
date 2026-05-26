# Arquitetura — Melhorias Estruturais

Atualizado em: 2026-05-25.  
Estado confrontado com a `main`.

> Documento dono de **estrutura interna, decomposição de módulos e acoplamento técnico**.  
> Não detalhar aqui eficiência operacional, bugs fechados, fluxo comercial ou UX.

---

## Escopo deste documento

Este documento cobre:

- decomposição de serviços grandes;
- split de handlers admin;
- fronteiras de settings/configuração;
- redução de acoplamento estrutural.

Assuntos relacionados ficam em documentos donos:

| Assunto | Documento dono |
|---|---|
| Bugs corrigidos e validações | `07_BUGS.md` |
| Eficiência, sender, backup, carga Raspberry | `08_EFICIENCIA.md` |
| Pagamento/assinatura | `06_SUBSCRIPTION.md` |
| UX/copy | `01_UX.md` |
| Lançamento/beta | `04_LAUNCH_PLAN.md` |

---

## Estado atual do roadmap estrutural

### Concluído / não reabrir

- **Admin split parcial:** health/audit/errors, dedupe/tracking, digest, FIPE e metrics já têm módulos dedicados.
- **Pool SQLAlchemy:** tratado como concluído; detalhes em `08_EFICIENCIA.md` e `07_BUGS.md`.
- **Índice parcial de notifications:** tratado como concluído; detalhes em `07_BUGS.md`.
- **Scripts órfãos removidos:** tratado como concluído; detalhes em `08_EFICIENCIA.md`.
- **Sender e Playwright baseline RPi:** tratados como concluídos; detalhes em `08_EFICIENCIA.md`.

### Ainda pendente neste documento

- Concluir o split de `app/bot/handlers_admin.py`.
- Quebrar incrementalmente `app/services/source_execution_service.py`.
- Preparar `app/core/settings.py` para namespaces por domínio mantendo compatibilidade flat.

---

## ARCH-01 — `source_execution_service.py` ainda é god object

**Estado atual:** `run_source_for_all_wishlists` ainda concentra elegibilidade, dispatch v1/v2/dual, scraping, ingestão, matching, telemetria, erro, backoff e reconciliação de atividade.

**Extração incremental recomendada:**

```text
Etapa 1: extrair _run_single_group(...)
  → scrape + ingest + match de um grupo
  → retorna resultado agregado
  → preserva contrato externo

Etapa 2: extrair _post_run_telemetry(...)
  → persiste source_runs/telemetry/system_logs
  → separa observabilidade da execução

Etapa 3: extrair _reconcile_activity(...)
  → atualiza last_seen/inatividade após o run
```

**Critério:** `run_source_for_all_wishlists` deve virar orquestrador legível.

---

## ARCH-02 — `settings` como god object

**Estado atual:** `app/core/settings.py` segue flat e concentra DB, Telegram, deploy admin, Playwright, scheduler, sender, tracking, dedupe, leilões, alertas, paths, fontes e feature flags.

**Direção:** criar namespaces por domínio mantendo acesso flat por compatibilidade.

Exemplo de direção:

```python
class DBSettings(BaseModel): ...
class PlaywrightSettings(BaseModel): ...
class SchedulerSettings(BaseModel): ...

class Settings(BaseModel):
    db: DBSettings
    playwright: PlaywrightSettings
    scheduler: SchedulerSettings
```

**Critério:** módulos novos podem usar `settings.db`, `settings.playwright`, `settings.scheduler`, mas acessos legados continuam funcionando.

---

## ARCH-03 — `handlers_admin.py` ainda não é dispatcher puro

**Estado atual verificado:** `handlers_admin.py` já delega vários comandos para módulos dedicados, mas ainda mantém domínios grandes.

### Já extraído

```text
app/bot/admin_handlers_sources.py       → /admin sources parcial
app/bot/admin_handlers_deploy.py        → /admin deploy
app/bot/admin_handlers_health.py        → /admin health, /admin audit, /admin errors
app/bot/admin_handlers_diagnostics.py   → /admin dedupe, /admin tracking
app/bot/admin_handlers_digest.py        → /admin digest
app/bot/admin_handlers_fipe.py          → /admin fipe
app/bot/admin_handlers_metrics.py       → /admin metrics
```

### Ainda dentro de `handlers_admin.py`

```text
/admin users
/admin premium
/admin auctions
/admin runall
/admin warmup
/admin matchdebug
/admin requeue
/admin reindex_wishlists
/admin source
/admin fb_sessions
helpers compartilhados e imports remanescentes
```

### Próximas fases recomendadas

| Fase | Escopo | Módulo sugerido |
|---|---|---|
| 3C | users/premium | `app/bot/admin_handlers_users.py` |
| 3D | runall/warmup/source/fb_sessions | `app/bot/admin_handlers_execution.py` |
| 3E | matchdebug/requeue/reindex | `app/bot/admin_handlers_matching_ops.py` |
| 3F | auctions | `app/bot/admin_handlers_auctions.py` |
| 3G | limpeza final do dispatcher | `handlers_admin.py` como glue mínimo |

**Critério:** responsabilidade única, sem import circular e sem mudar comportamento/textos.

---

## Prioridade atual

| Ordem | Item | Escopo | Risco de não fazer |
|---|---|---|---|
| 1 | ARCH-03 fase 3C | Extrair users/premium | Plano/assinatura seguem acoplados ao dispatcher |
| 2 | ARCH-03 fase 3D | Extrair execução/source/fb_sessions | Operação de execução segue misturada ao admin geral |
| 3 | ARCH-03 fase 3E | Extrair matching ops | Diagnóstico/reprocessamento seguem no arquivo principal |
| 4 | ARCH-03 fase 3F | Extrair auctions | Bloco grande de leilões mantém alto acoplamento |
| 5 | ARCH-01 fase 1 | Extrair `_run_single_group` | Runner de source segue difícil de testar/evoluir |
| 6 | ARCH-02 fase 1 | Namespaces de settings | Configuração segue sem fronteiras por domínio |

---

## Próxima PR recomendada

**ARCH-03 fase 3C — extrair users/premium.**

Diretriz:

```text
Criar app/bot/admin_handlers_users.py
Mover apenas /admin users e /admin premium, mais helpers exclusivos
Não mexer em auctions, runall, warmup, matchdebug, requeue ou source
Manter textos e comportamento existentes
Evitar import circular
Atualizar esta doc ao final da PR
```
