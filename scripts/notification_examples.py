"""
Notification Examples - Exemplos de Uso

Demonstra como usar o sistema de notificações.
"""

from app.notifications.manager import get_notification_manager
from app.notifications.base import (
    NotificationChannel,
    NotificationPriority,
    render_template,
)


def example_simple_notification():
    """Exemplo: Notificação simples via Telegram."""
    manager = get_notification_manager()
    
    result = manager.send(
        channel=NotificationChannel.TELEGRAM,
        recipient="123456789",  # Seu chat_id
        subject="Teste AutoHunter",
        message="Esta é uma mensagem de teste!",
        priority=NotificationPriority.NORMAL,
    )
    
    print(f"Resultado: {result.success}")
    if not result.success:
        print(f"Erro: {result.error}")


def example_new_listing_notification():
    """Exemplo: Notificação de novo listing usando template."""
    manager = get_notification_manager()
    
    # Dados do listing
    listing_data = {
        "make": "Honda",
        "model": "Civic",
        "year": 2019,
        "price": 75000.00,
        "city": "São Paulo",
        "state": "SP",
        "fuel_type": "Flex",
        "mileage_km": 35000,
        "url": "https://example.com/listing/123",
        "source": "iCarros",
    }
    
    # Renderiza template
    message = render_template("new_listing", **listing_data)
    
    # Envia via Telegram
    manager.send(
        channel=NotificationChannel.TELEGRAM,
        recipient="123456789",
        subject="🚗 Novo Honda Civic 2019",
        message=message,
        priority=NotificationPriority.HIGH,
    )


def example_multi_channel_notification():
    """Exemplo: Envio via múltiplos canais com fallback."""
    manager = get_notification_manager()
    
    results = manager.send_multi_channel(
        channels=[
            NotificationChannel.TELEGRAM,
            NotificationChannel.EMAIL,
            NotificationChannel.WHATSAPP,
        ],
        recipient_map={
            NotificationChannel.TELEGRAM: "123456789",
            NotificationChannel.EMAIL: "user@example.com",
            NotificationChannel.WHATSAPP: "+5511999999999",
        },
        subject="Alerta Importante",
        message="Este é um alerta de alta prioridade!",
        priority=NotificationPriority.URGENT,
        fallback=True,  # Se Telegram falhar, tenta Email, depois WhatsApp
    )
    
    for channel, result in results.items():
        print(f"{channel.value}: {'✅' if result.success else '❌'}")


def example_price_drop_alert():
    """Exemplo: Alerta de queda de preço."""
    manager = get_notification_manager()
    
    alert_data = {
        "make": "Toyota",
        "model": "Corolla",
        "year": 2020,
        "old_price": 85000.00,
        "new_price": 78000.00,
        "price_drop": 7000.00,
        "price_drop_percent": 8.2,
        "city": "Rio de Janeiro",
        "state": "RJ",
        "url": "https://example.com/listing/456",
    }
    
    message = render_template("price_drop", **alert_data)
    
    # Envia com alta prioridade
    manager.send(
        channel=NotificationChannel.TELEGRAM,
        recipient="123456789",
        subject="💰 Queda de Preço - Toyota Corolla",
        message=message,
        priority=NotificationPriority.HIGH,
    )


def example_auction_lot_notification():
    """Exemplo: Notificação de lote de leilão."""
    manager = get_notification_manager()
    
    lot_data = {
        "make": "Honda",
        "model": "Civic",
        "year": 2019,
        "lot_number": "123",
        "initial_bid": 45000.00,
        "city": "São Paulo",
        "state": "SP",
        "has_documentation": "✅ Sim",
        "has_debts": "❌ Não",
        "condition": "Usado",
        "url": "https://example.com/lot/123",
        "event_date": "15/02/2026 10:00",
    }
    
    message = render_template("new_auction_lot", **lot_data)
    
    manager.send(
        channel=NotificationChannel.WHATSAPP,
        recipient="+5511999999999",
        subject="🏷️ Novo Lote de Leilão",
        message=message,
        priority=NotificationPriority.NORMAL,
    )


