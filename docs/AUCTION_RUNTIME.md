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

- `vip_auctions` — VIP Leilões — `production_ready`, única source `user_eligible` por padrão no piloto `car`.
- `mega_auctions` — Mega Leilões — `experimental_detail_enrichment`; segue padrão listagem -> detail URL -> lote mínimo -> enrich por detalhe -> quality/monitor. Inspect por URL (`/admin auctions inspect mega --url <detail_url>`) inclui diagnóstico compacto de detalhe (`status/date/bid/image/location/json/data-*`), sem persistência. Extração conservadora: `Data do Leilão`/`Início` -> `auction_start_at`; `Encerramento`/`Fim`/`Data Final`/`Término` -> `auction_end_at`; `current_bid` só com rótulo explícito; `online` genérico não vira `live`; cidade/UF prioriza URL `/veiculos/carros/<uf>/<cidade>/...`; classificação prioriza URL (`/veiculos/carros` vence título), páginas genéricas/eventos sem identificador de lote (`J\d+`) são descartadas, e local inválido (`Sem Informacao / SI`) é higienizado para vazio no re-enrich. Para dados históricos já persistidos, usar `/admin auctions hygiene mega --dry-run` (e `--apply` apenas de forma explícita) para marcar `generic_page` como inválido e corrigir `item_type` quando a URL for inequívoca; Mega continua não user-facing.
- `win_auctions` — Win Leilões — `experimental_functional_vehicle`; captura carros reais via detail URLs e enrich funcional. Sinais operacionais atuais: `Aberto para Lances` => `status=live`; `Data do Leilão` => `auction_start_at` (não encerra o lote); `Lance Inicial` alimenta apenas `initial_bid`; `current_bid` é extraído quando há rótulo explícito de maior lance (`MAIOR LANCE NO MOMENTO`/`Maior Lance no Momento`/`Maior Lance`/`Lance Atual`/`Último Lance`/`Lance Vencedor`) e não é inferido a partir de `Lance Inicial`. Inspect de detalhe usa diagnóstico compacto para caber no Telegram. Ainda experimental e fora do user-facing.
- `sodre_auctions` — Sodré Santoro — `blocked`/`needs_study`, fetch real com `forbidden_403` e diagnóstico HTTP mínimo no inspect.
- `superbid_auctions` — Superbid — `needs_study`, fora do piloto.
- `copart_auctions` — Copart — `needs_study`, fora do piloto.

O registry define implementação. `source_configs` define operação. O bootstrap/reconcile de leilões atualiza automaticamente apenas metadados seguros (`source_type` e `status`) para refletir o registry/defaults atuais; decisões operacionais como `is_enabled`, `user_eligible`, `disabled_reason` e categorias permitidas em `extra.allowed_item_types` não são sobrescritas.

### Status operacional por source (2026-05-18)

| Source | Classificação | Diagnóstico rápido | Estratégia |
|---|---|---|---|
| `vip_auctions` | `production_ready` | pronto para piloto `car`; cards públicos + parser estável; mantém lance/URL/ano suficientes para notificação | HTML simples (requests); única `user_eligible` por padrão |
| `mega_auctions` | `experimental` | enrich de detalhe ativo com extração defensiva (lances, datas, status, imagem e city/UF), higiene de classificação/local inválido e diagnóstico no inspect (score observado: 60/100); ainda sem cobertura confiável de encerramento | manter fora de `user_eligible`; monitorar por `/admin auctions monitor mega` e `/admin auctions source-history mega` |
| `win_auctions` | `experimental_functional_vehicle` | captura carros reais com enrich por detalhe (`/item/<id>/detalhes`) e cobertura boa de `initial_bid`, `year`, imagem e URL; parser extrai status e `auction_start_at` (`Data do Leilão` como início/agenda) e só preenche `auction_end_at` com sinal explícito de encerramento; cobertura de encerramento ainda é parcial | manter `user_eligible=false`; próximo passo: monitorar por ciclos, ampliar cobertura confiável de status/end date/current bid e reduzir ruído de localização |

Estado validado (admin): captura carros reais via detail URLs, com status `live`, `auction_start_at` (Data do Leilão como início/agenda), lance inicial e, quando disponível, `current_bid` (Maior Lance no Momento). A principal pendência para prontidão user-facing continua sendo `auction_end_at`/encerramento em cobertura confiável. Win permanece experimental e não user-facing (`user_eligible=false`). Próxima etapa: usar `/admin auctions inspect win --url <detail_url>` e a seção **Diagnóstico detalhe Win** para mapear sinais reais de encerramento e elevar cobertura de `auction_end_at` com segurança.
| `superbid_auctions` | `needs_study` | banners deixaram de ser tratados como lote; retorno atual indica `requires_js_or_event_drilldown` | estudar endpoint/drilldown antes de elegibilidade; sem Playwright nesta fase |
| `copart_auctions` | `needs_study` | sem cards públicos no HTML estático; indício de renderização JS | manter fora do piloto; estudar endpoint sem bypass agressivo |
| `sodre_auctions` | `blocked`/`needs_study` | ocorrência recorrente de `forbidden_403` | não contornar proteção anti-bot; manter fora do piloto |


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

