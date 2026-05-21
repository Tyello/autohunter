# Garagem Alvo / AutoHunter — Arquitetura atual

Atualizado em: 2026-05-21.

Este documento descreve a arquitetura operacional atual do AutoHunter, runtime interno que sustenta a marca pública Garagem Alvo.

## 1. Resumo executivo

Garagem Alvo é um produto Telegram-first para monitoramento recorrente de oportunidades automotivas.

AutoHunter é o runtime técnico/repositório. O núcleo do produto não é a API web: é o conjunto de bot Telegram, scheduler, filas persistentes, workers, scrapers/sources, matching, dedupe, notificação e observabilidade operacional.

Fluxo principal de classificados:

```text
usuário no Telegram
  -> busca/wishlist
  -> scheduler tick por source
  -> scrape_jobs persistente
  -> workers HTTP/browser
  -> scrape + normalização + ingestão
  -> dedupe
  -> matching com wishlists
  -> notifications
  -> sender Telegram
```

Fluxo atual de leilões:

```text
wishlist include_auctions=true
  -> auction_lots persistidos
  -> source_configs + categorias permitidas + user_eligible
  -> matching/gates
  -> dry-run/samples/preview admin
  -> envio real manual controlado quando explicitamente acionado
```

## 2. Fronteiras do sistema

### Produto principal

- `app/bot/`: jornada principal do usuário final e comandos administrativos.
- Telegram é a superfície oficial de uso.
- A terminologia pública deve priorizar Garagem Alvo, busca, alerta, oportunidade e assinatura Premium.

### Runtime operacional

- `app/scheduler/`: agenda ticks, workers, sender, monitor, digest, cleanup, premium expiration, autopilot e jobs de leilão.
- `app/services/`: regras de negócio, execução de sources, configuração DB-driven, matching, notificações, settings runtime e observabilidade.
- `app/sources/`: registry e plugins de sources tradicionais.
- `app/sources/auctions/`: registry e parsers/fetchers de leilões.
- `app/models/`: entidades persistidas via SQLAlchemy/Alembic.

### Superfície auxiliar

- `app/main.py` e `app/web/`: FastAPI para health, checks, listagem simples e integrações auxiliares.
- A API pode iniciar scheduler quando `settings.enable_scheduler_in_api` estiver ligado, mas não deve ser tratada como jornada principal do usuário final.

## 3. Componentes principais

### 3.1 Bot Telegram

Arquivo principal: `app/bot/run.py`.

Responsabilidades:

- registrar comandos públicos e administrativos;
- iniciar polling do Telegram;
- configurar comandos oficiais;
- entregar notificações pendentes via sender embutido quando o scheduler não está rodando em alguns ambientes locais;
- registrar handlers de busca, menu, wishlist, filtros, tracking, planos, upgrade, admin, debug, Facebook Agent e callbacks.

Cuidados:

- handlers devem ser finos;
- regra de negócio deve ficar em services/core, não em handlers;
- comandos antigos podem coexistir com UX guiada por compatibilidade;
- callbacks globais não devem roubar estados de ConversationHandler.

### 3.2 Scheduler

Arquivo principal: `app/scheduler/run.py`.

Responsabilidades:

- criar `BackgroundScheduler` em UTC;
- registrar ticks por source com cadência curta de avaliação;
- delegar execução real para filas persistentes `scrape_jobs`;
- rodar heartbeat;
- rodar workers HTTP e browser;
- rodar sender de notificações;
- rodar scheduler de leilões;
- rodar alertas de tracking quando habilitados;
- rodar digest semanal;
- rodar admin monitor e autopilot;
- rodar limpeza de notifications e filesystem;
- expirar assinaturas Premium.

O scheduler não deve fazer scrape pesado dentro do tick. O tick deve apenas decidir se a source está due, respeitar backoff/config e enfileirar job.

### 3.3 Filas persistentes

Modelo principal: `app/models/scrape_job.py`.

