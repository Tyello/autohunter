# Bugs — Status operacional e pendências

> Este documento consolida o estado dos bugs mapeados na tranche de estabilização.  
> Ele não deve ser lido como uma lista de bugs ainda abertos: a maioria dos itens abaixo já está corrigida ou operacionalizada.  
> As pendências restantes são principalmente validação operacional em ambiente real, carga de dados e decisões controladas por feature flag.

---

## Visão executiva

| Grupo | Estado atual | Próximo passo real |
|---|---|---|
| BUG-01, BUG-02, BUG-03, BUG-04, BUG-05, BUG-08 | Corrigidos / validados | Manter regressão e operação normal |
| BUG-06 — cross-source dedupe | Implementado com feature flag, live OFF e shadow observável | Rodar janela em shadow e validar falsos positivos antes de live |
| BUG-07 — score_v2/FIPE | Score implementado com fallback + import/coverage FIPE | Carregar dados FIPE reais e validar coverage |

---

## BUG-01 — `max_overflow` não passado ao `create_engine` (crítico para escala)

**Arquivo:** `app/db/session.py`

**Status:** corrigido no código atual.

**Nota de validação:** `app/db/session.py` já aplica `max_overflow=settings.db_max_overflow` e `connect_args={"connect_timeout": int(settings.db_connect_timeout)}` para conexões não-SQLite.

**Impacto histórico:** sem a correção, o pool poderia abrir mais conexões do que o banco suporta sob carga.

**Status operacional:** fechado. Manter apenas cobertura/regressão de configuração de DB.

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

**Status operacional:** fechado. Revalidar apenas se houver nova migration envolvendo `notifications`.

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

**Status operacional:** fechado. Manter atenção a crescimento de dados/logs no Raspberry por rotinas novas.

---

## BUG-08 — Chamada incompatível em `match_listings_for_active_wishlists` (P0 runtime)

**Arquivo:** `app/services/matching_service.py`

**Problema confirmado:** havia chamada incorreta `match_listing_to_wishlist(w, l).ok` dentro do loop de match ativo.

- assinatura real exige `db` como primeiro parâmetro;
- retorno é `bool`, sem atributo `.ok`.

**Status:** corrigido na main para `match_listing_to_wishlist(db, w, l)`.

**Cobertura de regressão:** adicionada para garantir execução sem `TypeError`/`AttributeError` e inclusão de listing compatível no resultado.

**Status operacional:** fechado.

---

## BUG-04 — Validação end-to-end de migrations em PostgreSQL real

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P0 histórico

**Status:** resolvido e validado em PostgreSQL/Supabase real.

**Mudança implementada:** script read-only `scripts/validate_postgres_schema.py` valida conexão PostgreSQL, estado Alembic, colunas críticas de `car_listings` e índice partial de `notifications`.

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

**Status operacional:** fechado. Reexecutar o script antes/depois de deploys com migrations relevantes.

---

## BUG-05 — Filtros estruturados para `km`, `seller`, `body_type`, `doors`

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P1 histórico

**Status atual:** resolvido para fluxo por comando (`/wishlist filter ...`) com UX atualizada, parsing composto e testes cobrindo normalização + matching.

**O que já existia no backend (confirmado):**

- normalização/aliases em `normalize_wishlist_filter_input` para `mileage_km`, `seller_type`, `body_type`, `doors`;
- validação de operadores e valores para esses campos;
- aplicação de filtros em matching (`_apply_filters`, `_apply_filters_fast`, `explain_match`).

**O que foi fechado:**

- help do `/wishlist filter` atualizado com campos e exemplos de `km`, `vendedor`, `carroceria`, `portas`;
- handler legado `/wishlist filter add` aceita valor composto (`value = " ".join(args[5:])`), incluindo `between 30000 90000`;
- mensagens de uso/erro tornadas acionáveis com exemplos diretos;
- listagem textual de filtros no comando legado com labels amigáveis (`km`, `vendedor`, `carroceria`, `portas`) sem alterar persistência.

**Nota de produto:** fluxo guiado por botões para filtro estruturado completo pode evoluir depois; BUG-05 permanece **resolvido** no comando oficial já funcional.

**Status operacional:** fechado como bug. Evolução por botões deve ser tratada como melhoria de UX, não correção.

---

## BUG-06 — Cross-source dedupe

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P1 histórico

**Status atual:** **dedupe funcional preparado com feature flag; live OFF por padrão; shadow observável**.

**O que está pronto na main:**

- fingerprint `cross_source_fingerprint` é calculado no ingest/upsert com sinais estruturados conservadores (`make`, `model`, `year`, buckets de `price` e `mileage_km`, com `version/transmission` opcionais quando presentes);
- fingerprint é persistido em `car_listings` sem alterar a política atual de matching/notificação;
- existe consulta de diagnóstico para observar colisões cross-source (mesmo fingerprint em mais de uma source);
- runtime de dedupe está integrado à fila de notifications com feature flag;
- modo shadow registra o que seria suprimido sem alterar a fila;
- modo live suprime apenas se ativado explicitamente;
- falhas na avaliação de dedupe são isoladas para não quebrar enqueue;
- observabilidade admin disponível.

