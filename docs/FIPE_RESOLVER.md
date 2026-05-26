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