def example_daily_summary():
    """Exemplo: Resumo diário."""
    manager = get_notification_manager()
    
    summary_data = {
        "new_listings": 45,
        "new_auctions": 12,
        "price_alerts": 3,
        "top_makes": "Honda (15), Toyota (12), Volkswagen (8)",
        "dashboard_url": "https://autohunter.example.com",
    }
    
    message = render_template("daily_summary", **summary_data)
    
    # Envia via email (resumo completo)
    manager.send(
        channel=NotificationChannel.EMAIL,
        recipient="user@example.com",
        subject="📊 Resumo Diário - AutoHunter",
        message=message,
        priority=NotificationPriority.LOW,
    )


def example_webhook_notification():
    """Exemplo: Notificação via webhook."""
    manager = get_notification_manager()
    
    # Webhook pode ser usado para integrar com outros sistemas
    # (Slack, Discord, Microsoft Teams, Zapier, etc)
    
    result = manager.send(
        channel=NotificationChannel.WEBHOOK,
        recipient="",  # Não usado em webhook (usa URL configurada)
        subject="AutoHunter Event",
        message="New listing found!",
        priority=NotificationPriority.NORMAL,
        metadata={
            "event_type": "new_listing",
            "listing_id": 123,
            "make": "Honda",
            "model": "Civic",
            "price": 75000.00,
        }
    )
    
    print(f"Webhook enviado: {result.success}")


def example_async_queue():
    """Exemplo: Usar queue assíncrona para não bloquear."""
    manager = get_notification_manager()
    
    # Inicia worker
    manager.start_worker()
    
    # Envia 100 notificações rapidamente (não bloqueia)
    for i in range(100):
        manager.send(
            channel=NotificationChannel.TELEGRAM,
            recipient="123456789",
            subject=f"Teste {i}",
            message=f"Esta é a mensagem {i}",
            priority=NotificationPriority.LOW,
            async_mode=True,  # Adiciona na queue
        )
    
    print("100 notificações enfileiradas!")
    
    # Ver stats
    stats = manager.get_stats()
    print(f"Queue: {stats['queue_size']} pendentes")
    print(f"Enviadas: {stats['sent_count']}")
    print(f"Falhas: {stats['failed_count']}")
    
    # Para worker (quando terminar aplicação)
    # manager.stop_worker()


def example_error_alert():
    """Exemplo: Alerta de erro do sistema."""
    manager = get_notification_manager()
    
    error_data = {
        "error_type": "ScraperTimeout",
        "source": "iCarros",
        "error_message": "Request timeout after 60s",
        "timestamp": "2026-02-10 14:30:00",
        "action_required": "Verificar se site está online",
    }
    
    message = render_template("error_alert", **error_data)
    
    # Alerta urgente via múltiplos canais
    manager.send_multi_channel(
        channels=[
            NotificationChannel.TELEGRAM,
            NotificationChannel.EMAIL,
        ],
        recipient_map={
            NotificationChannel.TELEGRAM: "123456789",
            NotificationChannel.EMAIL: "admin@example.com",
        },
        subject="⚠️ ALERTA DE ERRO - AutoHunter",
        message=message,
        priority=NotificationPriority.URGENT,
    )


if __name__ == "__main__":
    print("=== Notification Examples ===\n")
    
    # Descomente o exemplo que quer testar:
    
    # example_simple_notification()
    # example_new_listing_notification()
    # example_multi_channel_notification()
    # example_price_drop_alert()
    # example_auction_lot_notification()
    # example_daily_summary()
    # example_webhook_notification()
    # example_async_queue()
    # example_error_alert()
    
    print("\nPronto! Configure seu .env primeiro:")
    print("  TELEGRAM_BOT_TOKEN=...")
    print("  TWILIO_ACCOUNT_SID=...")
    print("  SMTP_HOST=...")
