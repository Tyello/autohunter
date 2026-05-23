# Garagem Alvo / AutoHunter — Project Guideline

Atualizado em: 2026-05-22.

Este documento é a visão viva do runtime atual. Conteúdo histórico deve ser tratado como contexto, não como fonte de verdade quando divergir do código.

## 1) Identidade e posicionamento

- **Garagem Alvo**: marca pública.
- **AutoHunter**: nome técnico do runtime/repositório.
- Produto **Telegram-first** para monitoramento recorrente de oportunidades automotivas.
- Público principal: entusiastas que buscam carros específicos, versões raras, configurações especiais ou boas bases de projeto.

A API/FastAPI é auxiliar. A jornada de produto acontece no Telegram.

## 2) O que o sistema faz hoje

### Anúncios tradicionais

Fluxo oficial:

```text
wishlist -> scheduler tick -> scrape_jobs -> workers http/browser -> scrape+normalização+ingestão -> dedupe -> matching -> notifications -> sender Telegram
```

### Leilões

Fluxo atual:

```text
wishlist include_auctions -> auction_lots -> source_configs + categorias -> matching -> gates -> dry-run/samples/notify controlado
```

Leilões estão em piloto controlado: há opt-in por busca, controles admin, scheduler em dry-run e runtime settings por AppKV. Envio real automático ainda não é a recomendação operacional.

### Fluxos de usuário

Fluxos detalhados: `docs/USER_FLOWS.md`.

Resumo:

- `/start` e `/menu` são portas de entrada.
- `➕ Criar busca` é o caminho guiado principal.
- `🎯 Minhas buscas` permite gerir filtros, pausa/reativação e remoção.
- `🔎 Buscar agora` e `/buscar` fazem busca pontual sem salvar.
- `⭐ Rastrear` vincula anúncios a uma wishlist.
- `/plan` e `/upgrade` mostram limites e oferta Premium.

## 3) Superfícies do sistema

- `app/bot/`: UX Telegram de usuário e admin.
- `app/scheduler/`: scheduler, workers, sender, monitor, digest, jobs auxiliares.
- `app/services/`: regras de negócio, source execution, matching, notificações, settings runtime, planos e tracking.
- `app/sources/`: framework de plugins de sources tradicionais.
- `app/sources/auctions/`: registry/parsers de sources de leilão.
- `app/models/`: entidades persistidas.
- `app/main.py` e `app/web/`: API auxiliar.

## 4) Fonte de verdade operacional

### Sources tradicionais e de leilão

`source_configs` é a base operacional:

- `source`
- `source_type` (`classified` ou `auction`)
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

`source_states` complementa com estado operacional, backoff e saúde.

### Runtime settings de leilão

`AppKV` guarda `auction_notification_settings`:

- `enabled`
- `dry_run`
- `scheduler_minutes`
- `max_wishlists_per_run`
- `max_per_wishlist`
- `max_per_user_per_day`
- `min_score`
- `max_lot_age_hours`

Fallback: `app.core.settings` / `.env`.

Kill switch: `AUCTION_NOTIFICATIONS_KILL_SWITCH=true` força `enabled=false` efetivo.

## 5) Sources tradicionais

As sources tradicionais são registradas por plugin em `app/sources/builtins.py` e controladas por `source_configs`.

Exemplos já presentes no runtime incluem Mercado Livre, OLX, Chaves na Mão, WebMotors, GoGarage, iCarros, Mobiauto, Kavak, Facebook Marketplace e TurboClass.

O que está ativo em produção depende do banco, não apenas do código.

### Estado especial de WebMotors

WebMotors está tecnicamente implementada, diagnosticável e disponível para execução manual/admin, mas operacionalmente despriorizada por bloqueio anti-bot/fingerprint PerimeterX. Não deve ser tratada como source crítica de saúde global sem nova decisão explícita.

### Estado especial de TurboClass

TurboClass está presente como source HTTP/feed experimental e habilitada por default, com validação operacional contínua.

### V1/V2

A migração V1→V2 é trilha técnica paralela. Não fazer flip geral sem inventário, dual-run e paridade por source. Referência: `docs/V1_TO_V2_MIGRATION.md`.

## 6) Leilões — estado atual

Referência detalhada: [`docs/AUCTION_RUNTIME.md`](AUCTION_RUNTIME.md).

Pontos centrais:

- usuário decide por busca se aceita leilões (`wishlists.include_auctions`);
- admin controla sources, elegibilidade e categorias;
- no piloto, apenas `car` deve chegar ao usuário final;
- categorias `motorcycle`, `truck`, `heavy`, `real_estate` e `other` ficam bloqueadas por padrão no notify;
- scheduler pode rodar em dry-run automático;
- envio real automático não deve ser liberado nesta fase;
- `dry_run=false` é bloqueado pelo comando admin de settings;
- todo alerta user-facing de leilão precisa explicar que lance não é preço final.

Comandos operacionais principais:

