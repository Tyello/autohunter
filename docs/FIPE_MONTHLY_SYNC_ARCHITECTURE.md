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
