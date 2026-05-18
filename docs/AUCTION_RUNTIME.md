# Garagem Alvo / AutoHunter — Auction Runtime

Este guia descreve o estado atual da frente de leilões no AutoHunter.

## 1) Objetivo

Leilões são uma expansão controlada do produto Garagem Alvo para oportunidades automotivas especiais.

O usuário final não escolhe leiloeira/source. Ele escolhe apenas, por busca, se aceita oportunidades em leilão. A operação decide quais sources e categorias podem chegar ao usuário.

## 2) Estado atual

- Leilões têm dados próprios em `auction_lots`.
- Sources de leilão ficam no registry técnico em `app/sources/auctions/registry.py`.
- Operação de sources é DB-driven via `source_configs`.
- O usuário opta por leilões por wishlist via `wishlists.include_auctions`.
- Runtime de notificação de leilões tem scheduler, dry-run, samples, readiness e settings em AppKV.
- Envio automático real continua bloqueado via comando admin nesta fase.

## 3) Modelo mental

```text
Usuário:
  busca aceita leilões? sim/não

Admin:
  source ligada/desligada
  source elegível para usuário? sim/não
  categorias permitidas por source
  settings runtime de notify/scheduler

Sistema:
  source elegível
  + categoria permitida
  + wishlist opt-in
  + lance
  + score mínimo
  + lote recente
  + dedupe
  + limite diário
  => alerta elegível
```

## 4) Sources de leilão

Registry técnico atual:

- `vip_auctions` — VIP Leilões — ativa/elegível no piloto.
- `mega_auctions` — Mega Leilões — experimental.
- `win_auctions` — Win Leilões — experimental.
- `sodre_auctions` — Sodré Santoro — experimental/needs study conforme disponibilidade.
- `superbid_auctions` — Superbid — experimental.
- `copart_auctions` — Copart — needs JS/internal endpoint study.

O registry define implementação. `source_configs` define operação.

## 5) Controle unificado de sources

Comandos principais:

```text
/admin sources
/admin source vip enable
/admin source vip disable
/admin source vip user-enable
/admin source vip user-disable
```

Aliases aceitos para leilões incluem `vip`, `mega`, `win`, `sodre`, `superbid`, `copart`.

Regras:

- `disable` também deve remover `user_eligible`.
- `user-enable` exige source enabled.
- Source experimental pode estar enabled para diagnóstico, mas não deve ser user_eligible por padrão.

## 6) Categorias permitidas

Categorias canônicas:

- `car`
- `motorcycle`
- `truck`
- `heavy`
- `real_estate`
- `other`

No piloto atual, apenas `car` deve ser permitido para usuário final.

Comandos:

```text
/admin source vip categories
/admin source vip categories set car
/admin source vip categories add motorcycle
/admin source vip categories remove motorcycle
```

Compatibilidade:

```text
/admin auctions source-config vip categories set car
```

Default seguro: auction source sem configuração explícita permite apenas `car`.

`item_type` ausente ou desconhecido deve ser bloqueado no pipeline de notificação, salvo configuração explícita que permita `other`.

## 7) Runtime settings de notificações

As configs operacionais de notificação de leilão ficam em AppKV:

```text
auction_notification_settings
```

Comandos:

