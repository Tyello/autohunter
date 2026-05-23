# Subscription — Pagamento e Ciclo de Vida
> O modelo de dados suporta subscriptions. O fluxo de pagamento não existe. Este documento especifica o que implementar.

---

## Estado atual

- Modelo `Subscription` completo: `account_id`, `plan_id`, `status`, `source`, `starts_at`, `ends_at`, `current_period_start`, `current_period_end`, `cancel_at_period_end`, `metadata_json`
- `premium_subscription_service.py` tem `activate_premium`, `expire_premium`, `get_active_subscription`
- `premium_expiration_job.py` já roda no scheduler
- `/upgrade` mostra link Mercado Pago configurável
- **Nada disso é automático.** Admin ativa manualmente após validar comprovante.

---

## SUB-01 — Webhook Mercado Pago (caminho principal)

**Pré-requisito:** conta Mercado Pago com aplicação criada e webhook configurado.

### Fluxo técnico

```
1. Usuário toca "Assinar Mensal" no bot
2. Bot chama MP API: criar preferência de pagamento
   POST https://api.mercadopago.com/checkout/preferences
   {
     "items": [{"title": "Garagem Alvo Premium Mensal", "unit_price": 9.90, ...}],
     "metadata": {"chat_id": "123456789", "plan_period": "monthly"},
     "notification_url": "https://seudominio.com/webhooks/mercadopago",
     "back_urls": {...}
   }
3. MP retorna preference_id + init_point (URL de checkout)
4. Bot envia URL para o usuário

5. Usuário paga no Mercado Pago

6. MP envia POST /webhooks/mercadopago com evento payment.updated
7. App valida assinatura HMAC do webhook (header x-signature)
8. Extrai chat_id do metadata do pagamento
9. Verifica status == "approved"
10. Chama premium_subscription_service.activate_premium(db, chat_id, period)
11. Bot notifica usuário: "✅ Premium ativado!"
12. Bot notifica admin: "💰 Nova assinatura: @username"
```

### Arquivos a criar

**`app/web/routes_webhooks.py`:**
```python
from fastapi import APIRouter, Request, HTTPException
import hmac, hashlib

router = APIRouter()

@router.post("/webhooks/mercadopago")
async def handle_mercadopago_webhook(request: Request):
    # 1. Validar assinatura
    body = await request.body()
    signature = request.headers.get("x-signature", "")
    expected = hmac.new(settings.mp_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, f"sha256={expected}"):
        raise HTTPException(status_code=401)

    # 2. Processar evento
    data = await request.json()
    if data.get("type") == "payment" and data.get("action") == "payment.updated":
        payment_id = data["data"]["id"]
        # Buscar detalhes do pagamento na API do MP
        payment = await mp_client.get_payment(payment_id)
        if payment["status"] == "approved":
            chat_id = payment["metadata"]["chat_id"]
            period = payment["metadata"]["plan_period"]
            with SessionLocal() as db:
                await activate_and_notify(db, chat_id, period)

    return {"status": "ok"}
```

**`app/services/mercadopago_service.py`:**
```python
import mercadopago

class MercadoPagoService:
    def __init__(self):
        self.sdk = mercadopago.SDK(settings.mp_access_token)

    def create_preference(self, chat_id: str, period: str) -> dict:
        price = 9.90 if period == "monthly" else 59.99
        title = f"Garagem Alvo Premium {'Mensal' if period == 'monthly' else 'Anual'}"
        preference_data = {
            "items": [{"title": title, "quantity": 1, "unit_price": price}],
            "metadata": {"chat_id": chat_id, "plan_period": period},
            "notification_url": settings.mp_webhook_url,
        }
        result = self.sdk.preference().create(preference_data)
        return result["response"]

    async def get_payment(self, payment_id: str) -> dict:
        result = self.sdk.payment().get(payment_id)
        return result["response"]
```

**Settings a adicionar:**
```python
mp_access_token: str | None = None
mp_webhook_secret: str | None = None
mp_webhook_url: str | None = None  # URL pública do webhook
```

---

## SUB-02 — Aprovação em 1 clique (fallback para beta)

Para o beta, antes do webhook estar pronto:

```
1. Usuário envia comprovante (imagem ou texto) no chat
2. Handler detecta: contém "paguei" ou "comprovante" ou é imagem em resposta a mensagem de upgrade
3. Bot encaminha para admin com contexto:
   "💰 Pedido de ativação Premium
   Usuário: @username (chat_id: 123)
   Plano desejado: mensal (R$ 9,90)
   [Comprovante anexo]"
4. Botões inline:
   [✅ Ativar Mensal] [✅ Ativar Anual] [❌ Recusar]
5. Admin toca → bot ativa Premium → notifica usuário
```

**Handler a criar:** `app/bot/handlers_payment.py::handle_comprovante`

```python
async def handle_comprovante(update, context):
    user_id = update.effective_user.id
    # Verificar se usuário está em fluxo de upgrade
    # Encaminhar para admin com botões InlineKeyboard
    await context.bot.send_message(
        chat_id=settings.admin_chat_id,
        text=f"💰 Pedido Premium\n@{update.effective_user.username}\nchat_id: {user_id}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Mensal", callback_data=f"ADMIN:ACTIVATE:monthly:{user_id}")],
            [InlineKeyboardButton("✅ Anual", callback_data=f"ADMIN:ACTIVATE:annual:{user_id}")],
            [InlineKeyboardButton("❌ Recusar", callback_data=f"ADMIN:ACTIVATE:refuse:{user_id}")],
        ])
    )
```

---

## SUB-03 — Lifecycle completo de expiração

**Hoje:** `premium_expiration_job.py` expira subscriptions. Sem aviso prévio.

**O que adicionar:**

```python
# Adicionar ao scheduler — rodar 1x/dia às 9h BRT:
async def premium_expiry_warning_job(db):
    # Subscriptions que expiram em 7 dias
    expiring_7d = get_subscriptions_expiring_in(db, days=7)
    for sub in expiring_7d:
        user = get_user_by_account(db, sub.account_id)
        await bot.send_message(
            chat_id=user.telegram_chat_id,
            text=f"⚠️ Seu Premium expira em 7 dias ({sub.ends_at.strftime('%d/%m')}).\n\nRenove para continuar recebendo todos os alertas.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Renovar", callback_data="MENU:UPGRADE")
            ]])
        )

    # Subscriptions que expiram amanhã
    expiring_1d = get_subscriptions_expiring_in(db, days=1)
    for sub in expiring_1d:
        # Mensagem mais urgente
        ...
```

---

## SUB-04 — Auditoria de ativações

**Estado atual:** ativações manuais via `/admin premium activate` não ficam registradas com detalhe suficiente. `admin_deploy_audits` existe mas é para deploy, não para Premium.

**O que adicionar:** campo `metadata_json` na Subscription já suporta rastreio:

```python
# Ao ativar Premium manualmente:
sub.metadata_json = {
    "activated_by": "admin",
    "activated_at": datetime.now(UTC).isoformat(),
    "admin_chat_id": admin_chat_id,
    "reason": reason or "manual",
    "payment_ref": payment_ref or None,
}
```

---

## Prioridade

| # | Item | Semana | Impacto |
|---|---|---|---|
| SUB-02 | Aprovação 1 clique | 0 | Desbloqueio imediato para beta |
| SUB-01 | Webhook Mercado Pago | 1 | Escala de pagamento |
| SUB-03 | Aviso de expiração | 1 | Retenção Premium |
| SUB-04 | Auditoria de ativações | 2 | Rastreabilidade operacional |