```text
/admin source vip enable
/admin source vip user-enable
/admin source vip categories set car
/admin auctions settings
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
/admin auctions notify-run --source vip --limit-wishlists 5
```

## 7) Matching, dedupe e notificação

### Dedupe

- Listings tradicionais: dedupe por `(source, external_id)`.
- Notificações tradicionais: dedupe por par wishlist/listing.
- Leilões: dedupe por `auction:{wishlist_id}:{source}:{lot_external_id}`.

### Gates de leilão

Notify/scheduler de leilões exigem:

- wishlist ativa;
- `include_auctions=true`;
- source `enabled=true`;
- source `user_eligible=true`;
- categoria permitida;
- `item_type` conhecido;
- URL válida;
- lance atual ou inicial;
- score mínimo;
- lote atualizado recentemente;
- dedupe livre;
- limite diário por usuário.

### Copy obrigatória de leilão

Todo alerta de leilão para usuário final deve conter:

```text
Lance não é preço final.
```

E deve orientar verificação de edital, taxas/comissão, documentação e vistoria.

## 8) Tracking de anúncios por wishlist

- Cada wishlist tem até 3 slots de tracking.
- O limite total de rastreados varia por plano.
- Tracking mantém snapshot de preço/status por slot.
- Alerta de queda é permitido conforme plano/settings.
- Defaults: queda mínima de R$ 500 ou 1%, cooldown 24h.
- Premium tem acesso ampliado a tracking/alertas conforme regras comerciais atuais.

## 9) Modelo comercial mínimo

Planos oficiais de UX:

- **Free**
- **Premium**

Regras gerais atuais:

- Free: até 2 buscas salvas, 1 anúncio rastreado no total, 5 alertas/dia por busca, sem alertas automáticos de tracking.
- Premium: até 15 buscas salvas, 5 anúncios rastreados no total, até 3 slots por wishlist, alertas automáticos de tracking e 200 alertas/dia por busca.

Estado de pagamento:

- `/upgrade` pode exibir links Mercado Pago configuráveis.
- Ativação Premium ainda depende de validação/admin manual.
- Billing automático via webhook é lacuna de lançamento.

## 10) Operação e confiabilidade

Ferramentas principais:

```text
/admin health
/admin health verbose
/admin audit
/admin sources
/admin source <source> ...
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
```

Sinais críticos:

- scheduler stale global;
- fila `scrape_jobs` crescendo sem drenagem;
- source crítica com backoff/erro recorrente;
- sender sem progresso;
- notificações falhando em massa;
- fonte user_eligible de leilão sem dados mínimos.

Lacuna atual:

- falta `/admin metrics` para funil de produto/comercial: usuários, buscas, alertas, retenção e conversão Free→Premium.

## 11) Storage e limpeza

O runtime possui limpeza operacional para artefatos/cache/debug, mas não deve remover storage persistente sensível como perfis/cookies sem ação explícita.

Runbook de disco: [`docs/OPERATIONS_RUNBOOK.md`](OPERATIONS_RUNBOOK.md).

## 12) Backup e restore

Backup/restore core cobre:

- `users`
- `wishlists`
- `wishlist_filters`
- `wishlist_tracked_listings`
- opcionalmente `car_listings`

Referência: [`docs/BACKUP_RESTORE.md`](BACKUP_RESTORE.md).

## 13) Alembic e banco

- Manter head único.
- Rodar `alembic heads` antes de PR com migration.
- SQLite é para testes rápidos/unitários quando aplicável.
- PostgreSQL/Supabase é o banco operacional oficial.

## 14) Evolução incremental recomendada

Prioridades atuais combinadas:

1. Fechar lacunas de lançamento: pagamento/ativação, `/admin metrics`, teste de carga e operação beta/founders.
2. Continuar trilha técnica V1→V2 com inventário e dual-run controlado.
3. Evoluir digest semanal para comunicar valor mesmo sem alerta.
4. Avançar melhorias de inteligência: equivalência cross-source, histórico/retenção e contexto de mercado.
5. Melhorar Admin UX sem ampliar arquitetura.

## 15) Regras de cautela

- Não liberar `dry_run=false` sem PR específica, revisão e confirmação operacional.
- Não tornar source experimental `user_eligible` sem validar qualidade.
- Não permitir categorias não-car no piloto sem decisão explícita.
- Não remover código legado sem evidência de uso.
- Não misturar source técnica na UX de usuário final.
- Não prometer valor final de leilão: lance é apenas lance.
- Não tratar WebMotors como bloqueador imediato do lançamento se as demais sources entregarem valor.
- Não implementar dashboard web completo antes de validar necessidade real.

## 16) Documentos relacionados

- `README.md`
- `AGENTS.md`
- `docs/USER_FLOWS.md`
- `docs/ARCHITECTURE.md`
- `docs/LLM_CONTEXT.md`
- `docs/AUCTION_RUNTIME.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/ROADMAP.md`
- `docs/LAUNCH_PLAN.md`
- `docs/LEGACY_INVENTORY.md`
- `docs/BACKUP_RESTORE.md`
