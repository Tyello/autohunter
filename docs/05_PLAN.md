# Planos — Estrutura e Evolução

Atualizado em: 2026-05-25.

> Documento dono de planos, limites, trial, Founders e pricing.  
> A implementação de ativação e cobrança fica em `06_SUBSCRIPTION.md`.

---

## Escopo deste documento

Este documento cobre:

- plano Free/Premium;
- limites e capacidades;
- preço e posicionamento;
- trial;
- Founders;
- decisões comerciais de plano.

| Assunto relacionado | Documento dono |
|---|---|
| Ativação Premium, webhook e aprovação admin | `06_SUBSCRIPTION.md` |
| Jornada de usuário | `02_FLUXO.md` |
| Lançamento e beta | `04_LAUNCH_PLAN.md` |
| Métricas operacionais | `08_EFICIENCIA.md` |

---

## Estado atual do código

A `main` reconhece dois códigos de plano:

```python
PLAN_CODE_FREE = "free"
PLAN_CODE_PREMIUM = "premium"
```

Qualquer documentação antiga com três tiers deve ser tratada como proposta histórica, não como estado real.

---

## Capacidades atuais

Fonte principal: `app/services/plan_capabilities.py`.

| Capacidade | Free | Premium |
|---|---:|---:|
| Buscas salvas | 2 | 15 |
| Rastreados totais | 1 | 5 |
| Rastreados por wishlist | até 3, limitado pelo total | 3 |
| Alertas automáticos de tracking | não | sim |
| Alertas/dia por busca | 5 | 200 |
| Preço lançamento | - | R$ 5,99/mês |
| Preço futuro | - | R$ 9,99/mês |

A tabela `plans` pode sobrescrever `max_wishlists` e `daily_alert_limit` via `resolve_plan_capabilities`. Os limites de tracking e preços vêm hoje do fallback em código.

---

## Diretriz de pricing

Manter dois planos no lançamento:

- Free;
- Premium.

Motivo:

- reduz fricção de decisão;
- simplifica suporte no beta;
- evita migrations e handlers prematuros;
- permite decidir novos tiers com dados reais.

Adicionar tiers só depois de medir uso real e conversão.

---

## PLAN-01 — Trial de 7 dias

**Status:** aberto.

**Objetivo:** permitir que novo usuário sinta valor do Premium antes de assinar.

Decisões pendentes:

- trial para todos ou apenas beta?
- exige cadastro de forma de pagamento?
- quantos dias?
- como comunicar queda para Free?
- trial pode virar Founders?

Direção técnica provável:

```text
subscription.source = trial
subscription.ends_at = now + 7 dias
plan = Premium
```

**Critério:** trial tem elegibilidade, duração, aviso e downgrade claros.

---

## PLAN-02 — Founders

**Status:** proposta comercial, dependente do fluxo de ativação.

**Objetivo:** validar disposição de pagamento antes do lançamento amplo.

Direção recomendada:

- usar o mesmo plano Premium;
- registrar origem como Founders;
- registrar metadata com preço, duração e operador;
- limitar vagas operacionalmente.

**Critério:** não criar novo `plan_code` só para Founders enquanto o runtime está desenhado para `free|premium`.

---

## PLAN-03 — Ajuste de limites Free

**Status:** decisão pós-beta.

| Limite | Atual | Possível pós-beta |
|---|---:|---:|
| Buscas salvas | 2 | 1 |
| Alertas/dia por busca | 5 | 3 |
| Rastreados totais | 1 | 0 ou 1 |

**Diretriz:** não apertar limite durante beta inicial sem métrica. Medir primeiro via `/admin metrics` e feedback qualitativo.

---

## PLAN-04 — Modo silencioso

**Status:** aberto, pós-beta.

**Objetivo:** reduzir churn por alerta em horário ruim.

Direção:

- janela de não perturbe por usuário;
- sender posterga envio para o fim da janela;
- feature Premium;
- configuração via Telegram.

**Critério:** não perder alerta; apenas postergar.

---

## Prioridade atual

| # | Item | Status | Momento |
|---|---|---|---|
| 1 | PLAN-01 — Trial 7 dias | Aberto | Beta/lançamento |
| 2 | PLAN-02 — Founders | Aberto | Após ativação sem gargalo |
| 3 | PLAN-03 — Limites Free | Aberto | Pós-beta, com dados |
| 4 | PLAN-04 — Modo silencioso | Aberto | Pós-beta |

---

## Próxima decisão de produto

Antes de alterar preço, trial ou limite, fechar o fluxo de ativação em `06_SUBSCRIPTION.md`. Sem isso, o plano existe, mas monetização ainda depende de operação manual.
