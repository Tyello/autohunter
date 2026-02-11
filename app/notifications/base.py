"""
Base Notification System

Sistema base para notificações multi-canal com suporte a:
- Telegram
- WhatsApp
- Email
- SMS
- Webhooks
- Push Notifications
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
import logging


class NotificationChannel(Enum):
    """Canais de notificação disponíveis."""
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    PUSH = "push"


class NotificationPriority(Enum):
    """Prioridade da notificação."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(Enum):
    """Status de uma notificação."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


@dataclass
class NotificationResult:
    """Resultado do envio de uma notificação."""
    success: bool
    channel: NotificationChannel
    message_id: Optional[str] = None
    error: Optional[str] = None
    sent_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "channel": self.channel.value,
            "message_id": self.message_id,
            "error": self.error,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "metadata": self.metadata,
        }


@dataclass
class Notification:
    """Notificação a ser enviada."""
    channel: NotificationChannel
    recipient: str
    subject: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    metadata: Optional[Dict[str, Any]] = None
    
    # Tracking
    created_at: datetime = None
    sent_at: Optional[datetime] = None
    status: NotificationStatus = NotificationStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel.value,
            "recipient": self.recipient,
            "subject": self.subject,
            "message": self.message[:100] + "..." if len(self.message) > 100 else self.message,
            "priority": self.priority.value,
            "status": self.status.value,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


class BaseNotifier(ABC):
    """Classe base para todos os notificadores.
    
    Cada canal de notificação (Telegram, WhatsApp, etc) deve
    herdar desta classe e implementar o método send().
    """
    
    def __init__(self, channel: NotificationChannel):
        """Inicializa notifier.
        
        Args:
            channel: Canal de notificação
        """
        self.channel = channel
        self.logger = logging.getLogger(f"{__name__}.{channel.value}")
        self.enabled = False
    
    @abstractmethod
    def send(self, notification: Notification) -> NotificationResult:
        """Envia notificação.
        
        Args:
            notification: Notificação a enviar
        
        Returns:
            Resultado do envio
        """
        pass
    
    @abstractmethod
    def validate_recipient(self, recipient: str) -> bool:
        """Valida formato do recipient.
        
        Args:
            recipient: Destinatário (phone, email, chat_id, etc)
        
        Returns:
            True se válido
        """
        pass
    
    def is_enabled(self) -> bool:
        """Verifica se notifier está habilitado."""
        return self.enabled
    
    def enable(self):
        """Habilita notifier."""
        self.enabled = True
        self.logger.info(f"{self.channel.value} notifier enabled")
    
    def disable(self):
        """Desabilita notifier."""
        self.enabled = False
        self.logger.info(f"{self.channel.value} notifier disabled")
    
    def _log_send(self, notification: Notification, result: NotificationResult):
        """Log do envio."""
        if result.success:
            self.logger.info(
                f"✅ Sent via {self.channel.value} to {notification.recipient} "
                f"(ID: {result.message_id})"
            )
        else:
            self.logger.error(
                f"❌ Failed to send via {self.channel.value} to {notification.recipient}: "
                f"{result.error}"
            )
    
    def _create_success_result(
        self,
        message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> NotificationResult:
        """Cria resultado de sucesso."""
        return NotificationResult(
            success=True,
            channel=self.channel,
            message_id=message_id,
            sent_at=datetime.utcnow(),
            metadata=metadata,
        )
    
    def _create_error_result(
        self,
        error: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> NotificationResult:
        """Cria resultado de erro."""
        return NotificationResult(
            success=False,
            channel=self.channel,
            error=error,
            metadata=metadata,
        )


class NotificationTemplate:
    """Template de mensagem de notificação."""
    
    def __init__(self, name: str, template: str):
        """Inicializa template.
        
        Args:
            name: Nome do template
            template: String template com placeholders {var}
        """
        self.name = name
        self.template = template
    
    def render(self, **kwargs) -> str:
        """Renderiza template com variáveis.
        
        Args:
            **kwargs: Variáveis do template
        
        Returns:
            Mensagem renderizada
        """
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing template variable: {e}")


# ========== Templates Padrão ==========

TEMPLATES = {
    "new_listing": NotificationTemplate(
        name="new_listing",
        template="""🚗 NOVO ANÚNCIO ENCONTRADO!

{make} {model} {year}
💰 Preço: R$ {price:,.2f}
📍 Local: {city}, {state}
⛽ Combustível: {fuel_type}
📏 KM: {mileage_km:,}

🔗 {url}

Adicionado: {source}
"""
    ),
    
    "new_auction_lot": NotificationTemplate(
        name="new_auction_lot",
        template="""🏷️ NOVO LOTE DE LEILÃO!

{make} {model} {year}
Lote #{lot_number}

💰 Lance Inicial: R$ {initial_bid:,.2f}
📍 Local: {city}, {state}

📄 Documentação: {has_documentation}
💳 Débitos: {has_debts}
🔧 Condição: {condition}

🔗 {url}

⏰ Evento: {event_date}
"""
    ),
    
    "price_drop": NotificationTemplate(
        name="price_drop",
        template="""💰 QUEDA DE PREÇO!

{make} {model} {year}

Preço anterior: R$ {old_price:,.2f}
Preço atual: R$ {new_price:,.2f}
📉 Redução: R$ {price_drop:,.2f} ({price_drop_percent:.1f}%)

📍 {city}, {state}
🔗 {url}
"""
    ),
    
    "daily_summary": NotificationTemplate(
        name="daily_summary",
        template="""📊 RESUMO DIÁRIO - AutoHunter

Novos anúncios: {new_listings}
Novos leilões: {new_auctions}
Alertas de preço: {price_alerts}

Top marcas hoje:
{top_makes}

🔗 Ver detalhes: {dashboard_url}
"""
    ),
    
    "error_alert": NotificationTemplate(
        name="error_alert",
        template="""⚠️ ALERTA DE ERRO - AutoHunter

Tipo: {error_type}
Source: {source}
Mensagem: {error_message}

Timestamp: {timestamp}

🔧 Ação necessária: {action_required}
"""
    ),
}


def get_template(name: str) -> NotificationTemplate:
    """Retorna template por nome."""
    if name not in TEMPLATES:
        raise ValueError(f"Template '{name}' not found")
    return TEMPLATES[name]


def render_template(name: str, **kwargs) -> str:
    """Renderiza template por nome."""
    template = get_template(name)
    return template.render(**kwargs)
