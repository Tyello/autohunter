# Bugs — Status operacional e pendências

Atualizado em: 2026-05-25.

> Documento dono de bugs, correções, validações técnicas e pendências classificadas como defeito.  
> Produto, assinatura, UX, arquitetura e eficiência têm documentos próprios.

---

## Escopo deste documento

Este documento cobre:

- bugs corrigidos;
- validações técnicas;
- pendências que ainda parecem defeito;
- itens que não devem ser reabertos como bug.

| Assunto relacionado | Documento dono |
|---|---|
| Eficiência, carga e Raspberry | `08_EFICIENCIA.md` |
| Arquitetura/refactor | `03_ARQUITETURA.md` |
| Pagamento e assinatura | `06_SUBSCRIPTION.md` |
| Planos/trial/Founders | `05_PLAN.md` |
| UX/copy | `01_UX.md` |

---

## Visão executiva

| Grupo | Estado atual | Próximo passo real |
|---|---|---|
| BUG-01, BUG-02, BUG-03, BUG-04, BUG-05, BUG-08 | Corrigidos / validados | Manter regressão e operação normal |
| BUG-06 — cross-source dedupe | Implementado com feature flag, live OFF e shadow observável | Rodar shadow real antes de live |
| BUG-07 — score_v2/FIPE | Score implementado com fallback + import/coverage FIPE | Carregar dados FIPE reais e validar coverage |

---

## Fechados / não reabrir

### BUG-01 — Pool SQLAlchemy

**Status:** corrigido.

`app/db/session.py` já aplica `max_overflow`, `pool_timeout`, `connect_timeout` e tratamento específico para SQLite.

### BUG-02 — Índice parcial de notifications

**Status:** resolvido e validado em PostgreSQL/Supabase.

Índice:

```sql
ix_notifications_user_sent_today
ON notifications (user_id, sent_at)
WHERE status = 'sent'
```

### BUG-03 — Scripts legados de cache/otimização

**Status:** removidos/consolidados.

Fluxo oficial:

```text
scripts/cleanup_operational_data.py --apply
```

### BUG-04 — Validação PostgreSQL/Alembic

**Status:** resolvido e validado com `scripts/validate_postgres_schema.py`.

### BUG-05 — Filtros estruturados

**Status:** resolvido no comando oficial.

Inclui km, seller, body_type, doors, parsing composto e matching.

### BUG-08 — Chamada incompatível em matching ativo

**Status:** corrigido.

Contrato correto:

```python
match_listing_to_wishlist(db, wishlist, listing)
```

---

## BUG-06 — Cross-source dedupe

**Status:** preparado com feature flag; live OFF; shadow observável.

Pronto:

- fingerprint calculado e persistido;
- diagnóstico de colisões;
- runtime integrado à fila de notificações;
- modo shadow;
- modo live protegido por flag;
- falhas isoladas.

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

**Pendência real:** rodar shadow em produção/beta e avaliar falso positivo antes de live.

---

## BUG-07 — `score_v2` automotivo + FIPE operacional

**Status:** mecanismo fechado; carga real FIPE pendente.

Implementado:

- componentes market/FIPE/raridade/quality;
- fallback neutro;
- breakdown auditável;
- importador FIPE;
- exportador de chaves ausentes;
- template CSV;
- guia operacional;
- `/admin fipe coverage`.

**Pendência real:** carregar dados FIPE confiáveis e validar coverage útil.

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

## Não classificar como bug

- Pagamento/ativação Premium manual: pendência de fluxo em `06_SUBSCRIPTION.md`.
- Trial: decisão de plano em `05_PLAN.md`.
- UX guiada por botões: melhoria de UX em `01_UX.md`.
- Refactor admin/settings: arquitetura em `03_ARQUITETURA.md`.
- Teste de carga Raspberry: eficiência em `08_EFICIENCIA.md`.
- `/admin metrics` v1: já concluído.

- Decisão 2026-05: opção 2 adotada (base local mensal). API externa não será chamada em score/wishlist; CSV manual permanece fallback.
