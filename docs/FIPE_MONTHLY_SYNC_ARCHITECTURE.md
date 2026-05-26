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

## Fases futuras
1. Contrato de staging mensal (esta PR).
2. Adapter para output do pipeline externo.
3. Resolver AutoHunter→FIPE para produzir/atualizar `fipe_prices`.
4. Operação mensal com observabilidade e rollback seguro.