`/admin auctions quality` mantém `Atualizados 24h` como métrica de freshness, mas `Pronta piloto car` usa a mesma janela operacional de readiness: `auction_notification_settings.max_lot_age_hours` em AppKV, com fallback seguro de 48h. O render também mostra `Janela piloto car: Nh` para evitar confusão entre freshness de 24h e prontidão operacional.

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
- existem lotes `car` recentes com lance nas sources elegíveis;
- scheduler registrou execução;
- samples de dry-run existem;
- gates de qualidade seguros;
- categorias user_eligible permanecem somente `car`;
- resumo por source inclui `car_lots`, `user_allowed_lots` e `source_ready_for_user_car_pilot`;
- readiness usa `auction_notification_settings.max_lot_age_hours` para definir a janela de lote recente, com fallback seguro de 48h;
- source só conta como pronta para piloto `car` se tiver pelo menos um lote `car` dentro dessa janela operacional, com URL, lance e ano; imóveis/motos/caminhões/pesados não contam para readiness do piloto `car`;
- sources funcionais sem `car` recente geram warning, por exemplo `win_auctions funcional, mas sem lotes car recentes. Fora do piloto de carros.`;
- sources com carros sem lance útil geram warning, por exemplo `mega_auctions tem carros, mas sem lance inicial/atual. Manter experimental.`.

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

## Admin preview send

Use `/admin auctions preview-send` para validar visualmente a mensagem final do alerta de leilão (incluindo botão inline `🔗 Ver leilão`) com segurança operacional.

- Envia **somente para o chat do admin** que executou o comando.
- Reaproveita o mesmo renderer user-facing e o mesmo `reply_markup` do envio real.
- **Não grava dedupe**, não incrementa limite diário e não altera status de notificação.
- **Não envia ao usuário final**.
- **Não substitui o envio real manual** (`notify-run --real`).
- Fonte do preview: última amostra disponível em `auction_last_dry_run_samples`.
- Sem amostra, o comando orienta rodar:
  `/admin auctions notify-run --source vip --limit-wishlists 5`
## Auction dry-run digest

Use `/admin auctions digest` para visão operacional consolidada do dry-run de notificações de leilão.

- É comando **somente leitura** para admin.
- Não envia alertas reais nem altera scheduler/matching/gates.
- Janela padrão: 24h (`/admin auctions digest --hours 6` até `--hours 168`).
- Resume runs, buscas avaliadas, previews, erros, bloqueios, sources e últimas amostras/rejeições.
- Deve ser consultado antes de decidir por piloto manual/controlado.
- Envio real automático continua fora do escopo nesta fase.

## Controlled VIP-only real pilot

- Piloto real controlado usa **somente** `vip_auctions`.
- `mega_auctions`, `win_auctions`, `superbid`, `copart`, `sodre` seguem admin/experimental e fora do piloto user-facing.
- `dry_run=true` continua como default seguro.
- O scheduler automático com envio real **não deve** ser ligado nesta etapa.
- `--real` no `notify-run` é manual, limitado e não altera o `dry_run` global.

Fluxo recomendado:
1. `/admin auctions notify-run --source vip --limit-wishlists 5`
2. `/admin auctions notify-samples`
3. `/admin auctions preview-send`
4. `/admin auctions notify-run --source vip --limit-wishlists 5 --real`

Rollback operacional:
- `/admin auctions settings set dry_run true`
- `/admin auctions settings set enabled false`
- `/admin source vip user-disable`

Se algo sair errado, desabilite leilões (`enabled=false`) ou retire a VIP do user-facing (`user-disable`).

## User-facing auction UX

- O usuário opta por leilões por busca (`include_auctions`), com estado visível em criação, listagem e ajustes de filtros.
- No piloto atual, `VIP Leilões` é a única source user-facing.
- Toda comunicação user-facing de leilão deve incluir aviso de risco: lance não é preço final; conferir edital, taxas/comissão, documentação e vistoria.
- Sources experimentais (ex.: Mega/Win/Superbid) não devem ser expostas ao usuário final.
- Envio real permanece sob controle operacional/admin (manual), com scheduler automático em dry-run nesta fase.

## Pilot monitoring

Use `/admin auctions pilot` como visão consolidada do piloto user-facing de leilões.

O comando é **somente leitura** e **não envia alertas**. Ele consolida:
- adoção (`buscas ativas`, `buscas com leilões`, `usuários com leilões`);
- segurança operacional de sources (`user_eligible`, `unsafe_user_eligible`, prontidão car);
- estado do scheduler (dry-run vs risco de envio automático real);
- últimos envios reais manuais e agregados de 24h;
- resumo de dry-run (última execução e prévias).

Fluxo recomendado continua:
1. `/admin auctions notify-run --source vip --limit-wishlists 5`
2. `/admin auctions preview-send`
3. `/admin auctions notify-run --source vip --limit-wishlists 5 --real`

`/admin auctions pilot` **não substitui** os guardrails: o scheduler automático real continua fora do fluxo recomendado nesta fase do piloto.
