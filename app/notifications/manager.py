"""
Notification Manager

Gerenciador central de notificações que coordena todos os canais.

Features:
- Multi-canal (Telegram, WhatsApp, Email, SMS, Webhook)
- Retry logic com backoff exponencial
- Rate limiting por canal
- Queue de notificações
- Logging e tracking
- Fallback entre canais
"""

import time
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from collections import deque
import logging
import threading

from app.notifications.base import (
    Notification,
    NotificationResult,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)
from app.notifications.telegram import TelegramNotifier
from app.notifications.whatsapp import WhatsAppNotifier
from app.notifications.email import EmailNotifier
from app.notifications.webhook import WebhookNotifier


class NotificationQueue:
    """Fila de notificações com prioridade."""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.queues = {
            NotificationPriority.URGENT: deque(),
            NotificationPriority.HIGH: deque(),
            NotificationPriority.NORMAL: deque(),
            NotificationPriority.LOW: deque(),
        }
        self.lock = threading.Lock()
    
    def put(self, notification: Notification) -> bool:
        """Adiciona notificação na fila.
        
        Returns:
            True se adicionado
        """
        with self.lock:
            if self.size() >= self.max_size:
                return False
            
            self.queues[notification.priority].append(notification)
            return True
    
    def get(self) -> Optional[Notification]:
        """Remove e retorna próxima notificação (maior prioridade).
        
        Returns:
            Notificação ou None se fila vazia
        """
        with self.lock:
            # Verifica em ordem de prioridade
            for priority in [
                NotificationPriority.URGENT,
                NotificationPriority.HIGH,
                NotificationPriority.NORMAL,
                NotificationPriority.LOW
            ]:
                if self.queues[priority]:
                    return self.queues[priority].popleft()
            
            return None
    
    def size(self) -> int:
        """Retorna tamanho total da fila."""
        with self.lock:
            return sum(len(q) for q in self.queues.values())
    
    def clear(self):
        """Limpa toda a fila."""
        with self.lock:
            for queue in self.queues.values():
                queue.clear()


