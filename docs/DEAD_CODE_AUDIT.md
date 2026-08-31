# Auditoria de Código Não Utilizado (READ-ONLY)

**Status:** Análise apenas. Nenhum código, migration ou config foi alterado ou removido.
**Data:** 2026-08-31

---

## Metodologia

1. `vulture` (detector estático de código morto para Python) rodado contra `app/` e `migrations/`
   com `--min-confidence 60`, tratado como **hipótese**, não veredito.
2. Cada candidato do vulture foi verificado manualmente: `grep -rn` pelo nome do símbolo em todo
   `app/`, `migrations/`, `tests/` — contagem de ocorrências totais (definição incluída). Contagem
   `1` = símbolo não referenciado em lugar nenhum além da própria definição.
3. Verificação adicional, fora do alcance do vulture (que só cobre Python):
   - Arquivos/módulos inteiros nunca importados.
   - Migrations fora da cadeia do Alembic (`migrations/versions/`).
   - Arquivos de backup/dump versionados por engano.
   - Múltiplos heads no Alembic.
4. `vulture` foi instalado só no venv local para esta análise; **não foi adicionado a
   `requirements*.txt`** — pode ser desinstalado (`pip uninstall -y vulture`) sem impacto.

Falsos positivos categóricos do vulture neste repo (excluídos do relatório abaixo sem verificação
individual, por já terem mecanismo de uso confirmado em auditorias anteriores desta sessão):
handlers do bot registrados por `CallbackQueryHandler`/`CommandHandler` em `app/bot/run.py`,
rotas FastAPI decoradas com `@router.get/post` (confirmado: todos os routers de
`app/web/routes_*.py` estão montados via `app.include_router` em `app/main.py:40-42`), fixtures de
`conftest.py`, colunas de modelos SQLAlchemy, e todo o conteúdo de `migrations/versions/*.py`
(nunca é "chamado", é executado pelo runtime do Alembic via cadeia de revisões).

---

## Alta confiança — seguro remover

### 1. Migrations órfãs fora da cadeia do Alembic

- `migrations/fase4_001_auction_events.py`
- `migrations/fase4_002_auction_lots.py`

**Evidência:** ficam soltos em `migrations/` (não em `migrations/versions/`), e o
`script_location`/`version_locations` do `alembic.ini` só escaneia `migrations/versions/` (linha
comentada confirma o default). `grep -rn "fase4_001\|fase4_002"` no repo inteiro só retorna
ocorrências dentro dos próprios dois arquivos — nenhuma outra parte do código, docs ou scripts os
referencia. A migration real e ativa que cobre o mesmo schema (auction events/lots) já existe em
`migrations/versions/aa9d2f11c123_add_auction_events_and_lots_official.py` (nome sugere que estes
dois arquivos soltos são o rascunho anterior, substituído pela versão "official"). `alembic heads`
confirma um único head (`d3e5f7a9b1c2`), então não há branch órfão dependendo deles.
**Recomendação:** remover os dois arquivos.

### 2. `app/notifications/base.py` + `app/notifications/telegram.py` — abstração morta

- `BaseNotifier`, `TelegramNotifier`, `NotificationChannel`, `render_template` (base.py:320).

**Evidência:** `grep -rn "BaseNotifier\|TelegramNotifier\|\.notify("` fora do próprio pacote
`app/notifications/` não retorna nada. As notificações reais do bot são enviadas diretamente via
`app/bot/sender.py` (chamadas a `bot.send_message`/API do python-telegram-bot), não através desta
hierarquia de classes. `NotificationChannel` (enum) também só é referenciado dentro do próprio
arquivo. Parece uma abstração de canal de notificação (preparo para múltiplos canais: email, push,
etc.) que nunca chegou a ser adotada pelo fluxo real.
**Atenção:** o pacote `app/notifications/` também contém `telegram_formatter.py` e
`weekly_wishlist_digest_formatter.py`, que **são usados** (`app/bot/sender.py`,
`app/bot/handlers_buscar_agora.py`, testes) — não tocar nesses dois.
**Recomendação:** remover `app/notifications/base.py` e `app/notifications/telegram.py` (arquivos
inteiros — nenhuma outra classe/função neles é usada).

### 3. `app/scheduler/scraper_adapter.py` — arquivo inteiro nunca importado

**Evidência:** `grep -rn "scraper_adapter"` fora do próprio arquivo não retorna nada — nenhum
import em `app/`, `tests/` ou `migrations/`. 204 linhas, incluindo `scrape_source_smart` (scraping
"inteligente" com fallback pra legacy) e demais helpers do arquivo.
**Recomendação:** remover o arquivo inteiro.