```text
/admin auctions settings
/admin auctions settings set enabled true|false
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

`.env` continua como fallback e kill switch. AppKV é a superfície operacional runtime.

### Defaults recomendados no piloto

```text
enabled=true
dry_run=true
scheduler_minutes=60
min_score=60
max_lot_age_hours=48
max_wishlists_per_run=20
max_per_wishlist=1
max_per_user_per_day=3
```

### Envio real automático

`dry_run=false` é bloqueado pelo comando admin nesta fase.

Para liberar envio real automático no futuro, deve haver PR específica, revisão explícita e novos guardrails.

## 8) Gates de elegibilidade para notify

O pipeline de notificação de leilão só deve montar item se todos os gates passarem:

1. Wishlist ativa.
2. `include_auctions=true`.
3. Source `enabled=true`.
4. Source `user_eligible=true`.
5. Categoria do lote permitida para a source.
6. Lote com URL válida.
7. Lote com `current_bid` ou `initial_bid`.
8. Score do match >= `min_score` runtime.
9. Lote atualizado dentro de `max_lot_age_hours` runtime, exceto quando `0` desabilita o filtro.
10. Dedupe ainda não enviado para a mesma wishlist/source/lote.
11. Limite diário por usuário não atingido.

Contadores operacionais relevantes:

- `skipped_score_below_min`
- `skipped_stale_lot`
- `skipped_missing_lot_updated_at`
- `skipped_item_type_not_allowed`
- `skipped_missing_item_type`
- `skipped_duplicate`
- `skipped_daily_limit`
- `skipped_no_match`

## 9) Comandos de operação

### Ingestão manual

```text
/admin auctions run vip --limit 10
/admin auctions run vip --limit 10 --enrich
```

### Qualidade/source

```text
/admin auctions sources
/admin auctions source vip
/admin auctions quality
/admin auctions quality vip
/admin auctions upcoming
```

### Matching/preview diagnóstico

```text
/admin auctions match vip
/admin auctions match wishlist <id|index>
/admin auctions preview vip
/admin auctions preview wishlist <id|index>
```

### Opt-in por wishlist

```text
/admin auctions wishlists [texto]
/admin auctions wishlist <id|index> enable
/admin auctions wishlist <id|index> disable
```

### Notify manual/job

```text
/admin auctions notify wishlist <id|index> [--source vip] [--limit N] [--confirm]
/admin auctions notify-run
/admin auctions notify-run --source vip --limit-wishlists 5
```

Sem `--confirm`, notify manual roda em dry-run.

### Observabilidade

```text
/admin auctions settings
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
```

## 10) Readiness operacional

Antes de ativar scheduler dry-run automático, rodar:

```text
/admin auctions readiness
```

Interpretação:

- `ok`: pronto para dry-run automático.
- `warn`: pronto com ressalvas; avaliar avisos.
- `fail`: não ativar.

Checks esperados:

- envio real automático não ativo;
- source elegível disponível;
- VIP operacional no piloto;
- existem wishlists opt-in;
- existem lotes recentes com lance;
- scheduler registrou execução;
- samples de dry-run existem;
- gates de qualidade seguros;
- categorias user_eligible permanecem somente `car`.

## 11) Dry-run e samples

Dry-run pode persistir amostras em AppKV:

```text
auction_last_dry_run_samples
```

As amostras servem para auditar qualidade do que seria enviado:

- wishlist/query;
- source;
- título;
- lance atual/inicial;
- metadados opcionais quando disponíveis (ano, km, lances, encerramento e local);
- score técnico no contexto admin (wrapper), sem obrigação de aparecer na copy final user-facing;
- link;
- summary de skips.

Amostras de dry-run não são dedupe e não significam envio real.

## 12) Copy obrigatória de alerta

Todo alerta user-facing de leilão deve ser diferente de anúncio tradicional.

Deve conter:

```text
Lance não é preço final.
```

E orientar verificação de:

- edital;
- taxas/comissão;
- documentação;
- vistoria;
- regras do leiloeiro.

Usar label amigável da source quando houver, por exemplo `VIP Leilões`, evitando expor `vip_auctions` ao usuário final.

## 13) Sequência operacional recomendada

1. Deploy/restart.
2. Garantir source/categoria:
   ```text
   /admin source vip enable
   /admin source vip user-enable
   /admin source vip categories set car
   ```
3. Configurar runtime:
   ```text
   /admin auctions settings set enabled true
   /admin auctions settings set dry_run true
   /admin auctions settings set min_score 60
   /admin auctions settings set max_lot_age_hours 48
   ```
4. Validar:
   ```text
   /admin auctions readiness
   /admin auctions notify-status
   ```
5. Aguardar ciclo do scheduler.
6. Auditar:
   ```text
   /admin auctions notify-samples
   /admin auctions readiness
   ```
7. Não liberar envio real automático sem nova decisão/PR.

## 14) O que não fazer

- Não liberar `dry_run=false` por ajuste manual fora do fluxo revisado.
- Não colocar source experimental como `user_eligible` sem validação de qualidade.
- Não permitir `motorcycle`, `truck`, `heavy`, `real_estate` ou `other` no piloto sem decisão explícita.
- Não remover o disclosure de risco do alerta.
- Não tratar lance como preço final.
- Não depender apenas de `.env` para knobs operacionais runtime.
## Validação de copy com dry-run (`notify-samples`)

- O comando `/admin auctions notify-samples` exibe previews **user-facing simulados** dos alertas de leilão.
- Esse comando é apenas observabilidade/admin: **nenhuma mensagem é enviada ao usuário final**.
- O disclosure `Lance não é preço final.` permanece obrigatório na mensagem simulada/user-facing.
- Use esse preview para validar copy, disclosure de risco e legibilidade antes de qualquer decisão de envio real.
## Auction dry-run digest

Use `/admin auctions digest` para visão operacional consolidada do dry-run de notificações de leilão.

- É comando **somente leitura** para admin.
- Não envia alertas reais nem altera scheduler/matching/gates.
- Janela padrão: 24h (`/admin auctions digest --hours 6` até `--hours 168`).
- Resume runs, buscas avaliadas, previews, erros, bloqueios, sources e últimas amostras/rejeições.
- Deve ser consultado antes de decidir por piloto manual/controlado.
- Envio real automático continua fora do escopo nesta fase.