class RateLimiter:
    """Rate limiter simples por janela deslizante."""
    
    def __init__(self, max_requests: int, window_seconds: int):
        """
        Args:
            max_requests: Máximo de requests na janela
            window_seconds: Tamanho da janela em segundos
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = deque()
        self.lock = threading.Lock()
    
    def allow(self) -> bool:
        """Verifica se request é permitido.
        
        Returns:
            True se dentro do limite
        """
        with self.lock:
            now = time.time()
            
            # Remove requests antigas (fora da janela)
            while self.requests and self.requests[0] < now - self.window_seconds:
                self.requests.popleft()
            
            # Verifica limite
            if len(self.requests) >= self.max_requests:
                return False
            
            # Adiciona novo request
            self.requests.append(now)
            return True
    
    def wait_time(self) -> float:
        """Retorna tempo de espera até próximo slot disponível.
        
        Returns:
            Segundos a esperar
        """
        with self.lock:
            if len(self.requests) < self.max_requests:
                return 0.0
            
            oldest = self.requests[0]
            wait = (oldest + self.window_seconds) - time.time()
            return max(0.0, wait)


class NotificationManager:
    """Gerenciador central de notificações."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Inicializa notifiers
        self.notifiers = {
            NotificationChannel.TELEGRAM: TelegramNotifier(),
            NotificationChannel.WHATSAPP: WhatsAppNotifier(),
            NotificationChannel.EMAIL: EmailNotifier(),
            NotificationChannel.WEBHOOK: WebhookNotifier(),
        }
        
        # Queue
        self.queue = NotificationQueue()
        
        # Rate limiters (por canal)
        self.rate_limiters = {
            NotificationChannel.TELEGRAM: RateLimiter(max_requests=20, window_seconds=60),
            NotificationChannel.WHATSAPP: RateLimiter(max_requests=10, window_seconds=60),
            NotificationChannel.EMAIL: RateLimiter(max_requests=50, window_seconds=60),
            NotificationChannel.WEBHOOK: RateLimiter(max_requests=100, window_seconds=60),
        }
        
        # Tracking
        self.sent_count = 0
        self.failed_count = 0
        self.retry_count = 0
        
        # Worker thread
        self.worker_running = False
        self.worker_thread = None
    
    def send(
        self,
        channel: NotificationChannel,
        recipient: str,
        subject: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict] = None,
        async_mode: bool = True,
    ) -> NotificationResult:
        """Envia notificação.
        
        Args:
            channel: Canal de notificação
            recipient: Destinatário
            subject: Assunto
            message: Mensagem
            priority: Prioridade
            metadata: Dados extras
            async_mode: Se True, adiciona na queue; se False, envia imediatamente
        
        Returns:
            Resultado do envio
        """
        notification = Notification(
            channel=channel,
            recipient=recipient,
            subject=subject,
            message=message,
            priority=priority,
            metadata=metadata,
        )
        
        if async_mode:
            # Adiciona na queue
            if self.queue.put(notification):
                self.logger.info(f"Notification queued: {channel.value} to {recipient}")
                return NotificationResult(
                    success=True,
                    channel=channel,
                    message_id="queued",
                )
            else:
                self.logger.error("Notification queue full")
                return NotificationResult(
                    success=False,
                    channel=channel,
                    error="Queue full",
                )
        else:
            # Envia imediatamente
            return self._send_notification(notification)
    
    def send_multi_channel(
        self,
        channels: List[NotificationChannel],
        recipient_map: Dict[NotificationChannel, str],
        subject: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        fallback: bool = True,
    ) -> Dict[NotificationChannel, NotificationResult]:
        """Envia via múltiplos canais.
        
        Args:
            channels: Lista de canais
            recipient_map: Mapa canal -> destinatário
            subject: Assunto
            message: Mensagem
            priority: Prioridade
            fallback: Se True, tenta próximo canal se primeiro falhar
        
        Returns:
            Dict com resultados por canal
        """
        results = {}
        
        for channel in channels:
            recipient = recipient_map.get(channel)
            if not recipient:
                continue
            
            result = self.send(
                channel=channel,
                recipient=recipient,
                subject=subject,
                message=message,
                priority=priority,
                async_mode=False,  # Síncrono para fallback
            )
            
            results[channel] = result
            
            # Se sucesso ou não quer fallback, para
            if result.success or not fallback:
                break
        
        return results
    
    def _send_notification(self, notification: Notification) -> NotificationResult:
        """Envia notificação com retry logic.
        
        Args:
            notification: Notificação a enviar
        
        Returns:
            Resultado do envio
        """
        notifier = self.notifiers.get(notification.channel)
        
        if not notifier:
            return NotificationResult(
                success=False,
                channel=notification.channel,
                error=f"Notifier not available for {notification.channel.value}",
            )
        
        if not notifier.is_enabled():
            return NotificationResult(
                success=False,
                channel=notification.channel,
                error=f"{notification.channel.value} notifier not enabled",
            )
        
        # Retry logic
        max_attempts = notification.max_attempts
        backoff = 1  # segundos
        
        for attempt in range(1, max_attempts + 1):
            notification.attempts = attempt
            
            # Rate limiting
            rate_limiter = self.rate_limiters.get(notification.channel)
            if rate_limiter:
                while not rate_limiter.allow():
                    wait = rate_limiter.wait_time()
                    self.logger.info(f"Rate limit reached, waiting {wait:.1f}s")
                    time.sleep(wait)
            
            # Envia
            result = notifier.send(notification)
            
            if result.success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.utcnow()
                self.sent_count += 1
                return result
            
            # Falhou
            notification.status = NotificationStatus.RETRY
            self.retry_count += 1
            
            # Se não é última tentativa, aguarda backoff
            if attempt < max_attempts:
                self.logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed, "
                    f"retrying in {backoff}s: {result.error}"
                )
                time.sleep(backoff)
                backoff *= 2  # Exponential backoff
        
        # Todas as tentativas falharam
        notification.status = NotificationStatus.FAILED
        self.failed_count += 1
        
        return result
    
    def start_worker(self):
        """Inicia worker thread para processar queue."""
        if self.worker_running:
            self.logger.warning("Worker already running")
            return
        
        self.worker_running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        self.logger.info("Notification worker started")
    
    def stop_worker(self):
        """Para worker thread."""
        self.worker_running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        self.logger.info("Notification worker stopped")
    
    def _worker_loop(self):
        """Loop do worker que processa queue."""
        while self.worker_running:
            notification = self.queue.get()
            
            if notification:
                self._send_notification(notification)
            else:
                # Queue vazia, aguarda
                time.sleep(1)
    
    def get_stats(self) -> Dict:
        """Retorna estatísticas."""
        return {
            "queue_size": self.queue.size(),
            "sent_count": self.sent_count,
            "failed_count": self.failed_count,
            "retry_count": self.retry_count,
            "enabled_channels": [
                channel.value for channel, notifier in self.notifiers.items()
                if notifier.is_enabled()
            ],
        }
    
    def get_notifier(self, channel: NotificationChannel):
        """Retorna notifier de um canal."""
        return self.notifiers.get(channel)


# Instância global
_manager = None


def get_notification_manager() -> NotificationManager:
    """Retorna instância global do manager."""
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager
