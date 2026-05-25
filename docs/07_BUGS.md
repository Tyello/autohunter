# Bugs — Rastreamento e Pendências
> Bugs confirmados no código v2 que ainda não foram resolvidos ou precisam de validação.

---

## BUG-01 — `max_overflow` não passado ao `create_engine` (crítico para escala)

**Arquivo:** `app/db/session.py`

**Status:** corrigido no código atual.

**Nota de validação:** `app/db/session.py` já aplica `max_overflow=settings.db_max_overflow` e `connect_args={"connect_timeout": int(settings.db_connect_timeout)}` para conexões não-SQLite.

**Impacto histórico:** sem a correção, o pool poderia abrir mais conexões do que o banco suporta sob carga.

---

## BUG-02 — Index `notifications(user_id, sent_at WHERE status='sent')` não confirmado

**Arquivo:** `migrations/versions/f6a1b2c3d4e5_notifications_sent_at_index.py`

**Status:** resolvido e validado em banco real (PostgreSQL/Supabase).

**Nota de validação:** a migration `f6a1b2c3d4e5_notifications_sent_at_index.py` já cria em PostgreSQL o índice:

`ix_notifications_user_sent_today ON notifications (user_id, sent_at) WHERE status = 'sent'`

`count_sent_today` faz:

```sql
SELECT COUNT(*) FROM notifications
WHERE user_id = $1
  AND status = 'sent'
  AND sent_at >= now() - interval '24 hours'
```

Sem `WHERE status='sent'` no índice, esse filtro faz varredura parcial.

**Validação executada (banco real):**
```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'notifications'
  AND indexname LIKE '%sent%';
```

**Resultado confirmado:** `ix_notifications_user_sent_today` é índice partial com `WHERE status = 'sent'` no banco real, conforme validação do script `scripts/validate_postgres_schema.py` (OK).

---

## BUG-03 — Scripts legados de cache/otimização removidos (ARCH-06)

**Arquivo:** `config/raspberry-pi/crontab`

**Status:** corrigido e concluído.

**Correção aplicada:** removidas referências a scripts legados e consolidada limpeza operacional em:

```bash
/home/autohunter/autohunter/venv/bin/python /home/autohunter/autohunter/scripts/cleanup_operational_data.py --apply
```

**Validação operacional contínua:**
```bash
grep -E "cache_manager|database_optimizer" config/raspberry-pi/crontab
```

---


## BUG-08 — Chamada incompatível em `match_listings_for_active_wishlists` (P0 runtime)

**Arquivo:** `app/services/matching_service.py`

**Problema confirmado:** havia chamada incorreta `match_listing_to_wishlist(w, l).ok` dentro do loop de match ativo.

- assinatura real exige `db` como primeiro parâmetro;
- retorno é `bool`, sem atributo `.ok`.

**Status:** corrigido nesta branch para `match_listing_to_wishlist(db, w, l)`.

**Cobertura de regressão:** adicionada para garantir execução sem `TypeError`/`AttributeError` e inclusão de listing compatível no resultado.

---

## BUG-04 — Validação end-to-end de migrations em PostgreSQL real

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P0 aberto

**Status:** resolvido e validado em PostgreSQL/Supabase real.

**Mudança desta PR:** novo script read-only `scripts/validate_postgres_schema.py` valida conexão PostgreSQL, estado Alembic, colunas críticas de `car_listings` e índice partial de `notifications`.

**Importante:** o script **não** executa `alembic upgrade head` automaticamente e não aplica alterações destrutivas.

**Validação executada (resultado):**
```bash
python scripts/validate_postgres_schema.py
```

**Resultado confirmado em banco real:**
- conexão PostgreSQL estabelecida e dialect confirmado;
- Alembic com head único `aa21b3c4d5e6`;
- revision atual do banco em `aa21b3c4d5e6` (alinhada ao head esperado);
- `car_listings` contém `doors`, `body_type`, `cross_source_fingerprint`;
- resumo da execução: `OK=8, WARNING=0, FAIL=0`.

---

## BUG-05 — Filtros estruturados para `km`, `seller`, `body_type`, `doors` (resolvido via comando)

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P1 aberto

**Status atual:** resolvido para fluxo por comando (`/wishlist filter ...`) com UX atualizada, parsing composto e testes cobrindo normalização + matching.

