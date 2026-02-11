"""
Notification Configuration

Arquivo de configuração centralizado para notificações.
"""

import os
from typing import Dict, Any


class NotificationConfig:
    """Configuração de notificações."""
    
    # ========== Telegram ==========
    TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    # ========== WhatsApp (Twilio) ==========
    WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
    
    # ========== Email ==========
    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
    
    # SMTP
    USE_AWS_SES = os.getenv("USE_AWS_SES", "false").lower() == "true"
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    FROM_EMAIL = os.getenv("FROM_EMAIL")
    
    # AWS SES (alternativa ao SMTP)
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    SES_FROM_EMAIL = os.getenv("SES_FROM_EMAIL")
    
    # ========== SMS (Twilio) ==========
    SMS_ENABLED = os.getenv("SMS_ENABLED", "false").lower() == "true"
    TWILIO_SMS_NUMBER = os.getenv("TWILIO_SMS_NUMBER")
    
    # ========== Webhook ==========
    WEBHOOK_ENABLED = os.getenv("WEBHOOK_ENABLED", "false").lower() == "true"
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
    WEBHOOK_METHOD = os.getenv("WEBHOOK_METHOD", "POST")
    
    # ========== Rate Limiting ==========
    TELEGRAM_RATE_LIMIT = int(os.getenv("TELEGRAM_RATE_LIMIT", "20"))  # por minuto
    WHATSAPP_RATE_LIMIT = int(os.getenv("WHATSAPP_RATE_LIMIT", "10"))
    EMAIL_RATE_LIMIT = int(os.getenv("EMAIL_RATE_LIMIT", "50"))
    SMS_RATE_LIMIT = int(os.getenv("SMS_RATE_LIMIT", "10"))
    WEBHOOK_RATE_LIMIT = int(os.getenv("WEBHOOK_RATE_LIMIT", "100"))
    
    # ========== Queue ==========
    NOTIFICATION_QUEUE_MAX_SIZE = int(os.getenv("NOTIFICATION_QUEUE_MAX_SIZE", "1000"))
    NOTIFICATION_WORKER_ENABLED = os.getenv("NOTIFICATION_WORKER_ENABLED", "true").lower() == "true"
    
    # ========== Retry ==========
    NOTIFICATION_MAX_RETRIES = int(os.getenv("NOTIFICATION_MAX_RETRIES", "3"))
    NOTIFICATION_RETRY_BACKOFF = float(os.getenv("NOTIFICATION_RETRY_BACKOFF", "2.0"))
    
    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        """Retorna configurações como dict."""
        return {
            "telegram": {
                "enabled": cls.TELEGRAM_ENABLED,
                "configured": bool(cls.TELEGRAM_BOT_TOKEN),
            },
            "whatsapp": {
                "enabled": cls.WHATSAPP_ENABLED,
                "configured": bool(cls.TWILIO_ACCOUNT_SID and cls.TWILIO_AUTH_TOKEN),
            },
            "email": {
                "enabled": cls.EMAIL_ENABLED,
                "use_ses": cls.USE_AWS_SES,
                "configured": bool(
                    (cls.SMTP_HOST and cls.SMTP_USER and cls.SMTP_PASSWORD) or
                    (cls.USE_AWS_SES and cls.SES_FROM_EMAIL)
                ),
            },
            "webhook": {
                "enabled": cls.WEBHOOK_ENABLED,
                "configured": bool(cls.WEBHOOK_URL),
            },
            "queue": {
                "max_size": cls.NOTIFICATION_QUEUE_MAX_SIZE,
                "worker_enabled": cls.NOTIFICATION_WORKER_ENABLED,
            },
            "retry": {
                "max_retries": cls.NOTIFICATION_MAX_RETRIES,
                "backoff": cls.NOTIFICATION_RETRY_BACKOFF,
            },
        }
    
    @classmethod
    def validate(cls) -> Dict[str, str]:
        """Valida configurações.
        
        Returns:
            Dict com erros (vazio se tudo OK)
        """
        errors = {}
        
        # Telegram
        if cls.TELEGRAM_ENABLED and not cls.TELEGRAM_BOT_TOKEN:
            errors["telegram"] = "TELEGRAM_BOT_TOKEN not set"
        
        # WhatsApp
        if cls.WHATSAPP_ENABLED:
            if not cls.TWILIO_ACCOUNT_SID:
                errors["whatsapp_sid"] = "TWILIO_ACCOUNT_SID not set"
            if not cls.TWILIO_AUTH_TOKEN:
                errors["whatsapp_token"] = "TWILIO_AUTH_TOKEN not set"
        
        # Email
        if cls.EMAIL_ENABLED:
            if cls.USE_AWS_SES:
                if not cls.SES_FROM_EMAIL:
                    errors["ses_email"] = "SES_FROM_EMAIL not set"
            else:
                if not cls.SMTP_HOST:
                    errors["smtp_host"] = "SMTP_HOST not set"
                if not cls.SMTP_USER:
                    errors["smtp_user"] = "SMTP_USER not set"
                if not cls.SMTP_PASSWORD:
                    errors["smtp_password"] = "SMTP_PASSWORD not set"
        
        # Webhook
        if cls.WEBHOOK_ENABLED and not cls.WEBHOOK_URL:
            errors["webhook"] = "WEBHOOK_URL not set"
        
        return errors


def print_config():
    """Imprime configurações."""
    import json
    
    print("="*60)
    print("NOTIFICATION CONFIGURATION")
    print("="*60)
    
    config = NotificationConfig.to_dict()
    print(json.dumps(config, indent=2))
    
    print("\n" + "="*60)
    print("VALIDATION")
    print("="*60)
    
    errors = NotificationConfig.validate()
    if errors:
        print("❌ Errors found:")
        for key, error in errors.items():
            print(f"  - {key}: {error}")
    else:
        print("✅ All configurations valid!")


if __name__ == "__main__":
    print_config()