Tabela: `scrape_jobs`.

Responsabilidades:

- garantir execução previsível e observável;
- separar filas `http` e `browser`;
- controlar status `queued|running|done|failed`;
- registrar lock, tentativas, tempo de execução, payload de resultado e erro.

Regra operacional:

- browser deve ter paralelismo baixo;
- HTTP pode ter paralelismo controlado;
- fila crescendo sem drenagem é sinal de incidente operacional.

### 3.4 Execução de sources tradicionais

Arquivo central: `app/services/source_execution_service.py`.

Responsabilidades:

- executar uma source para todas as wishlists elegíveis;
- garantir `source_configs`;
- respeitar `is_enabled`, schedule, cooldown, rate-limit, proxy, browser flags e backoff;
- agrupar wishlists por URL de busca;
- despachar implementação v1/v2/dual conforme flags;
- chamar `scrape_ingest_match_many`;
- classificar erros em OK/BLOCKED/NET/PROXY/PARSE/DATA/ERR;
- registrar `source_runs`, `system_logs`, eventos e payloads operacionais;
- aplicar backoff em bloqueios/erros;
- reconciliar atividade/inatividade de listings por run;
- retornar resumo acionável para admin/scheduler.

Cuidados:

- é o coração do runtime de classificados;
- refactor deve ser incremental e coberto por testes;
- não remover v1/v2/dual sem evidência de migração concluída;
- WebMotors tem diagnóstico especial de bloqueio/proxy/parser.

### 3.5 Sources tradicionais

Registry principal: `app/sources/builtins.py`.

Sources presentes no runtime incluem:

- `mercadolivre`
- `olx`
- `chavesnamao`
- `webmotors`
- `gogarage`
- `icarros`
- `mobiauto`
- `kavak`
- `facebook_marketplace`
- `turboclass`

O fato de existir plugin no código não significa que a source esteja ativa em produção. A operação efetiva é DB-driven via `source_configs`.

### 3.6 Sources de leilão

Registry técnico: `app/sources/auctions/registry.py`.

Defaults operacionais efetivos: `app/services/auction_source_config_service.py`.

Sources atuais:

- `vip_auctions`: production_ready; source user-facing controlada para piloto de carros.
- `mega_auctions`: experimental; enriquecimento de detalhe e diagnóstico admin.
- `win_auctions`: experimental_functional_vehicle via defaults operacionais; captura veículos reais, mas ainda não user-facing.
- `sodre_auctions`: blocked/needs_study.
- `superbid_auctions`: needs_study.
- `copart_auctions`: needs_study.

Atenção: o registry técnico define fetchers/aliases. O serviço de config de leilão reconcilia `source_configs.source_type` e `source_configs.status` com defaults operacionais seguros. Quando houver divergência documental, trate `source_configs` e `auction_source_config_service.DEFAULTS` como referência operacional.

### 3.7 Matching, dedupe e notificação

Modelos/tabelas relevantes:

- `wishlists`
- `wishlist_filters`
- `wishlist_tokens`
- `wishlist_tracked_listings`
- `car_listings`
- `auction_lots`
- `notifications`

Classificados:

- dedupe principal por `(source, external_id)`;
- matching por wishlist/filtros/tokens;
- notificação persistida em `notifications`;
- sender entrega pelo Telegram;
- dedupe de notificação evita reenviar o mesmo listing para a mesma wishlist.

Leilões:

- opt-in por `wishlists.include_auctions`;
- lotes em `auction_lots`;
- dedupe lógico por `auction:{wishlist_id}:{source}:{lot_external_id}`;
- gates obrigatórios antes de qualquer alerta user-facing.

### 3.8 Tracking por wishlist

Cada wishlist pode rastrear até 3 anúncios.

Responsabilidades:

- guardar snapshot por slot;
- permitir alerta de queda por slot;
- controlar queda mínima/cooldown;
- diferenciar limites Free/Premium.

O job de alertas de tracking é protegido por setting e não deve ser assumido como sempre ligado.

