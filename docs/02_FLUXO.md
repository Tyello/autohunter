# Fluxo — Melhorias de Jornada do Usuário

Atualizado em: 2026-05-25.  
Estado confrontado com a `main` após a entrada de `/admin metrics`.

> Este documento lista gaps reais de jornada.  
> Itens já entregues no produto ou em observabilidade admin não devem voltar como bloqueadores de fluxo.

---

## Estado atual confrontado com a `main`

### Já existe no produto

- Entrada por `/start` e `/menu`.
- Criação e gestão de buscas/wishlists pelo Telegram.
- Filtros implícitos e filtros guiados.
- Busca pontual em `/buscar`/menu, sem salvar monitoramento.
- Tracking de anúncios por wishlist.
- Plano Free/Premium, `/plan` e `/upgrade`.
- Link Mercado Pago configurável no upgrade.
- Ativação Premium manual/admin.
- Scheduler, filas persistentes, workers e sender.
- `/admin metrics` v1 para acompanhar beta e funil operacional básico.

### Ainda não existe como fluxo fechado

- Pagamento automático com webhook Mercado Pago.
- Aprovação de comprovante em 1 clique pelo admin.
- Trial automático de 7 dias para usuário novo.
- Avisos user-facing antes da expiração Premium.
- Nudge interativo quando uma busca fica 7 dias sem alerta.
- Diagnóstico automático de busca muito restritiva após primeira varredura sem resultado.

### Evidência importante

- `app/web/routes_webhooks.py` não existe na `main`.
- `/admin metrics` existe em `app/bot/admin_handlers_metrics.py` e está registrado em `app/bot/handlers_admin.py`.
- Portanto, métricas não são mais gap deste documento; pagamento/ativação continua sendo o principal gap de fluxo comercial.

---

## FLOW-01 — Pagamento: fluxo ainda manual

**Status:** aberto.  
**Impacto:** bloqueador comercial para lançamento público.

**Estado atual:** usuário toca em upgrade, recebe link do Mercado Pago, paga fora do bot e depende de validação/ativação manual pelo admin. Isso funciona para operação assistida, mas não escala.

### Opção A — Webhook Mercado Pago

Fluxo desejado:

```text
usuário toca Assinar Mensal/Anual
→ bot gera preferência de pagamento com metadata {chat_id, plan, period}
→ bot envia link de checkout personalizado
→ usuário paga
→ Mercado Pago envia webhook POST /webhooks/mercadopago
→ app valida assinatura do webhook
→ app extrai chat_id/period do pagamento
→ premium_subscription_service ativa assinatura
→ bot notifica usuário
→ bot notifica admin
```

Arquivos prováveis:

```text
app/web/routes_webhooks.py
app/services/mercadopago_service.py
app/bot/handlers_upgrade.py ou handler equivalente de upgrade
```

### Opção B — Aprovação admin em 1 clique

Fallback recomendado para beta:

```text
usuário envia comprovante no chat
→ bot encaminha para admin com contexto
→ admin toca em Ativar Mensal / Ativar Anual / Recusar
→ bot ativa Premium automaticamente
→ bot notifica usuário
```

Arquivo provável:

```text
app/bot/handlers_payment.py
```

**Critério:** Premium ativado sem o admin digitar comando manual.

---

## FLOW-02 — Fluxo de expiração do Premium

**Status:** aberto.

**Estado atual:** existe job de expiração Premium, mas este documento não encontrou, na `main`, um fluxo user-facing completo de aviso 7 dias/1 dia antes e mensagem de downgrade no dia da expiração.

Fluxo desejado:

```text
7 dias antes → aviso de renovação
1 dia antes → aviso final
no dia → downgrade + mensagem clara do que mudou
```

Arquivos prováveis:

```text
app/scheduler/premium_expiration_job.py
app/services/premium_expiry_notification_service.py
```

**Critério:** usuário não descobre a expiração apenas quando perde uma capacidade Premium.

---

## FLOW-03 — Busca sem alerta por 7 dias

**Status:** aberto, parcialmente relacionado ao digest semanal v2.

**Estado atual:** o digest semanal existe como base, mas ainda falta um fluxo interativo específico por wishlist silenciosa.

Fluxo desejado:

```text
Sua busca "ek9 b16" está ativa, mas não encontrou nada em 7 dias.

Possíveis motivos:
• Carro muito raro
• Filtros muito restritivos
• Preço abaixo do mercado

[🔧 Ajustar filtros] [⏸️ Pausar busca] [Continuar monitorando]
```

Arquivo provável:

```text
app/scheduler/wishlist_no_alert_nudge_job.py
```

**Critério:** não enviar mais de 1 vez por wishlist por semana.

---

## FLOW-04 — Trial de 7 dias

**Status:** aberto.

**Estado atual:** não há evidência na `main` de trial automático para novos usuários. O modelo de subscription suporta `source` e `ends_at`, então a evolução parece possível sem migration grande.

Fluxo desejado:

```text
/start de usuário novo
→ cria conta com acesso Premium trial por 7 dias
→ avisa que o acesso completo é temporário
→ avisa antes de terminar
→ downgrade automático para Free ao expirar
```

**Critério:** usuário novo sente valor do Premium antes de pagar.

---

## FLOW-05 — Diagnóstico de busca muito restritiva

**Status:** aberto.

**Problema:** usuário cria busca com muitos filtros, não recebe alerta e não sabe se o carro é raro, caro demais ou se os filtros bloquearam tudo.

Direção:

```python
diagnosis = diagnose_zero_results(wishlist, source_runs)
```

Saída desejada:

```text
Não encontrei nada agora.
Seus filtros podem estar muito restritivos:
km baixo + preço abaixo do mercado + apenas uma cidade.

[Relaxar filtros] [Manter e aguardar]
```

Arquivo provável:

```text
app/services/wishlist_diagnosis_service.py
```

**Critério:** primeira varredura sem resultado vira orientação, não silêncio.

---

## Prioridade atual

| # | Item | Status | Impacto |
|---|---|---|---|
| 1 | FLOW-01 — Pagamento automático ou 1 clique | Aberto | Bloqueador comercial |
| 2 | FLOW-04 — Trial 7 dias | Aberto | Ativação e conversão |
| 3 | FLOW-02 — Expiração com aviso | Aberto | Retenção Premium |
| 4 | FLOW-03 — Nudge busca sem alerta | Aberto | Retenção Free/Premium |
| 5 | FLOW-05 — Diagnóstico busca restritiva | Aberto | Reduz abandono silencioso |

---

## Fora da fila deste documento

- `/admin metrics` v1: concluído.
- Refactor de admin handlers: fica em `03_ARQUITETURA.md`.
- Ajustes de throughput/Raspberry: ficam em `08_EFICIENCIA.md`.
- BUGs e validações técnicas: ficam em `07_BUGS.md`.