### 4. `app/scheduler/market_stats_job.py` — job nunca agendado

**Evidência:** define `job_compute_market_stats_daily`. `grep -rni "market_stats"` em
`app/scheduler/run.py` (onde todo `sched.add_job(...)` do projeto vive) e `app/main.py` não
retorna nada — o job nunca é registrado no APScheduler nem chamado manualmente em lugar nenhum.
78 linhas.
**Recomendação:** remover o arquivo inteiro (ou, se a intenção é ativá-lo futuramente, registrar
com `sched.add_job` — decisão de produto, não deste doc).

### 5. `app/services/mercadopago_webhook_service.py:24` — `InvalidSignatureError` nunca levantada

**Evidência:** `grep -rn "InvalidSignatureError"` no repo inteiro só retorna a linha da própria
definição da classe — não é levantada (`raise`) nem capturada (`except`) em lugar nenhum, nem no
próprio arquivo.
**Recomendação:** remover a classe.

### 6. `app/services/source_configs_service.py:109` — `UpdateResult` nunca usada

**Evidência:** dataclass definida, `grep -rn "UpdateResult"` só bate na própria definição — não é
usada como tipo de retorno em lugar nenhum (a função vizinha aparentemente retorna outro tipo).
**Recomendação:** remover.

### 7. `app/scrapers/chavesnamao.py:21` — `ChavesNaMaoItem` nunca instanciada

**Evidência:** dataclass definida no módulo, `grep -n "ChavesNaMaoItem" app/scrapers/chavesnamao.py`
só retorna a própria linha de definição — nem o próprio arquivo a instancia. As funções reais desse
arquivo (`scrape_chavesnamao`, `build_chavesnamao_search_url`) **são usadas** por
`app/sources/builtins.py` — não remover o arquivo, só a classe morta dentro dele.
**Recomendação:** remover só a classe `ChavesNaMaoItem`.

### 8. Funções privadas (`_prefixo`) sem nenhuma referência, nem interna

Cada uma abaixo: `grep -rn "\bnome\b"` no repo inteiro só bate na própria linha de definição —
como são privadas (prefixo `_`), não podem ser chamadas de fora do módulo, então "só a definição"
prova que estão mortas mesmo dentro do próprio arquivo.

| Símbolo | Local |
|---|---|
| `_clean_location` | `app/bot/sender.py:135` |
| `_score_from_text` | `app/bot/sender.py:180` |
| `_extract_slot_from_message` | `app/bot/handlers_wishlist_ui.py:443` |
| `_get_active_subscription_and_plan` | `app/bot/handlers.py:160` |
| `_index_by` | `app/sources/compare.py:15` |
| `_is_tiny_image` | `app/scrapers/icarros.py:248` |
| `_truthy` | `app/services/system_logs_service.py:15` |

**Recomendação:** remover as 7 funções.

---

## Confiança média — remover com revisão

Funções públicas de serviço, sem nenhum caller em `app/`, `migrations/` ou `tests/`, mas que podem
ser utilitários pensados para um comando admin futuro ainda não conectado (padrão já visto neste
repo — ver ressalva do item "Falsos positivos" sobre `manual_search`). Antes de remover, vale um
`git log -p` rápido em cada um para confirmar que não é código recém-adicionado para uma feature em
andamento.

| Símbolo | Local | Observação |
|---|---|---|
| `clear_backoff` | `app/services/source_backoff_service.py:179` | Par de `mark_success/mark_error/...`, mas sem call site (nem em admin commands) |
| `create_queued_if_absent` | `app/services/notifications_service.py:75` | |
| `mark_failed_reason` | `app/services/notifications_service.py:42` | |
| `list_source_config_snapshots` | `app/services/source_configs_service.py:98` | |
| `get_tracking_capacity_snapshot` | `app/services/wishlist_tracking_service.py:360` | |
| `premium_upgrade_cta` | `app/services/plan_capabilities.py:59` | |
| `get_fipe_price` | `app/services/fipe_service.py:9` | Confirmar se não é a função esperada pelo job FIPE mensal (spec `001-fipe-monthly-job-fix`) antes de remover |
| `get_source_proxy_server` | `app/services/source_proxy_service.py:11` | |
| `get_source_rate_limit_seconds` | `app/services/source_rate_limit_service.py:11` | |
| `admin_alerts_diagnostic_snapshot` | `app/services/admin_alerts_service.py:36` | |
| `can_send_more_today` | `app/services/limits_service.py:98` | Nome sugere guard-rail de limite de envio — checar se não é chamada indiretamente via nome de string em algum lugar |

