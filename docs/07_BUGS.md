# Bugs — Status operacional e pendências

Atualizado em: 2026-05-25.  
Estado confrontado com a `main`.

> Este documento consolida o estado dos bugs mapeados na tranche de estabilização.  
> Ele não deve ser lido como lista de bugs abertos: a maioria dos itens abaixo já está corrigida, validada ou operacionalizada.  
> As pendências restantes são validação operacional, carga de dados e decisões controladas por feature flag.

---

## Visão executiva

| Grupo | Estado atual | Próximo passo real |
|---|---|---|
| BUG-01, BUG-02, BUG-03, BUG-04, BUG-05, BUG-08 | Corrigidos / validados | Manter regressão e operação normal |
| BUG-06 — cross-source dedupe | Implementado com feature flag, live OFF e shadow observável | Rodar janela em shadow e validar falsos positivos antes de live |
| BUG-07 — score_v2/FIPE | Score implementado com fallback + import/coverage FIPE | Carregar dados FIPE reais e validar coverage |

---

## Estado adicional confrontado com a `main`

- `/admin metrics` existe e não deve ser tratado como bug ou bloqueador técnico.
- `admin_handlers_metrics.py` cobre métricas básicas de beta: usuários, buscas, alertas, backlog, Free/Premium e sources 7d.
- O índice `ix_notifications_user_sent_today` está documentado como validado em PostgreSQL/Supabase real.
- Pagamento automático, aprovação 1-clique e trial não são bugs de runtime; são pendências de fluxo/produto em `02_FLUXO.md`, `05_PLAN.md` e `06_SUBSCRIPTION.md`.

---

## BUG-01 — `max_overflow` não passado ao `create_engine`

**Arquivo:** `app/db/session.py`

**Status:** corrigido.

`app/db/session.py` já aplica:

- `max_overflow=settings.db_max_overflow`;
- `pool_timeout=settings.db_pool_timeout` quando aplicável;
- `connect_args={"connect_timeout": int(settings.db_connect_timeout)}` para conexões não-SQLite;
- tratamento específico para SQLite sem parâmetros incompatíveis.

**Status operacional:** fechado.

---

## BUG-02 — Índice parcial de notifications enviado

**Arquivo:** `migrations/versions/f6a1b2c3d4e5_notifications_sent_at_index.py`

**Status:** resolvido e validado em banco real PostgreSQL/Supabase.

A migration cria em PostgreSQL:

```sql
CREATE INDEX ix_notifications_user_sent_today
ON notifications (user_id, sent_at)
WHERE status = 'sent';
```

Queries protegidas:

- `app/services/limits_service.py::count_sent_today`;
- `app/services/limits_service.py::count_notifications_sent_last_n_days`;
- leituras agregadas de alertas enviadas em `/admin metrics`.

**Status operacional:** fechado. Revalidar apenas se houver nova migration envolvendo `notifications`.

---

## BUG-03 — Scripts legados de cache/otimização removidos

**Arquivo:** `config/raspberry-pi/crontab`

**Status:** corrigido e concluído.

O fluxo oficial de limpeza operacional é:

```bash
/home/autohunter/autohunter/venv/bin/python /home/autohunter/autohunter/scripts/cleanup_operational_data.py --apply
```

Removidos:

```text
scripts/cache_manager.py
scripts/database_optimizer.py
```

**Status operacional:** fechado. Manter atenção a crescimento de dados/logs no Raspberry por rotinas novas.

---

## BUG-04 — Validação end-to-end de migrations em PostgreSQL real

**Status:** resolvido e validado em PostgreSQL/Supabase real.

Script read-only:

```text
scripts/validate_postgres_schema.py
```

Valida:

- conexão PostgreSQL;
- estado Alembic;
- colunas críticas de `car_listings`;
- índice partial de `notifications`.

Resultado já documentado historicamente:

```text
OK=8, WARNING=0, FAIL=0
```

**Status operacional:** fechado. Reexecutar antes/depois de deploys com migrations relevantes.