## 4. Banco e configuração runtime

Banco operacional: PostgreSQL/Supabase.

SQLite pode aparecer em testes locais, mas não é o banco operacional oficial.

### Tabelas/configs críticas

`source_configs` controla:

- `source`
- `source_type`
- `is_enabled`
- `user_eligible`
- `admin_only`
- `status`
- `sched_minutes`
- `cooldown_minutes`
- `rate_limit_seconds`
- `proxy_server`
- `browser_fallback_enabled`
- `force_browser`
- `extra`

`source_states` controla:

- `next_allowed_at`
- `last_run_at`
- `last_effective_run_at`
- `consecutive_blocks`
- `consecutive_failures`
- `last_status`
- `last_error`
- throttling de alerta admin.

`AppKV` controla settings runtime flexíveis, principalmente frente de leilões (`auction_notification_settings` e samples de dry-run).

`.env` deve ser usado como fallback, bootstrap e kill switch, não como única fonte de knobs operacionais de produto.

## 5. Leilões: gates obrigatórios

Um alerta de leilão só pode ser considerado elegível quando todos os pontos abaixo passarem:

1. wishlist ativa;
2. `include_auctions=true`;
3. source enabled;
4. source `user_eligible=true`;
5. categoria permitida pela source;
6. tipo conhecido e permitido, no piloto apenas `car`;
7. URL válida;
8. lance atual ou inicial;
9. score mínimo;
10. lote recente dentro da janela operacional;
11. dedupe livre;
12. limite diário por usuário respeitado.

Todo alerta user-facing de leilão deve conter:

```text
Lance não é preço final.
```

E deve orientar leitura de edital, taxas/comissão, documentação, vistoria e regras do leiloeiro.

## 6. Observabilidade e operação

Superfícies operacionais principais:

```text
/admin health
/admin health verbose
/admin audit
/admin sources
/admin source <source> ...
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
/admin auctions digest
/admin auctions pilot
```

Sinais críticos:

- scheduler sem heartbeat;
- `scrape_jobs` acumulando;
- `source_runs` sem sucesso recente;
- `source_states` com backoff permanente;
- sender sem drenar `notifications`;
- alto volume de failed/suppressed/discarded;
- source experimental marcada por engano como user-facing;
- categorias não-car chegando ao piloto de leilões.

## 7. Limpeza e armazenamento local

Existe job de limpeza de notifications e job de limpeza de filesystem. Eles fazem parte da higiene operacional e não devem ser removidos sem confirmar impacto em disco.

Não apagar manualmente perfis/cookies/sessões persistentes sem decisão explícita, porque podem ser necessários para integrações auxiliares e fontes com sessão.

## 8. API FastAPI

Arquivo: `app/main.py`.

Rotas relevantes:

- `/health`
- `/db-check`
- `/listings`
- `/admin/health`
- rotas auxiliares de Facebook Auth/Agent;
- websocket `/ws/fb/agent`.

Regra: FastAPI é auxiliar. Não redesenhar o produto como web-first sem decisão explícita.

## 9. Regras para evolução segura

- Código atual vence documentação histórica.
- Mudanças devem ser pequenas, reversíveis e testáveis.
- Não remover legado sem validar imports, comandos, dados e operação real.
- Não misturar regra de negócio em handlers Telegram.
- Não promover source experimental para usuário final sem gates claros.
- Não liberar `dry_run=false` automático para leilões sem PR específica e revisão operacional.
- Não aumentar Playwright/paralelismo sem considerar Raspberry Pi 4 4GB.
- Sempre validar migrations com `alembic heads` e suíte de testes relevante.

## 10. Comandos de validação recomendados

```bash
pytest -q
alembic heads
python -m app.bot.run   # quando for validar bot localmente com env real
python -m app.scheduler.run  # quando aplicável ao entrypoint do ambiente
```

Para mudanças focadas, rodar testes específicos da área alterada antes da suíte completa.
