# Subscription — Pagamento e Ciclo de Vida

Atualizado em: 2026-05-25.

> Documento dono de ativação Premium, cobrança, ciclo de vida de assinatura e auditoria.  
> Regras comerciais de plano, trial e Founders ficam em `05_PLAN.md`.

---

## Escopo deste documento

Este documento cobre:

- ativação Premium;
- webhook Mercado Pago;
- aprovação admin em 1 clique;
- expiração e renovação;
- auditoria de ativações.

| Assunto relacionado | Documento dono |
|---|---|
| Limites, preço, trial e Founders | `05_PLAN.md` |
| Jornada de usuário | `02_FLUXO.md` |
| Lançamento e beta | `04_LAUNCH_PLAN.md` |
| Métricas de conversão | `08_EFICIENCIA.md` |

---

## Estado atual confrontado com a `main`

### Existe

- Modelo `Subscription` com campos de ciclo de vida.
- Serviço de ativação/expiração/consulta Premium.
- Job de expiração Premium.
- `/upgrade` com oferta Premium e link configurável.
- `/admin premium` para ativação manual.
- `/admin metrics` para leitura Free/Premium.

### Não existe

- Webhook Mercado Pago.
- Rota `app/web/routes_webhooks.py`.
- Serviço operacional de Mercado Pago.
- Preferência de pagamento dinâmica por usuário/período.
- Aprovação de comprovante por botão admin.
- Avisos user-facing antes da expiração.
- Auditoria padronizada de ativações manuais.

---

## SUB-01 — Webhook Mercado Pago

**Status:** aberto.  
**Caminho principal para escala.**

Fluxo desejado:

```text
usuário escolhe assinatura
→ bot cria checkout com metadata
→ usuário paga
→ Mercado Pago chama webhook
→ app valida evento
→ app ativa Premium
→ usuário e admin são notificados
```

Arquivos prováveis:

```text
app/web/routes_webhooks.py
app/services/mercadopago_service.py
app/services/payment_activation_service.py
```

Critérios:

- rejeitar evento inválido;
- não duplicar assinatura em evento repetido;
- ativar apenas pagamento aprovado;
- notificar usuário e admin;
- não expor tokens ou dados sensíveis em logs.

---

## SUB-02 — Aprovação admin em 1 clique

**Status:** aberto.  
**Fallback recomendado para beta.**

Fluxo desejado:

```text
usuário envia comprovante
→ bot manda resumo ao admin
→ admin toca em ativar ou recusar
→ bot ativa Premium ou informa recusa
→ metadata registra operador e origem
```

Handler provável:

```text
app/bot/handlers_payment.py
```

Critérios:

- apenas admin aciona botões;
- callback inválido não ativa assinatura;
- metadata registra operador, data e origem;
- usuário recebe confirmação clara.

---

## SUB-03 — Avisos de expiração

**Status:** aberto.

Fluxo desejado:

```text
7 dias antes → aviso de renovação
1 dia antes → aviso final
no dia → downgrade + mensagem clara
```

Critérios:

- sem aviso duplicado;
- respeita datas UTC e status ativo;
- inclui CTA de renovação;
- downgrade informa limites Free.

---

## SUB-04 — Auditoria de ativações

**Status:** aberto.

`metadata_json` já permite rastreabilidade sem migration imediata.

Metadata mínima:

```text
activated_by
activated_at
admin_chat_id
source
period
payment_ref
reason
```

Critérios:

- ativação manual registra operador e data;
- ativação por webhook registra payment/preference id sem expor dado sensível;
- admin consegue consultar origem da assinatura.

---

## Prioridade atual

| # | Item | Status | Impacto |
|---|---|---|---|
| 1 | SUB-02 — Aprovação 1 clique | Aberto | Desbloqueia beta rápido |
| 2 | SUB-01 — Webhook Mercado Pago | Aberto | Escala pagamento |
| 3 | SUB-04 — Auditoria de ativações | Aberto | Rastreabilidade operacional |
| 4 | SUB-03 — Aviso de expiração | Aberto | Retenção Premium |

---

## Próxima PR recomendada

Implementar primeiro **SUB-02 — Aprovação em 1 clique**, porque reduz imediatamente o gargalo manual do beta sem exigir URL pública/webhook.

Depois, implementar **SUB-01 — Webhook Mercado Pago** para lançamento público amplo.
