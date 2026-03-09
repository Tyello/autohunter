# Source Audit Baseline (Item 4)

## Sources atuais e implementação

| Source | Implementação | Modo |
|---|---|---|
| mercadolivre | `app/scrapers/mercadolivre.py` | listagem (sem detalhe dedicado) |
| olx | `app/scrapers/olx.py` | listagem (API/HTML, fallback browser) |
| chavesnamao | `app/scrapers/chavesnamao.py` | listagem + detalhe opcional |
| webmotors | `app/scrapers/webmotors.py` | listagem (browser/XHR) |
| gogarage | `app/scrapers/gogarage.py` | listagem + detalhe com orçamento |
| icarros | `app/scrapers/icarros.py` | listagem + detalhe/enrichment |
| mobiauto | `app/scrapers/mobiauto.py` | listagem + detalhe/enrichment |
| kavak | `app/scrapers/kavak.py` | listagem |
| facebook_marketplace | `app/scrapers/facebook_marketplace.py` | listagem |
| turboclass | `app/scrapers/turboclass.py` | listagem |
| turboclass_vendidos | `app/scrapers/turboclass.py` (plugin dedicado) | listagem vendidas |

## Pipeline observado

- Busca/listagem: scraper por fonte com saída em dict/listing.
- Detalhe/enrichment: presente em `icarros`, `mobiauto`, `gogarage` e opcional em `chavesnamao`.
- Normalização: `finalize_listings` + adapters + `normalize_ad`/`enforce_ad_contract`.
- Contract/quality flags: `app/sources/ad_quality.py`.
- Persistência: `ingest_listings_stats` + `insert_ignore_duplicates_return_ids`.
- Deduplicação: `app/scrapers/contract.py` e repo por `(source, external_id)`.
- Mensagem/notificação: `app/notifications/telegram_formatter.py` + fila em `app/services/notifications_queue_service.py`.

## Matriz inicial (baseline por código)

Source | price | title | location | year | km | gearbox | images | thumbnail_url | source_listing_id | detail_needed | gaps
------ | ----- | ----- | -------- | ---- | -- | ------- | ------ | ------------- | ----------------- | ------------ | ----
mercadolivre | ok | ok | parcial | parcial | parcial | gap | parcial | ok | ok | parcial | poucos campos técnicos
olx | ok | ok | ok | parcial | parcial | parcial | parcial | ok | ok | parcial | variação por payload/API
chavesnamao | parcial | ok | parcial | parcial | parcial | gap | parcial | parcial | ok | sim | enriquecimento caro
webmotors | ok | ok | parcial | parcial | parcial | parcial | parcial | parcial | ok | parcial | anti-bot e payload variável
gogarage | parcial | parcial | parcial | parcial | parcial | gap | parcial | parcial | ok | sim | depende de details budget
icarros | ok | ok | ok | ok | ok | parcial | parcial | ok | ok | sim | alguns campos somem no merge
mobiauto | ok | ok | ok | parcial | parcial | parcial | parcial | parcial | ok | sim | enriquecimento necessário
kavak | parcial | ok | parcial | parcial | parcial | parcial | parcial | parcial | ok | parcial | campos não padronizados
facebook_marketplace | parcial | parcial | parcial | gap | gap | gap | parcial | parcial | ok | não | dados automotivos limitados
turboclass | parcial | ok | parcial | parcial | parcial | gap | parcial | parcial | ok | não | feed heterogêneo
turboclass_vendidos | gap | parcial | gap | gap | gap | gap | gap | gap | ok | não | foco em vendido

## Proposta normalizeAd final (objetiva)

- Obrigatórios globais: `source`, `source_listing_id`, `url`, `title`, `price`.
- Opcionais desejáveis: `location`, `year`, `km`, `thumbnail_url`, `images_count`, `make`, `model`.
- Dependentes de detalhe: `description`, `seller_type`, `risk/provenance signals`, `gearbox` (em parte das fontes).
- Flags críticas ao faltar: `missing_url`, `missing_source_listing_id`, `missing_price`, `empty_title`.
- Campos **não** exigir missing global (evitar falso positivo): `gearbox`, `seller_type`, `description`, `risk_signals`.

## Como rodar auditoria local

1. Execute pipeline normalmente com instrumentação habilitada.
2. Artefatos de captura condicional vão para `artifacts/source_audit_candidates/<source>/`.
3. Gere matriz/relatório:

```bash
python scripts/run_source_audit.py --input artifacts/source_audit_samples.json --out artifacts/source_audit_reports
```

Entrada aceita: JSON array ou JSONL com linhas por `(source, field, present_in_listing, ...)`.
