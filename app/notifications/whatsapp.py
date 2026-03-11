"""
WhatsApp Notifier

Notificador via WhatsApp usando Twilio API.
"""

from typing import Optional

from app.core.settings import settings
from app.notifications.base import (
    BaseNotifier,
    Notification,
    NotificationResult,
    NotificationChannel,
)


class WhatsAppNotifier(BaseNotifier):
    """Notificador WhatsApp via Twilio."""
    
    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
    ):
        """Inicializa WhatsApp notifier.
        
        Args:
            account_sid: Twilio Account SID (ou via env TWILIO_ACCOUNT_SID)
            auth_token: Twilio Auth Token (ou via env TWILIO_AUTH_TOKEN)
            from_number: WhatsApp number (ou via env TWILIO_WHATSAPP_NUMBER)
        """
        super().__init__(NotificationChannel.WHATSAPP)
        
        self.account_sid = account_sid or settings.twilio_account_sid
        self.auth_token = auth_token or settings.twilio_auth_token
        self.from_number = from_number or settings.twilio_whatsapp_number
        
        if self.account_sid and self.auth_token:
            try:
                from twilio.rest import Client
                self.client = Client(self.account_sid, self.auth_token)
                self.enable()
            except ImportError:
                self.logger.error("Twilio library not installed. Run: pip install twilio")
            except Exception as e:
                self.logger.error(f"Failed to initialize Twilio client: {e}")
        else:
            self.logger.warning("Twilio credentials not configured")
    
    def send(self, notification: Notification) -> NotificationResult:
        """Envia mensagem via WhatsApp.
        
        Args:
            notification: Notificação a enviar
        
        Returns:
            Resultado do envio
        """
        if not self.is_enabled():
            return self._create_error_result("WhatsApp notifier not enabled")
        
        if not self.validate_recipient(notification.recipient):
            return self._create_error_result("Invalid WhatsApp number")
        
        try:
            # Garante formato whatsapp:+número
            to_number = self._format_number(notification.recipient)
            
            # Formata mensagem
            message = self._format_message(notification)
            
            # Envia via Twilio
            message_obj = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number,
            )
            
            result = self._create_success_result(
                message_id=message_obj.sid,
                metadata={
                    "to": to_number,
                    "status": message_obj.status,
                }
            )
            
            self._log_send(notification, result)
            return result
            
        except Exception as e:
            result = self._create_error_result(str(e))
            self._log_send(notification, result)
            return result
    
    def validate_recipient(self, recipient: str) -> bool:
        """Valida número de WhatsApp.
        
        Args:
            recipient: Número no formato +5511999999999 ou whatsapp:+5511999999999
        
        Returns:
            True se válido
        """
        if not recipient:
            return False
        
        # Remove whatsapp: prefix se tiver
        number = recipient.replace("whatsapp:", "").strip()
        
        # Deve começar com + e ter ao menos 10 dígitos
        if number.startswith("+") and len(number.replace("+", "").replace(" ", "")) >= 10:
            return True
        
        return False
    
    def _format_number(self, recipient: str) -> str:
        """Formata número para Twilio.
        
        Args:
            recipient: Número
        
        Returns:
            Número formatado (whatsapp:+...)
        """
        if recipient.startswith("whatsapp:"):
            return recipient
        
        if not recipient.startswith("+"):
            # Assume Brasil se não tem código de país
            recipient = f"+55{recipient}"
        
        return f"whatsapp:{recipient}"
    
    def _format_message(self, notification: Notification) -> str:
        """Formata mensagem para WhatsApp.
        
        Args:
            notification: Notificação
        
        Returns:
            Mensagem formatada
        """
        # WhatsApp suporta emojis e quebras de linha
        if notification.subject:
            return f"*{notification.subject}*\n\n{notification.message}"
        
        return notification.message
    
    def send_media(
        self,
        to_number: str,
        media_url: str,
        caption: Optional[str] = None
    ) -> NotificationResult:
        """Envia mídia via WhatsApp.
        
        Args:
            to_number: Número do destinatário
            media_url: URL da mídia (imagem, vídeo, etc)
            caption: Legenda (opcional)
        
        Returns:
            Resultado do envio
        """
        if not self.is_enabled():
            return self._create_error_result("WhatsApp notifier not enabled")
        
        try:
            to = self._format_number(to_number)
            
            message_obj = self.client.messages.create(
                body=caption or "",
                media_url=[media_url],
                from_=self.from_number,
                to=to,
            )
            
            return self._create_success_result(
                message_id=message_obj.sid,
                metadata={"media_url": media_url}
            )
            
        except Exception as e:
            return self._create_error_result(str(e))
