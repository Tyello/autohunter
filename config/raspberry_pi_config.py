"""
Raspberry Pi Configuration - Configurações Otimizadas

Este arquivo contém configurações específicas para rodar
AutoHunter em Raspberry Pi com recursos limitados.
"""

# ========== PostgreSQL Configuration ==========

POSTGRESQL_RASPBERRY_PI_CONFIG = """
# postgresql.conf - Configurações para Raspberry Pi

# Memória (para RPi com 4GB RAM)
shared_buffers = 256MB              # 25% da RAM disponível
effective_cache_size = 1GB          # 50-75% da RAM total
work_mem = 4MB                      # Memória por operação de sort
maintenance_work_mem = 64MB         # Memória para VACUUM, CREATE INDEX

# Checkpoints (reduz I/O em SD card)
checkpoint_completion_target = 0.9
wal_buffers = 16MB
min_wal_size = 512MB
max_wal_size = 1GB

# Logging (desabilitar logs desnecessários)
logging_collector = off
log_statement = 'none'
log_duration = off

# Vacuum (mais agressivo para economizar espaço)
autovacuum = on
autovacuum_max_workers = 2
autovacuum_naptime = 30s

# Conexões (limitar para economizar memória)
max_connections = 20

# Query Planner
random_page_cost = 4.0              # SD card é lento para acesso aleatório
effective_io_concurrency = 2        # Limitado em SD card
"""

# ========== Systemd Service Configuration ==========

SYSTEMD_SERVICE_CONFIG = """
# /etc/systemd/system/autohunter.service
# Service file otimizado para Raspberry Pi

[Unit]
Description=AutoHunter - Car Listing Aggregator
After=network.target postgresql.service

[Service]
Type=simple
User=autohunter
Group=autohunter
WorkingDirectory=/home/autohunter/autohunter
Environment="PATH=/home/autohunter/autohunter/venv/bin"
Environment="PYTHONUNBUFFERED=1"

# Limites de recursos
MemoryMax=512M                      # Máximo 512MB de RAM
CPUQuota=75%                        # Máximo 75% de CPU
Nice=10                             # Prioridade baixa

# Restart automático
Restart=on-failure
RestartSec=10s

# Comando
ExecStart=/home/autohunter/autohunter/venv/bin/python -m app.scheduler

[Install]
WantedBy=multi-user.target
"""

# ========== Environment Variables ==========

ENVIRONMENT_CONFIG = """
# .env - Configurações para Raspberry Pi

# Database (conexão local)
DATABASE_URL=postgresql://autohunter:password@localhost/autohunter
SQLALCHEMY_POOL_SIZE=5              # Reduzido (padrão: 10)
SQLALCHEMY_MAX_OVERFLOW=5           # Reduzido (padrão: 10)
SQLALCHEMY_POOL_RECYCLE=1800        # 30 minutos

# Cache
USE_REDIS_CACHE=false               # Redis consome muita memória
CACHE_TTL_SECONDS=600               # 10 minutos

# Browser (Playwright)
BROWSER_HEADLESS=true
BROWSER_TIMEOUT_MS=60000            # 60 segundos (mais tolerante)
BROWSER_MAX_CONCURRENT=1            # Apenas 1 browser por vez (economia de RAM)

# Scraping
MAX_CONCURRENT_SOURCES=2            # Máximo 2 sources simultâneos
SCRAPE_DELAY_SECONDS=5              # Delay maior entre scrapes
HTTP_TIMEOUT_SECONDS=30
HTTP_MAX_RETRIES=2

# Notificações
TELEGRAM_ENABLED=true
EMAIL_ENABLED=false                 # Email consome recursos

# Logging
LOG_LEVEL=INFO                      # Reduzir logs (WARNING em produção)
LOG_TO_FILE=true
LOG_FILE_MAX_MB=10                  # Máximo 10MB por arquivo
LOG_FILE_BACKUP_COUNT=3

# Scheduler
SCHEDULER_INTERVAL_MINUTES=60       # Roda a cada hora (não a cada 15min)
SCHEDULER_MAX_WORKERS=2             # Máximo 2 workers

# Resource Monitoring
ENABLE_RESOURCE_MONITOR=true
RESOURCE_CHECK_INTERVAL=300         # Check a cada 5 minutos
CPU_THRESHOLD=85
MEMORY_THRESHOLD=80
DISK_THRESHOLD=90
TEMP_THRESHOLD=70

# Cleanup
AUTO_CLEANUP_ENABLED=true
CLEANUP_INTERVAL_DAYS=7             # Limpar dados antigos a cada 7 dias
CLEANUP_KEEP_DAYS=90                # Manter últimos 90 dias
"""

# ========== Python Requirements (Minimized) ==========

REQUIREMENTS_MINIMAL = """
# requirements-rpi.txt
# Versão mínima para Raspberry Pi (sem dependências desnecessárias)

# Core
SQLAlchemy==2.0.25
alembic==1.13.1
psycopg2-binary==2.9.9
python-dotenv==1.0.0

# Web Scraping (mínimo)
requests==2.31.0
beautifulsoup4==4.12.3
lxml==5.1.0

# Browser (Playwright - mais leve que Selenium)
playwright==1.41.0

# Utilities
python-dateutil==2.8.2
psutil==5.9.8                       # Monitoramento

# Notificações
python-telegram-bot==20.8           # Telegram apenas
# boto3                             # SES desabilitado para economizar

# Cache (opcional)
# redis==5.0.1                      # Desabilitado por padrão
"""

# ========== Cron Jobs ==========

