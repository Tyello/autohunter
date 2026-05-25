# FIPE — carga operacional inicial (controlada)

## Objetivo

Operacionalizar a primeira carga real de FIPE sem alterar score/ranking: preparar CSV com `vehicle_key` faltante, validar via dry-run e aplicar com confirmação explícita.

> Este documento é um guia operacional. Não versione cargas reais grandes no repositório.

## Formato aceito do CSV

Colunas mínimas aceitas pelo importador:

- `vehicle_key`
- `fipe_price`

Colunas opcionais:

- `reference_month` (`YYYY-MM`)
- `currency` (default `BRL`)

Template pequeno de referência:

- `docs/examples/fipe_prices_template.csv`

## 1) Levantar cobertura e ausências

No bot admin:

- `/admin fipe coverage`
- `/admin fipe coverage 2026-05 50`

Use o bloco **Top ausentes** como lista de chaves para preencher o CSV.

## 2) Preencher CSV manualmente

1. Copie as `vehicle_key` mais relevantes (maior `listings_count`).
2. Preencha `fipe_price` com fonte confiável.
3. Use uma única competência por rodada (`reference_month`, ex.: `2026-05`).
4. Mantenha `currency=BRL` (salvo exceção operacional explícita).

Opcional: export read-only das chaves faltantes para acelerar preenchimento:

```bash
python scripts/export_missing_fipe_keys.py --reference-month 2026-05 --output /tmp/missing_fipe_keys.csv
```

## 3) Rodar dry-run (obrigatório)

```bash
python scripts/import_fipe_prices.py --file docs/examples/fipe_prices_template.csv --reference-month 2026-05
```

Para arquivo real local:

```bash
python scripts/import_fipe_prices.py --file caminho/real/fipe_prices.csv --reference-month 2026-05
```

## 4) Rodar apply (com confirmação)

```bash
python scripts/import_fipe_prices.py --file caminho/real/fipe_prices.csv --reference-month 2026-05 --apply
```

## 5) Validar pós-carga

No bot admin:

- `/admin fipe coverage`
- `/admin fipe coverage 2026-05 50`

Confirme avanço de cobertura (`vehicle_keys_covered` e `%`) e redução de `Top ausentes`.

## Reverter/ajustar dado incorreto

- Corrija a linha no CSV (mesma `vehicle_key` + mesma `reference_month`) e rode novo `--apply`.
- O importador faz `upsert`: atualiza preço/moeda quando o par (`vehicle_key`, `reference_month`) já existe.
- Evite rodadas sem dry-run prévio.

## Cuidados com fonte de dados

- Validar origem antes da carga (fonte confiável e auditável).
- Não usar scraping/API externa nesta rotina.
- Não alterar score_v2/ranking nesta operação; apenas aumentar cobertura de `fipe_prices`.
