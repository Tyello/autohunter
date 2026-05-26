# Planos — Estrutura e Evolução

Atualizado em: 2026-05-25.  
Estado confrontado com a `main`.

> Fonte de verdade atual: `app/services/plan_capabilities.py` + tabela `plans` para limites persistidos.  
> Produto atual: dois planos operacionais — Free e Premium.

---

## Estado atual do código

```python
PLAN_CODE_FREE = "free"
PLAN_CODE_PREMIUM = "premium"
```

A `main` implementa apenas dois códigos de plano reconhecidos pelo runtime:

- `free`
- `premium`

Qualquer documentação antiga com três tiers (`Free`, `Enthusiast`, `Pro`) deve ser tratada como proposta histórica, não como estado real do produto.

---

## Capacidades atuais

### Free

Estado em `app/services/plan_capabilities.py`:

```text
max_active_wishlists=2
max_tracked_total=1
max_tracked_slots_per_wishlist=3
tracking_auto_alerts=false
daily_notifications_per_wishlist=5
premium=false
```

Resumo user-facing:

- até 2 buscas salvas;
- até 1 anúncio rastreado no total;
- até 3 slots por wishlist, mas limitado pelo total do plano;
- sem alertas automáticos de tracking;
- 5 alertas/dia por busca.

### Premium

Estado em `app/services/plan_capabilities.py`:

```text
max_active_wishlists=15
max_tracked_total=5
max_tracked_slots_per_wishlist=3
tracking_auto_alerts=true
daily_notifications_per_wishlist=200
premium=true
launch_price_brl=5.99
future_price_brl=9.99
```

Resumo user-facing:

- até 15 buscas salvas;
- até 5 anúncios rastreados no total;
- até 3 rastreados por wishlist;
- alertas automáticos de tracking;
- 200 alertas/dia por busca;
- preço de lançamento tratado no código como R$ 5,99/mês;
- preço futuro tratado no código como R$ 9,99/mês.

---

## Observação sobre limites no banco

`resolve_plan_capabilities` usa a tabela `plans` para sobrescrever, quando existir:

- `max_wishlists`;
- `daily_alert_limit`.

Já os limites de tracking e preços de lançamento/futuro vêm hoje do fallback em `plan_capabilities.py`.

**Diretriz:** se a operação quiser mudar limite comercial, confirmar primeiro se o limite é DB-driven ou code-driven para evitar divergência entre `/plan`, `/upgrade` e regra real.

---

## Gap entre proposta de pricing e código

Se `docs/pricing.md` ou qualquer doc histórico falar em `Enthusiast` e `Pro`, isso não reflete a `main`.

**Decisão recomendada para lançamento:** manter dois planos.

Motivo:

- reduz fricção de decisão;
- simplifica suporte no beta;
- evita migrations/handlers prematuros;
- permite precificar melhor após dados reais de uso.

Adicionar tiers só depois de medir:

- quantas buscas usuários realmente criam;
- quantos rastreados usam;
- quantos alertas recebem;
- quanto aceitam pagar;
- quais features Premium realmente geram conversão.

---

## PLAN-01 — Trial de 7 dias automático

**Status:** aberto.

**Objetivo:** dar ao usuário novo a experiência completa antes de pedir dinheiro.

**Estado atual confrontado:** não há evidência de trial automático implementado na `main`.

Direção:

```text
novo usuário
→ cria subscription Premium trial por 7 dias
→ usa capacidades Premium no período
→ recebe avisos antes de terminar
→ volta para Free ao expirar se não pagar
```

Possível implementação:

```python
def create_trial_subscription(db, account_id):
    premium_plan = db.query(Plan).filter_by(code="premium").first()
    sub = Subscription(
        account_id=account_id,
        plan_id=premium_plan.id,
        status="active",
        source="trial",
        starts_at=now,
        ends_at=now + timedelta(days=7),
    )
```

**Atenção:** antes de ativar trial, decidir se ele é universal ou apenas para beta/founders.

---

## PLAN-02 — Founders

**Status:** proposta comercial, ainda depende de fluxo de ativação/pagamento.

**Objetivo:** validar disposição de pagamento antes do lançamento público amplo.

Direção recomendada:

- usar o mesmo `plan_id` Premium;
- marcar `Subscription.source = "founders"`;
- registrar metadata com preço, duração e operador;
- limitar vagas operacionalmente.

Exemplo de metadata:

```json
{
  "tier": "founders",
  "locked_price_brl": 149,
  "duration_months": 24,
  "activated_by": "admin"
}
```

**Importante:** não criar novo `plan_code` só para Founders enquanto o runtime está desenhado para `free|premium`.

---

## PLAN-03 — Ajuste de limites Free para conversão

**Status:** decisão pós-beta.

Estado atual Free:

| Limite | Atual |
|---|---:|
| Buscas salvas | 2 |
| Alertas/dia por busca | 5 |
| Rastreados totais | 1 |

Possível ajuste futuro:

| Limite | Proposto pós-beta |
|---|---:|
| Buscas salvas | 1 |
| Alertas/dia por busca | 3 |
| Rastreados totais | 0 ou 1 |

**Diretriz:** não apertar limite durante beta inicial sem métrica. Primeiro medir uso real via `/admin metrics` e feedback qualitativo.

---

## PLAN-04 — Modo silencioso

**Status:** aberto, pós-beta.

**Objetivo:** reduzir churn por alerta em horário ruim.

Direção:

- permitir janela de não perturbe por usuário;
- sender posterga envio para o fim da janela;
- feature Premium;
- configurar via Telegram.

Possível schema:

```text
users.quiet_hours_start
users.quiet_hours_end
users.timezone
```

**Critério:** não perder alerta; apenas postergar.

---

## Prioridade atual

| # | Item | Status | Momento |
|---|---|---|---|
| 1 | PLAN-01 — Trial 7 dias | Aberto | Beta/lançamento |
| 2 | PLAN-02 — Founders | Aberto | Após fluxo de pagamento/ativação |
| 3 | PLAN-03 — Limites Free | Aberto | Pós-beta, com dados |
| 4 | PLAN-04 — Modo silencioso | Aberto | Pós-beta |

---

## Próxima decisão de produto

Antes de mudar preço ou limite, fechar o fluxo de pagamento/ativação descrito em `06_SUBSCRIPTION.md`. Sem isso, plano existe no código, mas monetização ainda depende de operação manual.
