# Fluxo — Melhorias de Jornada do Usuário
> Gaps identificados nos fluxos de `USER_FLOWS.md` e `UX_FLOW.md` após a implementação do bloco UX anterior.

---

## FLOW-01 — Pagamento: fluxo inexistente (bloqueador de lançamento)

**Estado atual:** usuário toca em "Assinar", recebe link do Mercado Pago, paga, envia comprovante manualmente, espera ativação manual do admin. Não é um fluxo — é uma sequência de passos manuais.

**O que implementar:**

**Opção A — Webhook Mercado Pago (caminho principal):**

```
usuário toca "Assinar Mensal/Anual"
→ bot gera preferência de pagamento com metadata {chat_id, plan, period}
→ bot envia link de checkout personalizado
→ usuário paga
→ MP envia webhook POST /webhooks/mercadopago
→ app valida assinatura do webhook
→ extrai chat_id do metadata
→ chama premium_subscription_service.activate(...)
→ bot notifica usuário: "✅ Premium ativado até DD/MM/YYYY"
→ bot notifica admin: "💰 Nova assinatura: @username, mensal"
```

**Rota a criar:** `app/web/routes_webhooks.py::handle_mercadopago_webhook`

**SDK:** `mercadopago` (pip install mercadopago)

**Opção B — Aprovação admin em 1 clique (fallback para beta):**

```
usuário envia comprovante no chat
→ bot detecta imagem/documento + texto com "comprovante"/"paguei"
→ bot encaminha para admin com botões:
   [✅ Ativar Mensal] [✅ Ativar Anual] [❌ Recusar]
→ admin toca no botão
→ bot ativa Premium automaticamente
→ bot notifica usuário
```

**Handler a criar:** `app/bot/handlers_payment.py`

**Critério:** Premium ativado sem comando manual digitado pelo admin.

---

## FLOW-02 — Fluxo de expiração do Premium

**Estado atual:** o job `premium_expiration_job` existe mas o usuário não recebe aviso antes de expirar. Descobre quando tenta usar algo que era Premium.

**O que implementar:**

```
7 dias antes da expiração:
→ bot envia: "Seu Premium expira em 7 dias. Renove para continuar..."
→ botão: [Renovar]

1 dia antes:
→ bot envia: "Último dia de Premium."

No dia da expiração:
→ downgrade para Free
→ bot envia: "Premium expirado. Você voltou para o plano Free."
→ lista o que foi perdido (buscas pausadas automaticamente se acima do limite Free)
```

**Localização:** `app/scheduler/premium_expiration_job.py` + novo `app/services/premium_expiry_notification_service.py`

---

## FLOW-03 — Fluxo de feedback quando busca não gera alerta por 7 dias

**Estado atual:** usuário cria busca, não recebe alerta, some. Sem nenhum toque do bot.

**O que implementar:** job semanal que detecta wishlists ativas sem alerta nos últimos 7 dias e envia:

```
Sua busca "ek9 b16" está ativa mas não encontrou nada em 7 dias.

Possíveis motivos:
• Carro muito raro para essa configuração
• Filtros muito restritivos
• Preço abaixo do mercado

O que prefere?
[🔧 Ajustar filtros] [⏸️ Pausar busca] [Continuar monitorando]
```

**Localização:** novo `app/scheduler/wishlist_no_alert_nudge_job.py`

**Critério:** não enviar mais de 1x por wishlist por semana.

---

## FLOW-04 — Fluxo de trial (não existe, deveria)

**Estado atual:** não há período de trial. Usuário entra Free e pode nunca perceber o valor do Premium antes de bater no limite.

**O que implementar:** 7 dias de Premium automático para novos usuários.

```
/start (novo usuário)
→ conta criada com subscription trial por 7 dias
→ bot menciona: "Você tem 7 dias de acesso completo."
→ no dia 5: "Seu trial termina em 2 dias. Continue com Premium por R$ 9,90/mês."
→ no dia 7: downgrade automático para Free
```

**Schema:** `subscriptions.source = "trial"` + `subscriptions.ends_at = now() + 7 days`

**O trial resolve o gap de ativação:** usuário recebe alertas com volume de Premium durante o trial e sente a diferença quando cai para Free.

---

## FLOW-05 — Fluxo de busca muito restritiva: diagnóstico automático

**Estado atual:** usuário cria busca com 5 filtros, não recebe nada, não sabe por quê.

**O que implementar:** quando trigger_initial_run retorna 0 resultados, analisar por que:

```python
# Após primeira varredura com 0 resultados:
diagnosis = diagnose_zero_results(wishlist, source_runs)

if diagnosis.reason == "filters_too_strict":
    # Ex: km < 50000 + preço < 60000 + apenas SP
    await bot.send(
        "Não encontrei nada. Seus filtros podem estar muito restritivos.\n\n"
        f"Tentei: {diagnosis.filter_summary}\n\n"
        "O que prefere?",
        reply_markup=[[
            "Relaxar filtros", "Manter e aguardar"
        ]]
    )
```

**Localização:** `app/services/wishlist_diagnosis_service.py` (novo)

---

## Prioridade

| # | Item | Semana | Impacto |
|---|---|---|---|
| FLOW-01 | Pagamento automático | 0 | Bloqueador comercial |
| FLOW-04 | Trial 7 dias | 1 | Ativação e conversão |
| FLOW-02 | Expiração com aviso | 1 | Retenção Premium |
| FLOW-03 | Nudge busca sem alerta 7d | 2 | Retenção Free |
| FLOW-05 | Diagnóstico busca restritiva | 3 | Reduz abandono silencioso |
