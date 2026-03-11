"""
Notification Configuration

Arquivo de configuração centralizado para notificações.
"""

from typing import Dict, Any

from app.core.settings import settings


class NotificationConfig:
    """Configuração de notificações."""
    
    # ========== Telegram ==========
    TELEGRAM_ENABLED = settings.telegram_enabled
    TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
    
    # ========== WhatsApp (Twilio) ==========
    WHATSAPP_ENABLED = settings.whatsapp_enabled
    TWILIO_ACCOUNT_SID = settings.twilio_account_sid
    TWILIO_AUTH_TOKEN = settings.twilio_auth_token
    TWILIO_WHATSAPP_NUMBER = settings.twilio_whatsapp_number
    
    # ========== Email ==========
    EMAIL_ENABLED = settings.email_enabled
    
    # SMTP
    USE_AWS_SES = settings.use_aws_ses
    SMTP_HOST = settings.smtp_host
    SMTP_PORT = int(settings.smtp_port)
    SMTP_USER = settings.smtp_user
    SMTP_PASSWORD = settings.smtp_password
    FROM_EMAIL = settings.from_email
    
    # AWS SES (alternativa ao SMTP)
    AWS_REGION = settings.aws_region
    AWS_ACCESS_KEY_ID = settings.aws_access_key_id
    AWS_SECRET_ACCESS_KEY = settings.aws_secret_access_key
    SES_FROM_EMAIL = settings.ses_from_email
    
    # ========== SMS (Twilio) ==========
    SMS_ENABLED = settings.sms_enabled
    TWILIO_SMS_NUMBER = settings.twilio_sms_number
    
    # ========== Webhook ==========
    WEBHOOK_ENABLED = settings.webhook_enabled
    WEBHOOK_URL = settings.webhook_url
    WEBHOOK_SECRET = settings.webhook_secret
    WEBHOOK_METHOD = settings.webhook_method
    
    # ========== Rate Limiting ==========
    TELEGRAM_RATE_LIMIT = int(settings.telegram_rate_limit)  # por minuto
    WHATSAPP_RATE_LIMIT = int(settings.whatsapp_rate_limit)
    EMAIL_RATE_LIMIT = int(settings.email_rate_limit)
    SMS_RATE_LIMIT = int(settings.sms_rate_limit)
    WEBHOOK_RATE_LIMIT = int(settings.webhook_rate_limit)
    
    # ========== Queue ==========
    NOTIFICATION_QUEUE_MAX_SIZE = int(settings.notification_queue_max_size)
    NOTIFICATION_WORKER_ENABLED = settings.notification_worker_enabled
    
    # ========== Retry ==========
    NOTIFICATION_MAX_RETRIES = int(settings.notification_max_retries)
    NOTIFICATION_RETRY_BACKOFF = float(settings.notification_retry_backoff)
    
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
