# FIPE Monthly Sync Architecture

## Decisão
Adotamos **base FIPE local mensal** (opção 2). O runtime AutoHunter continua consumindo apenas dados locais de banco. Não haverá chamada de API FIPE no fluxo principal (wishlist, matching, notification e score).

## Motivo
- previsibilidade operacional e custo controlado;
- menor risco de latência/rate-limit no caminho crítico;
- manter `score_v2` estável e desacoplado de integrações online.

## Papel do pipeline externo
`caiopizzol/fipe-data-pipeline` passa a ser referência/fonte potencial de dados de catálogo bruto. Nesta fase não há acoplamento com Bun/TypeScript dentro do AutoHunter.

## Contrato de ingestão mensal
Fluxo alvo:

`pipeline externo -> import/staging mensal AutoHunter -> tabelas locais -> resolver AutoHunter->FIPE -> fipe_prices -> score_v2`

Separação explícita:
1. **Catálogo bruto**: `fipe_catalog_entries`.
2. **Mapeamento AutoHunter -> FIPE**: fase futura (fora desta PR).
3. **Tabela final de consumo**: `fipe_prices` (sem alteração nesta PR).

## Riscos
- volume de linhas e tempo de upsert;
- ambiguidade de versões/modelos/ano;
- rate-limit e disponibilidade da fonte externa (fora do runtime principal);
- qualidade do match entre catálogo e veículos AutoHunter;
- operação em Raspberry (I/O e memória em carga mensal).

## Fases
1. ✅ Contrato de staging mensal implementado.
2. ✅ Adapter para output do pipeline externo implementado.
3. 🔜 Resolver AutoHunter→FIPE para produzir/atualizar `fipe_prices` (pendente).
4. Operação mensal com observabilidade e rollback seguro.

## Ajustes de segurança (PR 356)
- `fipe_catalog_entries` usa `identity_key` para upsert estável por (`reference_month`,`vehicle_type`,`source`,`identity_key`).
- Ordem de identidade: `fipe_code` -> `codes` -> fallback textual com diferenciador.
- `model_year` inválido não aborta carga: linha é `skipped_invalid`.
- Dry-run do importador **não** grava `fipe_sync_runs`; run é criado apenas em `--apply`.


## Fase 3 (parcial)
- Resolver diagnóstico AutoHunter → FIPE implementado (cálculo de candidatos + confiança).
- Atualização automática de `fipe_prices` permanece pendente e fora do escopo desta fase.

## Update 2026-05-26
- Resolver diagnóstico FIPE refinado para busca por tokens, melhor recall (ex.: Civic Si, Golf GTI), e scoring com explicabilidade ampliada.
- Critério de ambiguidade atualizado: high+high próximo (<15) => ambiguous; high com folga >=15 => matched; medium => ambiguous.
- Fluxo segue read-only nesta fase: sem escrita em fipe_prices, sem score_v2, sem chamadas externas.
- Próximo passo planejado: etapa dry-run/apply para persistir somente matches high não ambíguos.



## Status atualizado

- ✅ Planejamento dry-run AutoHunter→FIPE implementado via `/admin fipe plan`.
- ✅ Etapa continua read-only (sem escrita em `fipe_prices`).
- 🔜 Apply controlado (com confirmação explícita) permanece pendente em PR separada.


## Status do apply controlado

- ✅ Apply controlado implementado via `/admin fipe apply_plan`.
- ✅ Fluxo dry-run default com live explícito.
- ⏳ Scheduler mensal automático permanece pendente.
- ⏳ Updates de preços existentes permanecem desabilitados por padrão (guardados para flag futura).

- O apply controlado de FIPE agora possui trilha de auditoria persistente em `system_logs`, inclusive em dry-run.
- A trilha pode ser consultada via Telegram/admin com `/admin fipe apply_history [1-20]` (alias: `/admin fipe audit [1-20]`), somente leitura.
- Scheduler mensal continua pendente e fora deste escopo.


## Update — status operacional pós-apply

- ✅ Implementado status operacional pós-apply via `/admin fipe apply_status` (histórico dry/live/error + métricas agregadas + próximo passo).
- ✅ Leitura baseada em `system_logs` (`component=fipe_apply_plan`) e `fipe_prices` por competência.
- ✅ Fluxo continua sem scheduler mensal nesta etapa (fora do escopo).
