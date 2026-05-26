# Claude Review Follow-up

## Estado consolidado pós-tranche

Este documento consolida o estado real após as entregas recentes.

## Concluído

- **P0 schema/migrations** validado em PostgreSQL/Supabase com `scripts/validate_postgres_schema.py` (head único, índice partial de notifications e colunas críticas presentes).
- **BUG-05 (filtros estruturados por comando)** resolvido no fluxo `/wishlist filter ...` com parsing composto, UX de ajuda e cobertura de testes para normalização/matching.
- **Tracking/price_drop** concluído com sync funcional, alerta `price_drop` e anti-duplicidade/cooldown.
- **Observabilidade admin de tracking** disponível via `/admin tracking`.
- **Weekly Digest foundation** concluído:
  - `build_weekly_digest_for_user` + renderer;
  - `/admin digest user`;
  - `/admin digest candidates`;
  - preferências com opt-in/opt-out;
  - scheduler controlado com `/admin digest run [dry|live]` e gate de live;
  - comando de usuário `/digest`;
  - refinamento de conteúdo;
  - contexto de raridade no conteúdo.
- **FIPE import/coverage** implementado:
  - import/upsert via `scripts/import_fipe_prices.py`;
  - diagnóstico via `/admin fipe coverage`.
- **score_v2 incremental** já implementado com componentes market/FIPE/raridade e fallback neutro quando não há dados suficientes.

## Preparado com feature flag / aguardando observação

- **Cross-source dedupe (BUG-06) live**:
  - fingerprint calculado/persistido e diagnóstico de colisões implementados;
  - shadow report implementado (`/admin dedupe shadow`);
  - comportamento live controlado por flags:
    - `cross_source_dedupe_enabled=false` (default);
    - `cross_source_dedupe_shadow_mode=true` (default).
- Status: funcional e observável, porém com supressão live mantida OFF por padrão até validação operacional.

## Pendências operacionais

- Rodar janela de observação em shadow para dedupe e revisar `/admin dedupe shadow`.
- Revisar `/admin dedupe collisions` durante a janela para calibrar falso positivo/falso negativo.
- Importar carga real FIPE no ambiente operacional.
- Mecanismo de carga já existe (template CSV, guia operacional e importador local); próximo passo é executar a primeira carga real no ambiente operacional.
- Rodar `/admin fipe coverage` após carga para confirmar cobertura útil.
- Após a primeira carga e cobertura útil, a pendência FIPE pode ser considerada operacionalmente endereçada.
- Integrar/ajustar cron/systemd externo no Raspberry (se ainda desejado operacionalmente).

## Pendências futuras de produto/refactor

- Refactor maior de `handlers_admin` (decomposição por domínios).
- Mitigação adicional de `settings` como god object.
- Evolução de comandos guiados/botões no Telegram.
- Refinamentos futuros de FIPE/dados reais (qualidade/cobertura).
- Eventual ativação live de dedupe cross-source após observação real consistente.

- Decisão FIPE (2026-05): opção 2 adotada com base local mensal; próximo passo é ingestão mensal de catálogo staging; CSV manual deixa de ser caminho principal.

## FIPE mensal (update 2026-05)

- staging mensal de catálogo FIPE implementado (`fipe_catalog_entries` + `fipe_sync_runs`).
- adapter de pipeline externo implementado para JSON/CSV com aliases comuns e preservação de `raw_payload`.
- próximo passo: resolver AutoHunter → FIPE para alimentar `fipe_prices` (sem alteração em `score_v2` nesta etapa).


- Resolver diagnóstico FIPE implementado (preview read-only).
- Próximo passo: persistir mapping ou alimentar `fipe_prices` apenas para matches high com fluxo dry-run/apply.

## Update 2026-05-26
- Resolver diagnóstico FIPE refinado para busca por tokens, melhor recall (ex.: Civic Si, Golf GTI), e scoring com explicabilidade ampliada.
- Critério de ambiguidade atualizado: high+high próximo (<15) => ambiguous; high com folga >=15 => matched; medium => ambiguous.
- Fluxo segue read-only nesta fase: sem escrita em fipe_prices, sem score_v2, sem chamadas externas.
- Próximo passo planejado: etapa dry-run/apply para persistir somente matches high não ambíguos.



## Follow-up FIPE plan dry-run

- Implementado planejamento dry-run de `fipe_prices` a partir do resolver AutoHunter→FIPE.
- Admin agora pode estimar `planned_inserts`, `would_updates` e `skipped reasons` sem persistir dados.
- Próximo passo: fluxo `apply` controlado com confirmação explícita e estratégia de rollback em PR separada.


## FIPE apply plan controlado

Implementado apply controlado para `fipe_prices` com guardrails:
- dry-run default;
- live explícito;
- sem scheduler e sem apply automático pós-import;
- sem update automático de `would_updates`.

Próximo passo operacional:
1. rodar `/admin fipe plan`;
2. validar `/admin fipe apply_plan ... dry`;
3. aplicar `/admin fipe apply_plan ... live` com limite pequeno;
4. validar cobertura via `/admin fipe coverage`.

- Implementada auditoria persistente para `/admin fipe apply_plan` (dry-run/live) desacoplada da transação principal.
- Próximo passo operacional: rodar dry-run/live pequeno e validar coverage de logs/resultados em produção controlada.