Além disso, ~35 outros itens do vulture (funções/atributos com confiança 60%, 1 única ocorrência)
não foram individualmente detalhados neste documento por limite de tempo desta análise — a lista
completa e reprodutível está em `/tmp/candidate_counts.txt` (gerado nesta sessão, não versionado)
e pode ser regerada com:

```bash
.venv/Scripts/python.exe -m vulture app migrations --min-confidence 60
```

Antes de agir sobre qualquer um desses, repita o passo de verificação manual (grep pelo nome no
repo inteiro) descrito na metodologia.

---

## Falsos positivos identificados (não remover)

- **`app/scrapers/auctions/generic_auction.py` (`GenericAuctionScraper`)** — vulture aponta 0 usos,
  mas o próprio docstring da classe diz: *"NOTA: Este é um template. Para sites reais, você
  precisará: 1. Descobrir os seletores CSS..."* — é um scaffold intencional para novos scrapers de
  leilão, não código morto esquecido. Não remover; se quiser, mover para `docs/` como referência.
- **Rotas de `app/web/routes_auth_facebook.py`, `routes_fb_agent.py`,
  `routes_mercadopago_webhook.py`** — vulture marca `auth_facebook_start`, `auth_facebook_complete`,
  `auth_facebook_status`, `fb_agent_bootstrap`, `fb_agent_ws`, `mercadopago_webhook` como não
  usados. Confirmado falso positivo: os três routers estão montados em `app/main.py:40-42` via
  `app.include_router(...)` — são endpoints HTTP reais, chamados por requisição, não por import
  direto no código Python.
- **`quick_search_conversation` / `manual_search`** — aparecem com poucas referências no grep, mas
  já foi confirmado em `docs/DIAGNOSTICO_BUSCAR_AGORA.md` (2026-08-30) que são o fluxo ativo do
  botão de menu "Buscar agora", mantido deliberadamente por decisão da spec `018-buscar-agora-bot-flow`
  (REQ-006). Não remover.
- **Duas implementações paralelas de scraper para ChavesNaMao** — `app/scrapers/chavesnamao.py`
  (função, usada por `app/sources/builtins.py`) e `app/scrapers/sources/chavesnamao.py`
  (`ChavesNaMaoScraper`, classe, registrada em `app/scrapers/sources/__init__.py:68`). Não é
  código morto (ambas parecem ter callers), mas é uma duplicação estrutural que vale investigação
  separada — **fora do escopo desta auditoria de "morto vs. vivo"**, é uma pergunta de arquitetura
  (qual dos dois registries está realmente ativo em produção?).
- **Migrations em `migrations/versions/*.py` em geral** — vulture não foi rodado sobre elas com a
  intenção de sinalizar remoção; todas fazem parte da cadeia de revisões do Alembic e são
  necessárias mesmo sem "chamada" direta no código Python.
- **Colunas/atributos de modelos SQLAlchemy** (`app/models/*.py`, ex.:
  `wishlist_listing_activity.py:43,55,60`, `source_state.py:45`, `subscription.py:30,32`) — usados
  via ORM (SELECT/INSERT automáticos), não por referência direta no código; vulture não entende
  esse padrão. Não remover.

---

## Plano consolidado (não executado — aguardando aprovação)

```bash
# 1. Migrations órfãs fora da cadeia do Alembic
git rm migrations/fase4_001_auction_events.py migrations/fase4_002_auction_lots.py

# 2. Abstração de notificação morta (manter telegram_formatter.py e weekly_wishlist_digest_formatter.py)
git rm app/notifications/base.py app/notifications/telegram.py

# 3. Adapter de scraper nunca importado
git rm app/scheduler/scraper_adapter.py

# 4. Job de market stats nunca agendado
git rm app/scheduler/market_stats_job.py

# 5-8. Edições pontuais (remover só o símbolo, não o arquivo):
#   - app/services/mercadopago_webhook_service.py: remover classe InvalidSignatureError
#   - app/services/source_configs_service.py: remover classe UpdateResult
#   - app/scrapers/chavesnamao.py: remover classe ChavesNaMaoItem
#   - app/bot/sender.py: remover _clean_location, _score_from_text
#   - app/bot/handlers_wishlist_ui.py: remover _extract_slot_from_message
#   - app/bot/handlers.py: remover _get_active_subscription_and_plan
#   - app/sources/compare.py: remover _index_by
#   - app/scrapers/icarros.py: remover _is_tiny_image
#   - app/services/system_logs_service.py: remover _truthy
```

Depois de qualquer remoção: rodar a suíte de testes completa (`pytest`) e `vulture` de novo para
confirmar que nada quebrou e que os símbolos remanescentes de "confiança média" ainda precisam de
decisão humana.
