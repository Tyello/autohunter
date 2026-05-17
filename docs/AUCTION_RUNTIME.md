# Garagem Alvo / AutoHunter — Auction Runtime

Este documento descreve o estado operacional atual da frente de leilões.

## 1) Estado atual

Leilões já saíram da POC puramente admin-only, mas ainda estão em piloto controlado.

O usuário final pode escolher por busca se aceita oportunidades de leilão (`wishlists.include_auctions`). O usuário **não** escolhe leiloeira/source técnica.

O admin controla:

- quais sources de leilão existem e estão habilitadas;
- quais sources são elegíveis para usuário final (`user_eligible`);
- quais categorias por source podem entrar no notify;
- settings runtime de scheduler/notificação;
- readiness, status e samples do dry-run.

## 2) Modelo mental

```text
Usuário:
  busca/wishlist + include_auctions=true|false

Admin:
  source enabled/user_eligible
  categorias permitidas por source
  runtime settings de notify/scheduler

Sistema:
  auction_lots -> matching -> gates -> dry-run/samples -> notify controlado
```

## 3) Sources de leilão

Registry técnico: `app/sources/auctions/registry.py`.

Config operacional: `source_configs`.

Campos relevantes:

- `source`: chave técnica (`vip_auctions`, `mega_auctions`, etc.);
- `source_type='auction'`;
- `is_enabled`: source operacionalmente ligada/desligada;
- `user_eligible`: pode chegar ao usuário final;
- `admin_only`: apoio operacional;
- `status`: `active`, `experimental`, `needs_study`, etc.;
- `extra.allowed_item_types`: categorias permitidas no notify.

Sources registradas no estado atual:

- `vip_auctions` — ativa/elegível no piloto quando configurada assim no banco;
- `mega_auctions` — experimental;
- `win_auctions` — experimental;
- `sodre_auctions` — experimental/needs study conforme bloqueio;
- `superbid_auctions` — experimental;
- `copart_auctions` — needs JS/internal endpoint study.

O estado real em produção depende de `source_configs`, não só do registry.

## 4) Categorias de leilão

Categorias canônicas:

- `car`
- `motorcycle`
- `truck`
- `heavy`
- `real_estate`
- `other`

Default seguro: se uma auction source não tiver `extra.allowed_item_types`, o sistema assume apenas `car`.

No piloto atual, somente `car` deve chegar ao usuário final. Motos, caminhões/pesados, imóveis e outros ficam bloqueados por padrão no notify.

Exemplos:

```text
/admin source vip categories
/admin source vip categories set car
/admin source vip categories set car,motorcycle
/admin source vip categories remove motorcycle
```

Regra operacional atual: `car` apenas, salvo diagnóstico explícito.

## 5) Opt-in por wishlist

Campo: `wishlists.include_auctions`.

- Default: `false`.
- Pode ser escolhido pelo usuário na criação da busca.
- Pode ser alterado em ajustes de filtros.
- Admin também consegue listar/alterar em comandos de leilão.

`include_auctions=true` não garante alerta. Ele apenas torna a busca elegível. O alerta ainda depende de source/categoria/gates/dedupe/limites.

## 6) Gates de notificação

Um alerta de leilão só deve ser montado se passar por todos os gates:

1. wishlist ativa;
2. `include_auctions=true`;
3. source com `source_type='auction'`;
4. source `is_enabled=true`;
5. source `user_eligible=true`;
6. categoria do lote permitida para a source;
7. lote com `item_type` conhecido;
8. lote com `url` válida;
9. lote com `current_bid` ou `initial_bid`;
10. status não finalizado/cancelado/vendido, salvo força diagnóstica;
11. score mínimo;
12. lote atualizado dentro da janela configurada;
13. dedupe ainda não enviado para a mesma wishlist/lote;
14. limite diário por usuário permite.

Contadores relevantes:

- `skipped_item_type_not_allowed`
- `skipped_missing_item_type`
- `skipped_score_below_min`
- `skipped_stale_lot`
- `skipped_missing_lot_updated_at`
- `skipped_duplicate`
- `skipped_daily_limit`
- `skipped_missing_chat_id`

## 7) Runtime settings

