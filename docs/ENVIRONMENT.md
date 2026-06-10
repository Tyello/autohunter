# Garagem Alvo / AutoHunter — Ambiente e configuração

Atualizado em: 2026-06-10.

Este documento descreve como pensar a configuração do AutoHunter para desenvolvimento, operação local, Raspberry Pi, mini PC ou VPS pequena.

A regra principal: **o estado operacional efetivo é DB-driven**. O `.env` é fallback, bootstrap e kill switch. Para sources e knobs operacionais, sempre conferir também `source_configs`, `source_states` e `AppKV`.

## 1. Princípios

- Nunca commitar segredos reais.
- Preferir variáveis explícitas e documentadas.
- Usar `.env.example` como referência sanitizada quando disponível.
- Não tratar `.env` como painel operacional permanente.
- Não habilitar source experimental para usuário final só porque existe variável configurada.
- Não aumentar browser/Playwright/concurrency sem validar memória e CPU no ambiente real.

## 2. Grupos de configuração

### 2.1 Aplicação

Configurações típicas:

```env
APP_ENV=development
APP_DEBUG=false
LOG_LEVEL=INFO
TIMEZONE=America/Sao_Paulo
```

Uso esperado:

- diferenciar ambiente local, staging/beta e produção;
- controlar verbosidade de log;
- manter timestamps operacionais previsíveis.

### 2.2 Banco de dados

Configurações típicas:

```env
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/dbname
```

Regras:

- PostgreSQL/Supabase é o banco operacional oficial.
- SQLite pode aparecer em testes locais, mas não deve ser assumido como produção.
- Antes de deploy, validar migrations.

Comandos úteis:

```bash
alembic heads
alembic current
alembic upgrade head
```

### 2.3 Telegram

Configurações típicas:

```env
TELEGRAM_BOT_TOKEN=replace-me
TELEGRAM_ADMIN_CHAT_ID=replace-me
```

Regras:

- `TELEGRAM_BOT_TOKEN` é segredo crítico.
- `TELEGRAM_ADMIN_CHAT_ID` precisa proteger comandos sensíveis.
- Nunca expor token em log, erro, print ou documentação.

Validações mínimas:

```bash
python -m app.bot.run
```

Depois validar no Telegram:

- `/start`
- `/menu`
- `/buscar`
- criação de busca/wishlist
- `/plan`
- `/upgrade`
- comandos admin apenas no chat autorizado

### 2.4 Scheduler e workers

Configurações possíveis variam conforme o código atual. Conferir settings reais antes de alterar.

Conceitos importantes:

- ticks devem enfileirar jobs, não executar scrape pesado diretamente;
- workers HTTP e browser devem ter concorrência controlada;
- browser deve ser exceção operacional, não padrão agressivo;
- sender precisa drenar `notifications` sem atraso crescente.

Validação mínima:

```bash
python -m app.scheduler.run
```

Sinais de problema:

- `scrape_jobs` acumulando;
- jobs presos em `running`;
- muitos `failed` consecutivos;
- sender sem drenar;
- processos browser acumulados;
- RAM em pressão contínua.

### 2.5 Sources tradicionais

A existência de scraper/plugin no código não significa source ativa para usuário final.

Fonte de verdade operacional:

- `source_configs.is_enabled`
- `source_configs.user_eligible`
- `source_configs.status`
- `source_configs.operational_role` quando aplicável em `extra`
- `source_states.last_status`
- `source_states.next_allowed_at`
- backoff e falhas consecutivas

Configurações comuns podem incluir:

```env
SOURCE_PROXY_OLX=
SOURCE_PROXY_WEBMOTORS=
```

Regras:

- Não prometer publicamente source que está bloqueada, experimental ou despriorizada.
- WebMotors pode existir tecnicamente, mas deve ser tratada conforme decisão operacional atual.
- Proxies pagos/residenciais/mobile não entram por padrão sem decisão explícita.

### 2.6 Browser/Playwright

Use browser com cuidado.

Regras:

- Evitar como caminho principal quando HTTP/JSON/feed resolver.
- Manter paralelismo baixo.
- Monitorar processos zumbis.
- Não apagar cookies/sessões persistentes sem entender impacto.
- Em Raspberry/mini PC, validar memória real antes de aumentar concorrência.

### 2.7 Planos, upgrade e pagamento

Configurações típicas podem incluir links/identificadores do Mercado Pago:

```env
MERCADO_PAGO_ACCESS_TOKEN=replace-me
MERCADO_PAGO_WEBHOOK_SECRET=replace-me
PREMIUM_PAYMENT_LINK_MONTHLY=
PREMIUM_PAYMENT_LINK_YEARLY=
```

Estado atual esperado para lançamento:

- `/plan` mostra uso/limites;
- `/upgrade` apresenta oferta;
- ativação Premium precisa ser automática via webhook ou fallback com aprovação admin em 1 clique para beta aberto.

Regras:

- Não logar access token.
- Validar webhook antes de ativar Premium.
- Registrar auditoria de ativação, recusa e expiração.

### 2.8 Leilões

Leilões são controlados por gates e não devem ser liberados por simples variável de ambiente.

Fontes de verdade:

- `wishlists.include_auctions`
- `source_configs.source_type`
- `source_configs.user_eligible`
- `source_configs.status`
- categorias permitidas
- `AppKV` para settings runtime de notificação/dry-run

Regras obrigatórias:

- piloto controlado;
- `dry_run` como padrão seguro quando aplicável;
- apenas categorias permitidas;
- todo alerta deve deixar claro que lance não é preço final;
- não acionar envio automático real amplo sem PR específica e validação operacional.

## 3. Validação rápida de ambiente

Checklist local/servidor:

```bash
python --version
pip install -r requirements.txt
alembic heads
alembic current
pytest -q
python -m app.bot.run
python -m app.scheduler.run
```

Checklist pelo Telegram/admin:

```text
/start
/menu
/buscar
/plan
/upgrade
/admin health
/admin sources
/admin metrics
```

Checklist no banco:

- migrations aplicadas;
- `source_configs` populado;
- sources user-facing corretas;
- jobs não acumulando;
- notifications não presas;
- users/wishlists criados corretamente;
- limites de plano coerentes.

## 4. Configuração recomendada para beta controlado

- Ambiente único simples: Raspberry Pi 4, mini PC ou VPS pequena.
- PostgreSQL/Supabase externo.
- Bot e scheduler como processos separados quando possível.
- Logs persistidos e rotacionados.
- Backup documentado e testado.
- Browser desabilitado ou restrito por source.
- Sources experimentais fora da promessa pública.
- Admin chat restrito.

## 5. Não fazer

- Não subir token real para o GitHub.
- Não liberar source experimental por pressa de marketing.
- Não prometer cobertura total de mercado.
- Não rodar browser com paralelismo alto em hardware pequeno.
- Não usar `.env` para mascarar decisão que deveria estar em `source_configs`.
- Não abrir beta amplo sem teste mínimo de carga.
- Não ativar Premium sem auditoria mínima.

## 6. Próximas melhorias recomendadas

- Manter `.env.example` alinhado com este documento.
- Criar script de verificação de ambiente que valide settings essenciais sem imprimir segredos.
- Criar checklist automatizado de readiness para admin.
- Adicionar teste específico para gate de comandos admin.