**O que já existia no backend (confirmado):**
- normalização/aliases em `normalize_wishlist_filter_input` para `mileage_km`, `seller_type`, `body_type`, `doors`;
- validação de operadores e valores para esses campos;
- aplicação de filtros em matching (`_apply_filters`, `_apply_filters_fast`, `explain_match`).

**O que foi fechado nesta PR (BUG-05):**
- help do `/wishlist filter` atualizado com campos e exemplos de `km`, `vendedor`, `carroceria`, `portas`;
- handler legado `/wishlist filter add` agora aceita valor composto (`value = " ".join(args[5:])`), incluindo `between 30000 90000`;
- mensagens de uso/erro tornadas acionáveis com exemplos diretos;
- listagem textual de filtros no comando legado com labels amigáveis (`km`, `vendedor`, `carroceria`, `portas`) sem alterar persistência.

**Nota de produto:** fluxo guiado por botões para filtro estruturado completo pode evoluir depois; BUG-05 permanece **resolvido** no comando oficial já funcional.

---

## BUG-06 — Cross-source dedupe não funcional

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P1 aberto

**Status atual:** **Dedupe funcional preparado com feature flag (supressão default OFF)**.

**O que está ativo agora:**
- fingerprint `cross_source_fingerprint` é calculado no ingest/upsert com sinais estruturados conservadores (`make`, `model`, `year`, buckets de `price` e `mileage_km`, com `version/transmission` opcionais quando presentes);
- fingerprint é persistido em `car_listings` sem alterar a política atual de matching/notificação;
- existe consulta de diagnóstico para observar colisões cross-source (mesmo fingerprint em mais de uma source).

**Importante:** a supressão real segue desativada por padrão (`cross_source_dedupe_enabled=false`).  
Com `enabled=true` + `shadow_mode=true`, o runtime apenas registra o que **seria** suprimido; não altera fila.  
Só existe supressão efetiva quando `enabled=true` + `shadow_mode=false`.

**Observabilidade admin:**
- `/admin dedupe collisions [N]` exibe colisões por fingerprint e estado das flags (`suppression enabled`, `shadow mode`, `window`).
- `/admin dedupe shadow [horas] [limite]` exibe relatório de eventos shadow/live (`shadow hit`, `suppressed`, `evaluation error`) com top fingerprints, top pares de source e amostras para revisão operacional.

**Próximo passo (operação controlada):** ativar dedupe live somente após janela de observação em shadow + revisão de `/admin dedupe collisions` e logs de shadow para calibrar falso positivo/falso negativo.

---

## BUG-07 — `score_v2` automotivo incompleto (P2 incremental)

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P2 aberto

**Problema original:** `score_v2` existe no modelo `Notification` e é persistido, mas a lógica de score automotivo (FIPE, mercado, raridade) estava incompleta.

**Implementado na P2:**
- componente `market_price` com delta vs mediana de mercado quando `market_stats_cohorts` possui amostra mínima (fallback neutro quando não possui);
- componente `fipe_price` com lookup opcional em `fipe_prices` (sem integração externa) e fallback neutro quando ausente;
- componente `rarity` leve/conservador com fallback neutro quando não há amostra mínima;
- componente `quality` com sinais baratos (preço, km, localização, imagem, URL, make/model/year);
- breakdown auditável com componentes nomeados e alias `price` mantido por compatibilidade.

**Pendência real pós-P2:**
- mecanismo operacional de import/upsert e coverage de `fipe_prices` implementado; carga real de dados FIPE ainda depende de operação.
- score permanece estável via fallback neutro quando FIPE não está disponível.

---

## Resumo por severidade

| Bug | Severidade | Esforço | Status |
|---|---|---|---|
| BUG-01 | Alta — escala | Trivial (1 linha) | Corrigido |
| BUG-02 | Alta — performance | Baixo | Resolvido e validado em banco real |
| BUG-03 | Média — operação | Baixo | Corrigido |
| BUG-08 | Alta — runtime | Baixo | Corrigido |
| BUG-04 | Alta — estabilidade | Médio | Resolvido e validado em PostgreSQL/Supabase real |
| BUG-05 | Média — produto | Médio (handlers + matching) | Resolvido (comando) |
| BUG-06 | Baixa — produto | Alto (implementar + observar) | Modo diagnóstico implementado |
| BUG-07 | Média — produto | Alto (validar scoring) | Parcialmente resolvido (P2) |