CRON_JOBS = """
# /etc/cron.d/autohunter
# Cron jobs para manutenção do AutoHunter

# Limpeza de cache a cada 6 horas
0 */6 * * * autohunter /home/autohunter/autohunter/venv/bin/python -c "from scripts.cache_manager import get_cache; get_cache().cleanup_expired()"

# Vacuum database (toda segunda 3am)
0 3 * * 1 autohunter /home/autohunter/autohunter/venv/bin/python scripts/database_optimizer.py vacuum

# Backup database (todos os dias 2am)
0 2 * * * autohunter /home/autohunter/autohunter/scripts/backup_db.sh

# Restart serviço (toda semana)
0 4 * * 0 root systemctl restart autohunter.service

# Cleanup de logs antigos (mensal)
0 0 1 * * autohunter find /home/autohunter/autohunter/logs -name "*.log.*" -mtime +30 -delete
"""

# ========== NGINX Configuration (se usando web interface) ==========

NGINX_CONFIG = """
# /etc/nginx/sites-available/autohunter
# NGINX como reverse proxy (economiza recursos vs Gunicorn)

server {
    listen 80;
    server_name autohunter.local;

    # Limites
    client_max_body_size 1M;
    client_body_timeout 10s;
    client_header_timeout 10s;

    # Compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;

    # Static files (se houver)
    location /static {
        alias /home/autohunter/autohunter/static;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    # API (se houver)
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        # Timeouts
        proxy_connect_timeout 5s;
        proxy_send_timeout 10s;
        proxy_read_timeout 30s;
    }
}
"""

# ========== Guia de Otimização de SD Card ==========

SD_CARD_OPTIMIZATION = """
# Otimizações para SD Card (Raspberry Pi)

1. Usar sistema de arquivos ext4 com options:
   - noatime (não atualiza access time)
   - commit=60 (flush a cada 60s, reduz escritas)

2. Adicionar ao /etc/fstab:
   /dev/mmcblk0p2 / ext4 defaults,noatime,commit=60 0 1

3. Mover diretórios temporários para RAM:
   # /etc/fstab
   tmpfs /tmp tmpfs defaults,noatime,mode=1777,size=100M 0 0
   tmpfs /var/log tmpfs defaults,noatime,mode=0755,size=50M 0 0

4. Desabilitar swap se tiver RAM suficiente:
   sudo dphys-swapfile swapoff
   sudo dphys-swapfile uninstall
   sudo systemctl disable dphys-swapfile

5. Limitar writes do PostgreSQL:
   - fsync = off (apenas para desenvolvimento!)
   - synchronous_commit = off
   - full_page_writes = off

6. Log rotation agressivo:
   - Rotacionar logs a cada 10MB
   - Manter apenas 3 rotações
   - Comprimir com gzip
"""

# ========== Health Check Script ==========

HEALTH_CHECK_SCRIPT = """#!/bin/bash
# /home/autohunter/autohunter/scripts/health_check.sh
# Health check script para Raspberry Pi

set -e

echo "=== AutoHunter Health Check ==="
echo "Data: $(date)"
echo ""

# CPU Temperature
TEMP=$(cat /sys/class/thermal/thermal_zone0/temp)
TEMP_C=$((TEMP/1000))
echo "🌡️  Temperatura: ${TEMP_C}°C"

if [ $TEMP_C -gt 70 ]; then
    echo "⚠️  ALERTA: Temperatura alta!"
fi

# Memory
FREE_MB=$(free -m | awk 'NR==2{print $7}')
echo "🧠 Memória livre: ${FREE_MB}MB"

if [ $FREE_MB -lt 500 ]; then
    echo "⚠️  ALERTA: Pouca memória disponível!"
fi

# Disk
DISK_FREE=$(df -h / | awk 'NR==2{print $5}' | sed 's/%//')
echo "💾 Disco usado: ${DISK_FREE}%"

if [ $DISK_FREE -gt 85 ]; then
    echo "⚠️  ALERTA: Disco quase cheio!"
fi

# Service Status
if systemctl is-active --quiet autohunter.service; then
    echo "✅ Serviço: Running"
else
    echo "❌ Serviço: Stopped"
    systemctl restart autohunter.service
fi

# Database Connection
if psql -U autohunter -d autohunter -c "SELECT 1" > /dev/null 2>&1; then
    echo "✅ Database: OK"
else
    echo "❌ Database: Erro de conexão"
fi

echo ""
echo "=== Health Check Completo ==="
"""


def save_configs():
    """Salva todas as configurações em arquivos."""
    import os
    
    configs_dir = "config/raspberry-pi"
    os.makedirs(configs_dir, exist_ok=True)
    
    configs = {
        "postgresql.conf": POSTGRESQL_RASPBERRY_PI_CONFIG,
        "autohunter.service": SYSTEMD_SERVICE_CONFIG,
        ".env.rpi": ENVIRONMENT_CONFIG,
        "requirements-rpi.txt": REQUIREMENTS_MINIMAL,
        "crontab": CRON_JOBS,
        "nginx.conf": NGINX_CONFIG,
        "sd_card_optimization.txt": SD_CARD_OPTIMIZATION,
        "health_check.sh": HEALTH_CHECK_SCRIPT,
    }
    
    for filename, content in configs.items():
        filepath = os.path.join(configs_dir, filename)
        with open(filepath, "w") as f:
            f.write(content.strip() + "\n")
        print(f"✅ Criado: {filepath}")
    
    # Make health_check.sh executable
    os.chmod(os.path.join(configs_dir, "health_check.sh"), 0o755)
    
    print(f"\n✅ Todas as configurações salvas em: {configs_dir}/")


if __name__ == "__main__":
    save_configs()
