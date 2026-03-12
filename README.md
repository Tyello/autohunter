# AutoHunter

Bot do Telegram + scheduler para monitorar anúncios de carros em múltiplas fontes e avisar quando aparecer algo que bate com as wishlists do usuário.

## Visão rápida

**O que o projeto entrega hoje**

- Busca manual via bot (`/buscar`)
- Wishlists monitoradas (até 3 por usuário)
- Alertas com foto/thumbnail + link
- Preço FIPE (quando disponível) + score simples (abaixo/dentro/acima)

**Fontes ativas**

- `mercadolivre` (Mercado Livre)
- `olx` (scraping leve)
- `chavesnamao` (SSR; scraping leve)

**Fontes plugadas, porém desligadas (SPA/JS-heavy)**

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

# para testes
pip install -r requirements.dev.txt
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

Este projeto usa Alembic:

```bash
alembic upgrade head
```

Os planos base (`free`, `pro`, `ultra`) são garantidos por bootstrap automático no código
quando um usuário novo é criado. Mesmo assim, mantenha as migrations em dia para garantir
que a tabela `plans` exista no mesmo banco apontado por `DATABASE_URL`.

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

## Testes

Os testes são **offline** (sem rede/Playwright) e usam SQLite automaticamente:

```bash
pytest
```

Cobertura principal:

- Smoke tests da API (`/health`, `/db-check`, `/listings`, `/admin/health`)
- Matching “anti-falso-positivo” (ex.: `civic si` não casa com `civic 2015`)
- Sender de notifications respeitando limite diário (e aviso 1x por dia)
- Parsing/normalização de Mercado Livre e extração de `__NEXT_DATA__` da OLX

### Contract tests (anti-breaking change)

Além dos testes funcionais, existe um **contrato** para evitar que mudanças quebrem consumidores:

- Snapshot do OpenAPI (`tests/contracts/openapi_snapshot.json`)
- Contrato de formato da mensagem do Telegram (linhas e URL limpa)

Para atualizar o snapshot do OpenAPI **intencionalmente**:

```bash
UPDATE_CONTRACT=1 pytest -k openapi_contract_snapshot
```

### CI (GitHub Actions)

Workflow minimalista em `.github/workflows/ci.yml`:

- roda em `push` e `pull_request`
- instala dependências + `requirements.dev.txt`
- executa `pytest`

## Comandos principais do bot

- `/buscar <termos>`: busca manual (ingere resultados no banco e devolve os mais recentes)
- `/wishlist`: cria/lista wishlists
- `/alertas`: mostra alertas recentes
- `/plan`, `/upgrade`, `/setplan`, `/setlimit`: controle de limites/planos (MVP)

## Arquitetura (resumo)

### Componentes

- `app/bot/*`: handlers do Telegram
- `app/scheduler/*`: jobs (scrape -> ingest -> match -> notify)
- `app/scrapers/*`: scrapers por fonte (HTTP/HTML)
- `app/services/*`: regras de negócio (ingest, dedupe, limites, matching, logs)
- `app/models/*`: SQLAlchemy models

### Fluxo de dados

1) Usuário cria wishlist (query)
2) Scheduler roda periodicamente por fonte
3) Para cada wishlist ativa:
   - monta a URL de busca da fonte
   - faz scrape
   - ingere anúncios em `car_listings` (dedupe por `source + external_id`)
   - faz match e cria `notifications`
4) Sender job envia notificações pendentes no Telegram

## Framework de fontes (pluginável)

As fontes são plugins registrados em `app/sources`.

### Onde ficam

- `app/sources/types.py`: contrato do plugin (`SourcePlugin`)
- `app/sources/registry.py`: registry + helpers
- `app/sources/builtins.py`: plugins padrão (ML/OLX/Chaves...)

### Por que isso importa

Sem isso, cada nova fonte vira:

- mais `if/elif` no scheduler
- mais import e boilerplate no manual search
- mais risco de esquecer de adicionar defaults

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

## Boas práticas (anti-ban)

- Respeite `cooldown_minutes` e não rode fontes agressivas a cada 10s.
- Trate `FetchBlocked` e registre logs (já existe infra em `system_logs`).
- Para fontes SPA/Cloudflare/Turnstile (ex.: Webmotors), **não** vale insistir com `requests + bs4`.

## Roadmap sugerido

- Padronizar métricas por fonte (tempo de scrape, taxa de bloqueio, itens/execução)
- Cache + backoff por fonte
- Headless isolado como microserviço (se realmente for implementar SPA)

## Documentações adicionais

- `docs/projeto.md`: visão geral e arquitetura
- `docs/matching_guide.md`: guia de matching e semântica
- `docs/fontes_novas.md`: status das fontes e roadmap
- `docs/raspberry_pi_3.md`: deploy no Raspberry Pi 3
- `docs/security.md`: segurança de secrets
- `docs/pricing.md`: proposta de planos e preços
- `docs/launch_plan.md`: plano de lançamento
- `docs/market_opportunities.md`: oportunidades de mercado