**Flags atuais esperadas:**

```env
cross_source_dedupe_enabled=false
cross_source_dedupe_shadow_mode=true
cross_source_dedupe_window_days=30
```

**Importante:** a supressão real segue desativada por padrão (`cross_source_dedupe_enabled=false`).  
Com `enabled=true` + `shadow_mode=true`, o runtime apenas registra o que **seria** suprimido; não altera fila.  
Só existe supressão efetiva quando `enabled=true` + `shadow_mode=false`.

**Observabilidade admin:**

- `/admin dedupe collisions [N]` exibe colisões por fingerprint e estado das flags (`suppression enabled`, `shadow mode`, `window`).
- `/admin dedupe shadow [horas] [limite]` exibe relatório de eventos shadow/live (`shadow hit`, `suppressed`, `evaluation error`) com top fingerprints, top pares de source e amostras para revisão operacional.

**Próximo passo operacional:**

1. ativar dedupe em shadow no ambiente real;
2. rodar por alguns dias;
3. revisar `/admin dedupe shadow`;
4. revisar `/admin dedupe collisions`;
5. calibrar falsos positivos/falsos negativos;
6. só então decidir se vale ligar live (`cross_source_dedupe_shadow_mode=false`).

**Status operacional:** preparado, mas **não considerar live concluído** até haver evidência real de shadow.

---

## BUG-07 — `score_v2` automotivo + FIPE operacional

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P2 histórico

**Problema original:** `score_v2` existia no modelo `Notification` e era persistido, mas a lógica automotiva (FIPE, mercado, raridade) estava incompleta.

**Implementado na P2:**

- componente `market_price` com delta vs mediana de mercado quando `market_stats_cohorts` possui amostra mínima (fallback neutro quando não possui);
- componente `fipe_price` com lookup opcional em `fipe_prices` (sem integração externa) e fallback neutro quando ausente;
- componente `rarity` leve/conservador com fallback neutro quando não há amostra mínima;
- componente `quality` com sinais baratos (preço, km, localização, imagem, URL, make/model/year);
- breakdown auditável com componentes nomeados e alias `price` mantido por compatibilidade.

**Status atual:** **score v2 implementado com fallback; import/coverage FIPE implementado; carga real de dados FIPE pendente de operação**.

**O que está pronto na main:**

- `score_v2` usa dados de mercado/FIPE/raridade quando disponíveis;
- fallback neutro evita instabilidade quando faltam dados;
- importador operacional existe (`scripts/import_fipe_prices.py`);
- template CSV existe (`docs/examples/fipe_prices_template.csv`);
- guia operacional existe (`docs/FIPE_OPERATIONAL_LOAD.md`);
- exportador read-only de chaves ausentes existe (`scripts/export_missing_fipe_keys.py`);
- cobertura admin existe (`/admin fipe coverage`);
- handler `/admin fipe` está isolado em módulo dedicado.

**Clarezas importantes:**

- a fórmula/base do score não foi alterada pelo import FIPE;
- o import apenas alimenta dados de referência para o componente FIPE já previsto;
- sem carga FIPE real suficiente, o score continua estável por fallback neutro;
- o projeto não integra API externa FIPE nem scraping de FIPE neste fluxo.

**Próximo passo operacional:**

1. rodar `/admin fipe coverage`;
2. exportar chaves ausentes com `scripts/export_missing_fipe_keys.py`;
3. preencher CSV com fonte confiável;
4. rodar dry-run com `scripts/import_fipe_prices.py`;
5. aplicar com `--apply`;
6. rodar `/admin fipe coverage` novamente para confirmar avanço.

**Status operacional:** mecanismo fechado; pendente executar carga real e validar cobertura útil.

---

## Resumo por severidade/status

| Bug | Severidade | Estado na main | Pendência real |
|---|---|---|---|
| BUG-01 | Alta — escala | Corrigido | Nenhuma |
| BUG-02 | Alta — performance | Resolvido e validado em banco real | Nenhuma |
| BUG-03 | Média — operação | Corrigido | Monitorar rotinas novas de limpeza/log |
| BUG-08 | Alta — runtime | Corrigido | Nenhuma |
| BUG-04 | Alta — estabilidade | Resolvido e validado em PostgreSQL/Supabase real | Revalidar em deploys com migration |
| BUG-05 | Média — produto | Resolvido no comando oficial | Evolução guiada por botões é melhoria futura |
| BUG-06 | Baixa — produto / alta sensibilidade operacional | Preparado com feature flag; live OFF; shadow observável | Rodar shadow real antes de live |
| BUG-07 | Média — produto/dados | Score v2 + import/coverage FIPE implementados | Carregar dados FIPE reais e validar coverage |

---

## Pendências abertas que não são mais “bug de código”

1. **Dedupe live:** depende de observação real em shadow e decisão operacional.
2. **FIPE real:** depende de carga de dados confiável no ambiente operacional.
3. **UX guiada por botões:** melhoria de produto, não bug.
4. **Refactor de admin/settings:** melhoria estrutural, não bug funcional.
5. **Cron/systemd externo no Raspberry:** decisão operacional; o scheduler interno já existe para os fluxos implementados.