Config runtime em AppKV:

```text
auction_notification_settings
```

Campos:

- `enabled`
- `dry_run`
- `scheduler_minutes`
- `max_wishlists_per_run`
- `max_per_wishlist`
- `max_per_user_per_day`
- `min_score`
- `max_lot_age_hours`
- `updated_at`
- `updated_by`

Fallback por campo: `app.core.settings` / `.env`.

Kill switch via env:

```text
AUCTION_NOTIFICATIONS_KILL_SWITCH=true
```

Quando ativo, força `enabled=false` no valor efetivo, mesmo que o runtime esteja `enabled=true`.

Comandos:

```text
/admin auctions settings
/admin auctions settings set enabled true
/admin auctions settings set dry_run true
/admin auctions settings set scheduler_minutes 60
/admin auctions settings set min_score 60
/admin auctions settings set max_lot_age_hours 48
/admin auctions settings set max_wishlists_per_run 20
/admin auctions settings set max_per_wishlist 1
/admin auctions settings set max_per_user_per_day 3
/admin auctions settings reset <key>
/admin auctions settings reset-all
```

Nesta fase, o comando admin bloqueia `dry_run=false`.

## 8) Scheduler de leilões

Job: `auction_notification_scheduler_job`.

O scheduler lê runtime settings efetivas.

Estados seguros:

- `enabled=false`: não executa notify; registra skip.
- `enabled=true` + `dry_run=true`: simula, gera summaries/samples, não envia mensagem real.
- `enabled=true` + `dry_run=false`: caminho técnico existe, mas não deve ser liberado operacionalmente nesta fase; o comando admin bloqueia esse valor.
- `kill_switch=true`: força `enabled=false`.

`*scheduler_minutes*` é lido no registro do scheduler. Mudança de intervalo pode exigir restart do scheduler para reprogramar o job.

## 9) Comandos admin principais

Sources/categorias:

```text
/admin sources
/admin source vip enable
/admin source vip disable
/admin source vip user-enable
/admin source vip user-disable
/admin source vip categories
/admin source vip categories set car
/admin auctions sources
/admin auctions source-config vip categories set car
```

Ingestão/matching/preview:

```text
/admin auctions run vip --limit 10 --enrich
/admin auctions quality
/admin auctions source vip
/admin auctions match vip
/admin auctions preview vip
/admin auctions wishlists
/admin auctions wishlist <id|index> enable|disable
```

Notify/status:

```text
/admin auctions notify wishlist <id|index> [--confirm]
/admin auctions notify-run --source vip --limit-wishlists 5
/admin auctions notify-status
/admin auctions notify-samples
/admin auctions readiness
/admin auctions settings
```

## 10) Copy user-facing obrigatória

Todo alerta de leilão para usuário final deve ser distinto de anúncio tradicional.

Requisitos:

- abrir como oportunidade em leilão;
- usar source label amigável quando disponível (`VIP Leilões`, etc.);
- nunca mostrar `None`;
- mostrar só campos existentes;
- conter literalmente: `Lance não é preço final.`;
- orientar verificação de edital, taxas/comissão, documentação e vistoria.

## 11) Procedimento recomendado para ativar dry-run automático

1. Garantir deploy atualizado.
2. Configurar runtime:

```text
/admin auctions settings set enabled true
/admin auctions settings set dry_run true
/admin auctions settings set min_score 60
/admin auctions settings set max_lot_age_hours 48
/admin auctions settings set max_wishlists_per_run 20
/admin auctions settings set max_per_wishlist 1
/admin auctions settings set max_per_user_per_day 3
```

3. Garantir source/categoria:

```text
/admin source vip enable
/admin source vip user-enable
/admin source vip categories set car
```

4. Validar:

```text
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
```

5. Aguardar ciclo do scheduler e revisar samples.

Não ativar envio real automático nesta fase.

## 12) Próximas evoluções prováveis

- Digest operacional de dry-run 24h.
- Painel mais compacto de decisão: manter dry-run, ajustar gates ou preparar piloto manual.
- Hardening adicional de categorias/normalização por source.
- Futuro caminho de envio real automático somente com nova revisão, nova trava e validação explícita.
