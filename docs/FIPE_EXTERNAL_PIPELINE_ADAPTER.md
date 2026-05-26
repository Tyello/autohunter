# FIPE External Pipeline Adapter

Este adapter permite importar output de pipeline externo (ex.: `caiopizzol/fipe-data-pipeline`) para staging local `fipe_catalog_entries`, sem Bun/TypeScript no runtime AutoHunter.

## Formato de entrada esperado

- Arquivo JSON `list[dict]` ou CSV com colunas equivalentes.
- Campos normalizados alvo:
  - `reference_month`
  - `vehicle_type`
  - `brand_code`
  - `brand_name`
  - `model_code`
  - `model_name` (obrigatório)
  - `year_code`
  - `model_year`
  - `fuel`
  - `fipe_code`
  - `price` (obrigatório)
  - `currency`
  - `raw_payload`

## Aliases aceitos

- marca: `marca`, `brand`, `brand_name`, `nome_marca`
- código marca: `codigo_marca`, `brand_code`, `marca_codigo`
- modelo: `modelo`, `model`, `model_name`, `nome_modelo`
- código modelo: `codigo_modelo`, `model_code`, `modelo_codigo`
- ano/model year: `ano`, `year`, `ano_modelo`, `model_year`
- código ano: `codigo_ano`, `year_code`, `ano_codigo`
- combustível: `combustivel`, `fuel`
- FIPE: `codigo_fipe`, `fipe_code`
- preço: `valor`, `price`, `preco`, `fipe_price`
- mês referência: `mes_referencia`, `reference_month`
- tipo veículo: `tipo_veiculo`, `vehicle_type`

Defaults:
- `vehicle_type=car`
- `currency=BRL`
- `reference_month` vem do CLI quando ausente na linha.

## Conversões

- Preço BRL textual (`R$ 95.000,00`) é convertido para número decimal aceito no upsert.
- `model_year` vira inteiro quando possível.
- Linha original sempre preservada em `raw_payload`.

## Comandos

Dry-run (default):

```bash
python scripts/import_fipe_catalog_entries.py --file /tmp/fipe_pipeline_output.json --reference-month 2026-05 --format external-pipeline
```

Apply:

```bash
python scripts/import_fipe_catalog_entries.py --file /tmp/fipe_pipeline_output.json --reference-month 2026-05 --format external-pipeline --apply
```

## Limitações conhecidas

- Não chama API FIPE no runtime.
- Não resolve AutoHunter → FIPE nesta fase.
- Não altera `fipe_prices` nem `score_v2`.
