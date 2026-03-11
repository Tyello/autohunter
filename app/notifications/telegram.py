"""
Telegram Notifier

Notificador via Telegram Bot API.
"""

import requests
from typing import Optional
from datetime import datetime

from app.core.settings import settings
from app.notifications.base import (
    BaseNotifier,
    Notification,
    NotificationResult,
    NotificationChannel,
)


class TelegramNotifier(BaseNotifier):
    """Notificador Telegram."""
    
    def __init__(self, bot_token: Optional[str] = None):
        """Inicializa Telegram notifier.
        
        Args:
            bot_token: Token do bot (ou via env TELEGRAM_BOT_TOKEN)
        """
        super().__init__(NotificationChannel.TELEGRAM)
        
        self.bot_token = bot_token or settings.telegram_bot_token
        
        if self.bot_token:
            self.enable()
            self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        else:
            self.logger.warning("Telegram bot token not configured")
    
    def send(self, notification: Notification) -> NotificationResult:
        """Envia mensagem via Telegram.
        
        Args:
            notification: Notificação a enviar
        
        Returns:
            Resultado do envio
        """
        if not self.is_enabled():
            return self._create_error_result("Telegram notifier not enabled")
        
        if not self.validate_recipient(notification.recipient):
            return self._create_error_result("Invalid Telegram chat ID")
        
        try:
            # Formata mensagem
            message = self._format_message(notification)
            
            # Envia via API
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json={
                    "chat_id": notification.recipient,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("ok"):
                result = self._create_success_result(
                    message_id=str(data["result"]["message_id"]),
                    metadata={"chat_id": notification.recipient}
                )
            else:
                result = self._create_error_result(
                    data.get("description", "Unknown error")
                )
            
            self._log_send(notification, result)
            return result
            
        except requests.RequestException as e:
            result = self._create_error_result(str(e))
            self._log_send(notification, result)
            return result
    
    def validate_recipient(self, recipient: str) -> bool:
        """Valida chat ID do Telegram.
        
        Args:
            recipient: Chat ID (pode ser número ou @username)
        
        Returns:
            True se válido
        """
        if not recipient:
            return False
        
        # Chat ID numérico
        if recipient.lstrip("-").isdigit():
            return True
        
        # Username (@username)
        if recipient.startswith("@") and len(recipient) > 1:
            return True
        
        return False
    
    def _format_message(self, notification: Notification) -> str:
        """Formata mensagem com HTML do Telegram.
        
        Args:
            notification: Notificação
        
        Returns:
            Mensagem formatada
        """
        # Se tem subject, adiciona como header bold
        if notification.subject:
            return f"<b>{notification.subject}</b>\n\n{notification.message}"
        
        return notification.message
    
    def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: Optional[str] = None
    ) -> NotificationResult:
        """Envia foto via Telegram.
        
        Args:
            chat_id: ID do chat
            photo_url: URL da foto
            caption: Legenda (opcional)
        
        Returns:
            Resultado do envio
        """
        if not self.is_enabled():
            return self._create_error_result("Telegram notifier not enabled")
        
        try:
            response = requests.post(
                f"{self.api_url}/sendPhoto",
                json={
                    "chat_id": chat_id,
                    "photo": photo_url,
                    "caption": caption,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("ok"):
                return self._create_success_result(
                    message_id=str(data["result"]["message_id"])
                )
            else:
                return self._create_error_result(
                    data.get("description", "Unknown error")
                )
                
        except requests.RequestException as e:
            return self._create_error_result(str(e))
    
    def get_me(self) -> Optional[dict]:
        """Retorna informações do bot.
        
        Returns:
            Dict com info do bot ou None
        """
        if not self.is_enabled():
            return None
        
        try:
            response = requests.get(f"{self.api_url}/getMe", timeout=5)
            response.raise_for_status()
            data = response.json()
            
            if data.get("ok"):
                return data["result"]
            
        except Exception as e:
            self.logger.error(f"Failed to get bot info: {e}")
        
        return None
