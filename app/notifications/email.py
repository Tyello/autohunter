"""
Email Notifier

Notificador via SMTP ou AWS SES.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import re

from app.notifications.base import (
    BaseNotifier,
    Notification,
    NotificationResult,
    NotificationChannel,
)


class EmailNotifier(BaseNotifier):
    """Notificador Email (SMTP ou SES)."""
    
    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: Optional[str] = None,
        use_tls: bool = True,
        use_ses: bool = False,
    ):
        """Inicializa Email notifier.
        
        Args:
            smtp_host: SMTP host (ou via env SMTP_HOST)
            smtp_port: SMTP port (ou via env SMTP_PORT, default: 587)
            smtp_user: SMTP user (ou via env SMTP_USER)
            smtp_password: SMTP password (ou via env SMTP_PASSWORD)
            from_email: From email (ou via env FROM_EMAIL)
            use_tls: Usar TLS (default: True)
            use_ses: Usar AWS SES ao invés de SMTP
        """
        super().__init__(NotificationChannel.EMAIL)
        
        self.use_ses = use_ses or os.getenv("USE_AWS_SES", "false").lower() == "true"
        
        if self.use_ses:
            self._init_ses()
        else:
            self._init_smtp(smtp_host, smtp_port, smtp_user, smtp_password, from_email, use_tls)
    
    def _init_smtp(self, host, port, user, password, from_email, use_tls):
        """Inicializa SMTP."""
        self.smtp_host = host or os.getenv("SMTP_HOST")
        self.smtp_port = port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = user or os.getenv("SMTP_USER")
        self.smtp_password = password or os.getenv("SMTP_PASSWORD")
        self.from_email = from_email or os.getenv("FROM_EMAIL", self.smtp_user)
        self.use_tls = use_tls
        
        if self.smtp_host and self.smtp_user and self.smtp_password:
            self.enable()
        else:
            self.logger.warning("SMTP credentials not fully configured")
    
    def _init_ses(self):
        """Inicializa AWS SES."""
        try:
            import boto3
            self.ses_client = boto3.client(
                'ses',
                region_name=os.getenv("AWS_REGION", "us-east-1"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            )
            self.from_email = os.getenv("SES_FROM_EMAIL")
            
            if self.from_email:
                self.enable()
            else:
                self.logger.warning("SES from_email not configured")
                
        except ImportError:
            self.logger.error("boto3 not installed. Run: pip install boto3")
        except Exception as e:
            self.logger.error(f"Failed to initialize SES: {e}")
    
    def send(self, notification: Notification) -> NotificationResult:
        """Envia email.
        
        Args:
            notification: Notificação a enviar
        
        Returns:
            Resultado do envio
        """
        if not self.is_enabled():
            return self._create_error_result("Email notifier not enabled")
        
        if not self.validate_recipient(notification.recipient):
            return self._create_error_result("Invalid email address")
        
        if self.use_ses:
            return self._send_via_ses(notification)
        else:
            return self._send_via_smtp(notification)
    
    def _send_via_smtp(self, notification: Notification) -> NotificationResult:
        """Envia via SMTP."""
        try:
            # Cria mensagem
            msg = MIMEMultipart('alternative')
            msg['Subject'] = notification.subject or "AutoHunter Notification"
            msg['From'] = self.from_email
            msg['To'] = notification.recipient
            
            # Corpo (texto + HTML)
            text_part = MIMEText(notification.message, 'plain', 'utf-8')
            html_part = MIMEText(self._message_to_html(notification.message), 'html', 'utf-8')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            # Conecta e envia
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            result = self._create_success_result(
                message_id=f"smtp-{notification.recipient}",
                metadata={"to": notification.recipient}
            )
            
            self._log_send(notification, result)
            return result
            
        except Exception as e:
            result = self._create_error_result(str(e))
            self._log_send(notification, result)
            return result
    
    def _send_via_ses(self, notification: Notification) -> NotificationResult:
        """Envia via AWS SES."""
        try:
            response = self.ses_client.send_email(
                Source=self.from_email,
                Destination={'ToAddresses': [notification.recipient]},
                Message={
                    'Subject': {'Data': notification.subject or "AutoHunter Notification"},
                    'Body': {
                        'Text': {'Data': notification.message},
                        'Html': {'Data': self._message_to_html(notification.message)},
                    }
                }
            )
            
            result = self._create_success_result(
                message_id=response['MessageId'],
                metadata={"to": notification.recipient}
            )
            
            self._log_send(notification, result)
            return result
            
        except Exception as e:
            result = self._create_error_result(str(e))
            self._log_send(notification, result)
            return result
    
    def validate_recipient(self, recipient: str) -> bool:
        """Valida email.
        
        Args:
            recipient: Email
        
        Returns:
            True se válido
        """
        if not recipient:
            return False
        
        # Regex simples de validação de email
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, recipient))
    
    def _message_to_html(self, message: str) -> str:
        """Converte mensagem texto para HTML básico.
        
        Args:
            message: Mensagem em texto
        
        Returns:
            HTML
        """
        # Escapa HTML
        html_message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Converte quebras de linha
        html_message = html_message.replace("\n", "<br>")
        
        # Detecta URLs e converte em links
        url_pattern = r'(https?://[^\s]+)'
        html_message = re.sub(url_pattern, r'<a href="\1">\1</a>', html_message)
        
        # Wrap em HTML básico
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        a {{ color: #007bff; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        {html_message}
    </div>
</body>
</html>
"""