---

## BUG-05 — Filtros estruturados para `km`, `seller`, `body_type`, `doors`

**Status:** resolvido no comando oficial.

O backend já suporta:

- normalização/aliases em `normalize_wishlist_filter_input`;
- operadores e validação para filtros estruturados;
- aplicação em matching, matching fast e explicação de match.

Fechado no fluxo:

- `/wishlist filter` com ajuda atualizada;
- `/wishlist filter add` aceitando valor composto, incluindo `between 30000 90000`;
- mensagens de erro mais acionáveis;
- listagem textual com labels amigáveis.

**Status operacional:** fechado como bug. Evolução por botões é melhoria de UX, não correção.

---

## BUG-06 — Cross-source dedupe

**Status:** preparado com feature flag; live OFF; shadow observável.

O que está pronto na `main`:

- `cross_source_fingerprint` calculado no ingest/upsert;
- fingerprint persistido em `car_listings`;
- diagnóstico de colisões cross-source;
- runtime de dedupe integrado à fila de notifications;
- modo shadow registra o que seria suprimido sem alterar a fila;
- modo live só suprime se habilitado explicitamente;
- falhas na avaliação são isoladas;
- observabilidade admin disponível.

Flags esperadas:

```env
cross_source_dedupe_enabled=false
cross_source_dedupe_shadow_mode=true
cross_source_dedupe_window_days=30
```

Admin:

```text
/admin dedupe collisions [N]
/admin dedupe shadow [horas] [limite]
```

**Pendência real:** rodar shadow em produção/beta, revisar falsos positivos/falsos negativos e só então decidir live.

---

## BUG-07 — `score_v2` automotivo + FIPE operacional

**Status:** mecanismo fechado; carga real FIPE pendente de operação.

Implementado:

- componente `market_price` com fallback neutro;
- componente `fipe_price` com lookup opcional em `fipe_prices`;
- componente `rarity` conservador;
- componente `quality`;
- breakdown auditável;
- importador `scripts/import_fipe_prices.py`;
- exportador `scripts/export_missing_fipe_keys.py`;
- template `docs/examples/fipe_prices_template.csv`;
- guia `docs/FIPE_OPERATIONAL_LOAD.md`;
- diagnóstico `/admin fipe coverage`.

**Pendência real:** carregar dados FIPE confiáveis e validar coverage útil.

---

## BUG-08 — Chamada incompatível em `match_listings_for_active_wishlists`

**Arquivo:** `app/services/matching_service.py`

**Status:** corrigido.

A chamada incorreta `match_listing_to_wishlist(w, l).ok` foi corrigida para o contrato real:

```python
match_listing_to_wishlist(db, w, l)
```

**Status operacional:** fechado.

---

## Resumo por severidade/status

| Bug | Severidade | Estado na `main` | Pendência real |
|---|---|---|---|
| BUG-01 | Alta — escala | Corrigido | Nenhuma |
| BUG-02 | Alta — performance | Resolvido e validado | Nenhuma |
| BUG-03 | Média — operação | Corrigido | Monitorar rotinas novas |
| BUG-04 | Alta — estabilidade | Resolvido e validado | Revalidar em deploys com migration |
| BUG-05 | Média — produto | Resolvido no comando oficial | UX por botões é melhoria futura |
| BUG-06 | Alta sensibilidade operacional | Feature flag + shadow | Rodar shadow real antes de live |
| BUG-07 | Média — produto/dados | Score/FIPE implementados | Carregar FIPE real |
| BUG-08 | Alta — runtime | Corrigido | Nenhuma |

---

## Pendências abertas que não são bug de código

1. Dedupe live depende de observação real em shadow.
2. FIPE real depende de carga de dados confiável.
3. Pagamento/ativação Premium depende de fluxo de produto.
4. Trial depende de decisão comercial.
5. UX guiada por botões é evolução, não bug funcional.
6. Refactor de admin/settings é melhoria estrutural.
