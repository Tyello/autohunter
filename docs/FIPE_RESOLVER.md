# FIPE Resolver (diagnóstico)

O resolver diagnóstico compara `CarListing` com `fipe_catalog_entries` (competência mensal local) e calcula candidatos.

## Score de confiança
- marca compatível: +25
- modelo compatível: +30
- ano compatível: +25
- combustível compatível: +10
- tokens de versão: +10
- penalidades: ano divergente (-30), divergência forte de marca/modelo (score muito baixo)

Labels:
- high: >= 80
- medium: 60..79
- low: < 60

## Status
- `matched`: melhor candidato high e com diferença suficiente para o segundo.
- `ambiguous`: candidatos próximos ou confiança insuficiente.
- `no_match`: nenhum candidato relevante.
- `insufficient_data`: listing sem make/model/year mínimo.

## Comandos admin
- `/admin fipe resolve <listing_id> [YYYY-MM]`
- `/admin fipe resolver_status [YYYY-MM] [limit<=200]`

## Guardrails desta fase
- Não grava `fipe_prices`.
- Não altera `score_v2`.
- Sem chamadas de API externa.

## Próximo passo
Permitir persistência controlada (dry-run/apply) apenas para matches high confiáveis.

## Update 2026-05-26
- Resolver diagnóstico FIPE refinado para busca por tokens, melhor recall (ex.: Civic Si, Golf GTI), e scoring com explicabilidade ampliada.
- Critério de ambiguidade atualizado: high+high próximo (<15) => ambiguous; high com folga >=15 => matched; medium => ambiguous.
- Fluxo segue read-only nesta fase: sem escrita em fipe_prices, sem score_v2, sem chamadas externas.
- Próximo passo planejado: etapa dry-run/apply para persistir somente matches high não ambíguos.



## Planejamento dry-run de `fipe_prices`

Novo comando admin:
- `/admin fipe plan`
- `/admin fipe plan 2026-05`
- `/admin fipe plan 2026-05 100`

Critérios para entrar em `planned_inserts` (read-only):
- resolver `status=matched`;
- `best_candidate` presente;
- `confidence_label=high`;
- `confidence_score >= min_confidence`;
- preço presente e maior que zero;
- listing com chave FIPE derivada de `listing_vehicle_keys`.

Motivos de skip:
- `insufficient_data`
- `no_match`
- `ambiguous`
- `below_confidence`
- `missing_price`
- `missing_vehicle_key`
- `already_exists`
- `already_planned`

Read-only: esta etapa não grava em `fipe_prices`, não altera `score_v2` e não chama API externa.


## Apply controlado do plano (/admin fipe apply_plan)

Comando admin para aplicar explicitamente os `planned_inserts` gerados pelo plano.

- `dry` é padrão (não grava nada).
- `live` precisa ser explícito.
- `limit` padrão 100, com cap em 500.
- Usa `min_confidence=80` e só considera matches high, não ambíguos e deduplicados no plano.
- `would_updates` são apenas informativos nesta fase (não aplicados por padrão).

Exemplos:
- `/admin fipe apply_plan`
- `/admin fipe apply_plan 2026-05 dry`
- `/admin fipe apply_plan 2026-05 live 100`

- `/admin fipe apply_plan` agora registra auditoria persistente em `system_logs` via sessão dedicada (dry-run e live).
- Dry-run também é auditável sem depender da transação principal de aplicação.
- O logging de auditoria não altera regra de aplicação (critérios, `allow_updates=False`, sem updates automáticos).

### Histórico persistente (read-only)

Para consultar a trilha recente sem abrir banco manualmente:

- `/admin fipe apply_history`
- `/admin fipe apply_history 10`
- `/admin fipe audit 10` (alias curto)

Regras:
- fonte: `system_logs` com `component="fipe_apply_plan"`;
- ordenação: `created_at desc`;
- limite padrão: `5`;
- cap máximo: `20`;
- saída compacta (UTC, modo dry-run/live/error, referência, contagens e erro resumido).
