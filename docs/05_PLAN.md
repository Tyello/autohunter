# Planos — Estrutura e Evolução
> Estado atual: Free e Premium no código. Pricing doc (`docs/pricing.md`) define 3 tiers (Free, Enthusiast, Pro) mas o código implementa apenas 2 (Free, Premium).
> Este documento alinha código, produto e estratégia.

---

## Estado atual do código

```python
PLAN_CODE_FREE = "free"
PLAN_CODE_PREMIUM = "premium"
```

**Limites Free (código):**
- 2 wishlists salvas
- 1 anúncio rastreado total
- 5 alertas/dia por busca
- Sem alertas automáticos de tracking

**Limites Premium (código):**
- 15 wishlists salvas
- 5 anúncios rastreados total (3 por wishlist)
- 200 alertas/dia por busca
- Alertas automáticos de tracking

---

## Gap entre `pricing.md` e o código

O `pricing.md` define 3 tiers (Free + Enthusiast + Pro) mas o código tem 2. O tier "Enthusiast" (R$ 9,90) e "Pro" (R$ 19,90) não existem no banco, nem nas migrations, nem nos handlers.

**Decisão recomendada:** manter 2 planos para o lançamento. Free e Premium. Adicionar tiers só após ter dados reais de uso e disposição de pagamento dos beta users. Tentar vender 3 opções antes de ter produto validado aumenta fricção de decisão sem benefício.

---

## PLAN-01 — Trial de 7 dias automático

**Objetivo:** dar ao usuário novo a experiência completa antes de pedir dinheiro.

**Como funciona:**
- Ao criar conta, subscription criada automaticamente com `source="trial"` e `ends_at = now() + 7 days`
- Usuário tem limites de Premium durante o trial
- Aviso nos dias 5, 6 e 7
- Downgrade automático para Free ao expirar

**Schema:** já suportado pelo modelo `Subscription` (campo `source` e `ends_at`)

**Migration:** não necessária — só lógica no `premium_subscription_service.py`

```python
def create_trial_subscription(db, account_id: UUID):
    premium_plan = db.query(Plan).filter_by(code="premium").first()
    sub = Subscription(
        account_id=account_id,
        plan_id=premium_plan.id,
        status="active",
        source="trial",
        starts_at=datetime.now(UTC),
        ends_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(sub)
    db.commit()
```

---

## PLAN-02 — Founders: plano especial de lançamento

**Objetivo:** validar disposição de pagamento antes do lançamento público. 20 vagas.

**Definição:**
- Preço: R$ 149/ano (equivale a R$ 12,42/mês)
- Duração: 24 meses (preço travado)
- Benefício extra: acesso a canal privado de feedback

**Como implementar sem criar novo plan_code:**
- Criar subscription com `source="founders"` e `ends_at = now() + 24 months`
- `metadata_json = {"tier": "founders", "locked_price": 149}`
- Usar o mesmo `plan_id` do Premium

**Handler de ativação:**
```
/admin premium activate <chat_id> founders
```

**Limite de vagas:** checar com `SELECT COUNT(*) FROM subscriptions WHERE source='founders'` antes de ativar.

---

## PLAN-03 — Ajuste de limites Free para conversão

**Estado atual:** Free tem 2 buscas e 5 alertas/dia. É generoso o suficiente para nunca precisar de Premium para uso casual.

**Proposta para aumentar pressão de conversão:**

| Limite | Atual | Proposto |
|---|---|---|
| Buscas salvas | 2 | 1 |
| Alertas/dia | 5 | 3 |
| Rastreados | 1 | 0 |

Com 1 busca e 3 alertas, o usuário que busca mais de um modelo ou quer mais cobertura sente o limite rápido. O rastreamento zero garante que qualquer usuário que queira acompanhar preço precisa do Premium.

**Quando fazer:** após beta. Não mudar limites enquanto está testando produto — confunde análise de uso.

**Como mudar:** update no banco, não no código:
```sql
UPDATE plans SET max_wishlists = 1 WHERE code = 'free';
```
Os limites são lidos do banco via `Plan`, não hardcoded.

---

## PLAN-04 — Modo silencioso (horário de não-disturbar)

**Objetivo:** Premium feature que reduz churn de usuários que recebem alertas de madrugada.

**Implementação:**
- Campo `users.quiet_hours_start` e `users.quiet_hours_end` (nullable)
- Sender verifica antes de enviar: se horário atual está no intervalo, adicionar à fila com `next_attempt_at = quiet_end`
- Configurável via `/settings silencioso`

**Disponível apenas para:** Premium

---

## Prioridade

| # | Item | Semana | Impacto |
|---|---|---|---|
| PLAN-01 | Trial 7 dias | 1 | Ativação e conversão |
| PLAN-02 | Founders | 2 | Validação comercial |
| PLAN-03 | Limites Free mais apertados | pós-beta | Pressão de conversão |
| PLAN-04 | Modo silencioso | pós-beta | Retenção Premium |
