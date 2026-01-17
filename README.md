# AutoHunter

Bot do Telegram + scheduler para monitorar anúncios de carros e notificar o usuário quando aparecerem novos anúncios que batem com suas wishlists.

## MVP (o que já existe)

- Busca manual via bot (`/buscar`)
- Wishlists monitoradas (até 3 por usuário)
- Alertas de novos anúncios (com foto/thumbnail + link)
- Preço FIPE (quando disponível) + score simples (abaixo/dentro/acima)

### Fontes (hoje)

- `mercadolivre` (Mercado Livre)
- `olx` (scraping leve)
- `chavesnamao` (SSR; scraping leve)

Fontes plugadas mas **desligadas/placeholder** (SPA/JS-heavy):

- `webmotors`
- `gogarage`

## Como rodar localmente

### 1) Pré-requisitos

- Python 3.11+ (recomendado)
- Postgres (ou Supabase)

### 2) Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Configure o `.env` (exemplo mínimo):

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/DB
TELEGRAM_BOT_TOKEN=...  # opcional se for rodar só API/scheduler

# Flags de fontes
ENABLE_OLX=true
ENABLE_CHAVESNAMAO=true
ENABLE_WEBMOTORS=false
ENABLE_GOGARAGE=false

# Scheduler
SCHED_ML_MINUTES=30
SCHED_OLX_MINUTES=30
SCHED_CHAVESNAMAO_MINUTES=60
SCHED_WEBMOTORS_MINUTES=180
SCHED_GOGARAGE_MINUTES=180
SCHED_SENDER_SECONDS=60

# Cooldowns (anti-ban)
OLX_COOLDOWN_MINUTES=60
CHAVESNAMAO_COOLDOWN_MINUTES=30
WEBMOTORS_COOLDOWN_MINUTES=180
GOGARAGE_COOLDOWN_MINUTES=180
```

> Regra: `campo_do_settings` -> `CAMPO_DO_SETTINGS` (upper-case). Ex.: `enable_olx` -> `ENABLE_OLX`.

### 3) Banco e migrations

Este projeto usa Alembic.

```bash
alembic upgrade head
```

### 4) Rodar componentes

**Bot (Telegram):**

```bash
python -m app.bot.run
```

**Scheduler separado (recomendado):**

```bash
python -m app.scheduler.cli
```

**API (FastAPI):**

```bash
uvicorn app.main:app --reload
```

Se quiser que a API também suba o scheduler no startup:

```env
ENABLE_SCHEDULER_IN_API=true
```

## Comandos do Bot (principais)

- `/buscar <termos>`: busca manual (ingere resultados no banco e devolve os mais recentes)
- `/wishlist`: cria/lista wishlists
- `/alertas`: mostra alertas recentes
- `/plan`, `/upgrade`, `/setplan`, `/setlimit`: controle de limites/planos (MVP)

## Arquitetura (visão rápida)

### Componentes

- `app/bot/*`: handlers do Telegram
- `app/scheduler/*`: jobs (scrape -> ingest -> match -> notify)
- `app/scrapers/*`: scrapers por fonte (HTTP/HTML)
- `app/services/*`: regras de negócio (ingest, dedupe, limites, matching, logs)
- `app/models/*`: SQLAlchemy models

### Fluxo de dados

1) Usuário cria wishlist (query) no bot
2) Scheduler roda periodicamente por fonte
3) Para cada wishlist ativa:
   - monta a URL de busca da fonte
   - faz scrape
   - ingere anúncios em `car_listings` (dedupe por `source + external_id`)
   - faz match e cria `notifications`
4) Sender job envia notificações pendentes no Telegram

## Framework de Fontes (Pluginável)

Agora as fontes são plugins registrados em `app/sources`.

### Onde ficam

- `app/sources/types.py`: contrato do plugin (`SourcePlugin`)
- `app/sources/registry.py`: registry + helpers
- `app/sources/builtins.py`: plugins padrão (ML/OLX/Chaves...)

### Por que isso importa

Sem isso, cada nova fonte vira:
- mais `if/elif` no scheduler
- mais import e boilerplate no manual search
- mais risco de esquecer de adicionar em defaults

Com o registry:
- adicionou plugin -> scheduler pega automaticamente
- defaults de wishlist passam a ser “todas as fontes implementadas”

### Como adicionar uma nova fonte (exemplo)

1) Crie um scraper em `app/scrapers/minhafonte.py` que retorne `list[dict]` no formato do ingest:

```python
def scrape_minhafonte(url: str) -> list[dict]:
    return [
        {
            "source": "minhafonte",
            "external_id": "abc123",
            "title": "Civic 2019 Touring",
            "url": "https://...",
            "thumbnail_url": "https://...",
            "price": 95000,
            "currency": "BRL",
            "location": "SP",
        }
    ]
```

2) Crie um builder de URL em `app/services/search_urls_service.py` (ou direto no plugin).

3) Registre o plugin em `app/sources/builtins.py`:

```python
from app.services.search_urls_service import minhafonte_url
from app.scrapers.minhafonte import scrape_minhafonte

register_source(
    SourcePlugin(
        name="minhafonte",
        build_url=minhafonte_url,
        scrape=scrape_minhafonte,
        enabled_setting="enable_minhafonte",
        sched_minutes_setting="sched_minhafonte_minutes",
        cooldown_minutes_setting="minhafonte_cooldown_minutes",
    )
)
```

4) Adicione os campos no `app/core/settings.py` + `.env`.

Pronto: o scheduler já agenda automaticamente e a busca manual já passa a ingerir.

## Observações importantes (anti-ban)

- Respeite `cooldown_minutes` e não rode fontes agressivas a cada 10s.
- Trate `FetchBlocked` e registre logs (já existe infra em `system_logs`).
- Para fontes SPA/Cloudflare/Turnstile (ex: Webmotors), **não** vale insistir com `requests+bs4`.

## Roadmap sugerido

- Padronizar métricas por fonte (tempo de scrape, taxa de bloqueio, itens/execução)
- Cache + backoff por fonte
- Headless isolado como microserviço (se realmente for implementar SPA)

---

Docs adicionais:

- `docs/fontes_novas.md`