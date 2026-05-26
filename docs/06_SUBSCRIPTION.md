# Subscription — Pagamento e Ciclo de Vida

Atualizado em: 2026-05-25.  
Estado confrontado com a `main`.

> O modelo de assinatura existe e Premium pode ser ativado manualmente.  
> O fluxo de pagamento/ativação ainda não está fechado para escala.

---

## Estado atual

### Existe na `main`

- Modelo `Subscription` com campos para ciclo de vida:
  - `account_id`;
  - `plan_id`;
  - `status`;
  - `source`;
  - `starts_at`;
  - `ends_at`;
  - `current_period_start`;
  - `current_period_end`;
  - `cancel_at_period_end`;
  - `metadata_json`.
- Serviço `premium_subscription_service.py` com ativação/expiração/consulta de Premium.
- Job de expiração Premium no scheduler.
- `/upgrade` com oferta Premium e link Mercado Pago configurável.
- `/admin premium` para ativação manual/admin.
- `/admin metrics` para acompanhar usuários Free/Premium.

### Não existe na `main`

- Webhook Mercado Pago.
- Rota `app/web/routes_webhooks.py`.
- Serviço operacional `mercadopago_service.py`.
- Criação dinâmica de preferência de pagamento por usuário/período.
- Aprovação de comprovante em 1 clique por botão admin.
- Fluxo user-facing completo de avisos antes da expiração.
- Auditoria padronizada de ativações manuais no `metadata_json`.

---

## SUB-01 — Webhook Mercado Pago

**Status:** aberto.  
**Caminho principal para escala.**

### Fluxo técnico desejado

```text
1. Usuário toca Assinar Mensal/Anual no bot
2. Bot cria preferência de pagamento no Mercado Pago
3. Preferência recebe metadata {chat_id, plan_period, account_id?}
4. Bot envia URL de checkout ao usuário
5. Usuário paga
6. Mercado Pago envia POST /webhooks/mercadopago
7. App valida assinatura/origem do webhook
8. App busca detalhes do pagamento aprovado
9. App extrai metadata
10. App ativa Premium
11. Bot notifica usuário
12. Bot notifica admin
```

### Arquivos prováveis

```text
app/web/routes_webhooks.py
app/services/mercadopago_service.py
app/services/payment_activation_service.py
```

### Settings a adicionar

```python
mp_access_token: str | None = None
mp_webhook_secret: str | None = None
mp_webhook_url: str | None = None
mp_checkout_success_url: str | None = None
mp_checkout_failure_url: str | None = None
mp_checkout_pending_url: str | None = None
```

### Critérios de aceite

- Webhook rejeita assinatura inválida.
- Evento duplicado não cria múltiplas assinaturas ativas conflitantes.
- Pagamento aprovado ativa Premium correto.
- Pagamento pendente/rejeitado não ativa Premium.
- Usuário e admin são notificados.
- Testes cobrem aprovado, duplicado, inválido e pendente.
- Logs não expõem token, assinatura, documento ou dados sensíveis.

---

## SUB-02 — Aprovação em 1 clique

**Status:** aberto.  
**Fallback recomendado para beta.**

### Fluxo desejado

```text
1. Usuário envia comprovante ou mensagem de pagamento no chat
2. Bot identifica intenção de ativação Premium
3. Bot encaminha resumo para o admin
4. Admin recebe botões:
   [✅ Ativar Mensal] [✅ Ativar Anual] [❌ Recusar]
5. Admin toca no botão
6. Bot chama serviço de ativação Premium
7. Bot notifica usuário
8. Bot registra metadata operacional
```

### Handler provável

```text
app/bot/handlers_payment.py
```

### Callback sugerido

```text
ADMIN:PREMIUM_ACTIVATE:<period>:<telegram_chat_id>
ADMIN:PREMIUM_REFUSE:<telegram_chat_id>
```

### Critérios de aceite

- Apenas admin pode acionar botões.
- Callback inválido ou expirado não ativa assinatura.
- Ativação registra `source="manual"` ou `source="founders"` conforme caso.
- `metadata_json` registra operador, data e origem.
- Usuário recebe confirmação clara.
- Admin recebe confirmação da ação.

---

## SUB-03 — Lifecycle completo de expiração

**Status:** aberto.

**Hoje:** há expiração operacional, mas falta fluxo de comunicação user-facing completo.

### O que adicionar

```text
7 dias antes → aviso de renovação
1 dia antes → aviso final
no dia → downgrade + mensagem clara
```

### Serviço provável

```text
app/services/premium_expiry_notification_service.py
```

### Job provável

```text
app/scheduler/premium_expiry_warning_job.py
```

### Critérios de aceite

- Não envia aviso duplicado para a mesma assinatura/janela.
- Respeita subscription ativa e datas UTC.
- Não avisa subscriptions canceladas/expiradas indevidamente.
- Mensagem inclui CTA para renovar.
- Downgrade informa limites Free após expiração.

---

## SUB-04 — Auditoria de ativações

**Status:** aberto.

`metadata_json` já permite registrar rastreabilidade sem migration imediata.

### Metadata mínima recomendada

```json
{
  "activated_by": "admin",
  "activated_at": "2026-05-25T23:00:00Z",
  "admin_chat_id": 123456,
  "source": "manual",
  "period": "monthly",
  "payment_ref": null,
  "reason": "beta_activation"
}
```

### Critérios de aceite

- Toda ativação manual registra operador e data.
- Ativações por webhook registram payment id/preference id sem expor dados sensíveis.
- `/admin premium` ou comando equivalente permite consultar origem da assinatura.

---

## SUB-05 — Trial de 7 dias

**Status:** aberto, dependente de decisão de produto.

Trial pode usar `Subscription.source = "trial"` e `ends_at`, mas precisa de regra clara:

- todos os usuários novos recebem trial?
- apenas beta users?
- trial pode virar Founders?
- trial exige pagamento cadastrado ou não?

**Diretriz:** não implementar trial antes de decidir como ele aparece na jornada de upgrade e expiração.

---

## Prioridade atual

| # | Item | Status | Impacto |
|---|---|---|---|
| 1 | SUB-02 — Aprovação 1 clique | Aberto | Desbloqueia beta rápido |
| 2 | SUB-01 — Webhook Mercado Pago | Aberto | Escala pagamento |
| 3 | SUB-04 — Auditoria de ativações | Aberto | Rastreabilidade operacional |
| 4 | SUB-03 — Aviso de expiração | Aberto | Retenção Premium |
| 5 | SUB-05 — Trial 7 dias | Aberto | Ativação/conversão |

---

## Próxima PR recomendada

Implementar primeiro **SUB-02 — Aprovação em 1 clique**, porque reduz imediatamente o gargalo manual do beta sem exigir URL pública/webhook.

Depois, implementar **SUB-01 — Webhook Mercado Pago** para lançamento público amplo.
