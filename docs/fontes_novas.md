# Novas fontes de anúncios (Roadmap)

## O que já está plugado neste commit

- **Chaves na Mão (SSR)**: scraping leve por HTML.
  - Status: **ON por padrão** (`enable_chavesnamao=true`).
  - Scheduler: `sched_chavesnamao_minutes`.

- **Webmotors (SPA/JS-heavy)**: **placeholder** (não implementado).
  - Status: **OFF por padrão** (`enable_webmotors=false`).
  - Motivo: a página de estoque carrega os anúncios via JS/endpoints internos; `requests + bs4` não enxerga os itens.
  - Caminhos recomendados:
    1) **Integração oficial (B2B)** via Portal de Developers Webmotors (APIs de estoque/catálogo/leads).
    2) **Headless/anti-bot** (Playwright) ou serviço third-party (Apify/BrightData/ScrapingBee) só se você aceitar custo/risco.

- **GoGarage (SPA/JS-heavy)**: **placeholder** (não implementado).
  - Status: **OFF por padrão** (`enable_gogarage=false`).
  - Motivo: carrega anúncios via JS.

## Como ligar/desligar

No seu `.env`:

```env
ENABLE_OLX=true
ENABLE_CHAVESNAMAO=true
ENABLE_WEBMOTORS=false
ENABLE_GOGARAGE=false

SCHED_CHAVESNAMAO_MINUTES=60
SCHED_WEBMOTORS_MINUTES=180
SCHED_GOGARAGE_MINUTES=180
```

> Observação: os nomes das env vars seguem a regra do pydantic-settings (upper-case do campo). Ex: `sched_chavesnamao_minutes` -> `SCHED_CHAVESNAMAO_MINUTES`.

## Próximo passo técnico (se for implementar Webmotors/GoGarage)

1. Descobrir endpoint de listagem (Network tab) e autenticação/headers.
2. Implementar scraper via `httpx` (se for JSON) ou Playwright (se for JS + Cloudflare/Turnstile).
3. Integrar no mesmo contrato: `scrape_<source>() -> list[dict]` com chaves:
   - source, external_id, title, url, thumbnail_url, price, currency, location
