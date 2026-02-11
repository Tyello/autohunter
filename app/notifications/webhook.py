"""
Webhook Notifier

Notificador genérico via HTTP webhooks.
"""

import os
import requests
from typing import Optional, Dict, Any
import hmac
import hashlib

from app.notifications.base import (
    BaseNotifier,
    Notification,
    NotificationResult,
    NotificationChannel,
)


class WebhookNotifier(BaseNotifier):
    """Notificador via HTTP Webhooks."""
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
    ):
        """Inicializa Webhook notifier.
        
        Args:
            webhook_url: URL do webhook (ou via env WEBHOOK_URL)
            secret: Secret para assinatura HMAC (opcional)
            method: HTTP method (POST ou PUT)
            headers: Headers customizados
        """
        super().__init__(NotificationChannel.WEBHOOK)
        
        self.webhook_url = webhook_url or os.getenv("WEBHOOK_URL")
        self.secret = secret or os.getenv("WEBHOOK_SECRET")
        self.method = method.upper()
        self.headers = headers or {}
        
        # Headers padrão
        self.headers.setdefault("Content-Type", "application/json")
        self.headers.setdefault("User-Agent", "AutoHunter/1.0")
        
        if self.webhook_url:
            self.enable()
        else:
            self.logger.warning("Webhook URL not configured")
    
    def send(self, notification: Notification) -> NotificationResult:
        """Envia via webhook.
        
        Args:
            notification: Notificação a enviar
        
        Returns:
            Resultado do envio
        """
        if not self.is_enabled():
            return self._create_error_result("Webhook notifier not enabled")
        
        if not self.validate_recipient(notification.recipient):
            # Recipient pode ser ignorado para webhooks (usa URL configurada)
            pass
        
        try:
            # Monta payload
            payload = self._build_payload(notification)
            
            # Adiciona assinatura HMAC se secret configurado
            headers = self.headers.copy()
            if self.secret:
                signature = self._sign_payload(payload)
                headers["X-Webhook-Signature"] = signature
            
            # Envia request
            if self.method == "POST":
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=10,
                )
            elif self.method == "PUT":
                response = requests.put(
                    self.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=10,
                )
            else:
                return self._create_error_result(f"Unsupported method: {self.method}")
            
            response.raise_for_status()
            
            result = self._create_success_result(
                message_id=f"webhook-{response.status_code}",
                metadata={
                    "status_code": response.status_code,
                    "url": self.webhook_url,
                }
            )
            
            self._log_send(notification, result)
            return result
            
        except requests.RequestException as e:
            result = self._create_error_result(str(e))
            self._log_send(notification, result)
            return result
    
    def validate_recipient(self, recipient: str) -> bool:
        """Webhook não usa recipient (usa URL configurada).
        
        Returns:
            Always True
        """
        return True
    
    def _build_payload(self, notification: Notification) -> Dict[str, Any]:
        """Monta payload do webhook.
        
        Args:
            notification: Notificação
        
        Returns:
            Dict com payload
        """
        payload = {
            "channel": self.channel.value,
            "subject": notification.subject,
            "message": notification.message,
            "priority": notification.priority.value,
            "timestamp": notification.created_at.isoformat() if notification.created_at else None,
        }
        
        # Adiciona metadata se houver
        if notification.metadata:
            payload["metadata"] = notification.metadata
        
        return payload
    
    def _sign_payload(self, payload: Dict[str, Any]) -> str:
        """Assina payload com HMAC-SHA256.
        
        Args:
            payload: Payload a assinar
        
        Returns:
            Assinatura hexadecimal
        """
        import json
        
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            self.secret.encode(),
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    @staticmethod
    def verify_signature(payload: Dict[str, Any], signature: str, secret: str) -> bool:
        """Verifica assinatura de webhook recebido.
        
        Args:
            payload: Payload recebido
            signature: Assinatura recebida
            secret: Secret configurado
        
        Returns:
            True se assinatura válida
        """
        import json
        
        payload_str = json.dumps(payload, sort_keys=True)
        expected_signature = hmac.new(
            secret.encode(),
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected_signature)
