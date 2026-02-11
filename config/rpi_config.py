"""
Raspberry Pi Optimized Configuration

Configurações específicas e otimizadas para rodar em Raspberry Pi.
"""

from typing import Dict, Any
import os


class RaspberryPiConfig:
    """Configurações otimizadas para Raspberry Pi."""
    
    # ========== Hardware Detection ==========
    
    # Raspberry Pi 4 (4GB RAM)
    RPI_4_4GB = {
        "name": "Raspberry Pi 4 (4GB)",
        "ram_gb": 4,
        "cpu_cores": 4,
        "recommended_browser_instances": 2,
        "recommended_concurrent_scrapers": 3,
        "max_cache_mb": 200,
    }
    
    # Raspberry Pi 4 (8GB RAM)
    RPI_4_8GB = {
        "name": "Raspberry Pi 4 (8GB)",
        "ram_gb": 8,
        "cpu_cores": 4,
        "recommended_browser_instances": 3,
        "recommended_concurrent_scrapers": 4,
        "max_cache_mb": 400,
    }
    
    # Raspberry Pi 3
    RPI_3 = {
        "name": "Raspberry Pi 3",
        "ram_gb": 1,
        "cpu_cores": 4,
        "recommended_browser_instances": 1,
        "recommended_concurrent_scrapers": 2,
        "max_cache_mb": 50,
    }
    
    # Generic (fallback)
    GENERIC = {
        "name": "Generic",
        "ram_gb": 2,
        "cpu_cores": 2,
        "recommended_browser_instances": 1,
        "recommended_concurrent_scrapers": 2,
        "max_cache_mb": 100,
    }
    
    # ========== Database Settings ==========
    
    DATABASE = {
        # Connection Pool (ajustado para RAM limitada)
        "pool_size": 5,  # Conexões ativas
        "max_overflow": 10,  # Conexões extras
        "pool_timeout": 30,  # Timeout para obter conexão
        "pool_recycle": 3600,  # Recicla após 1h
        "pool_pre_ping": True,  # Verifica conexão antes de usar
        
        # Query Optimization
        "echo": False,  # Desabilita SQL logging (performance)
        "query_cache_size": 500,  # Cache de queries compiladas
    }
    
    # ========== Browser Settings ==========
    
    BROWSER = {
        # Playwright/Chromium otimizado
        "headless": True,
        "args": [
            "--disable-gpu",
            "--disable-dev-shm-usage",  # CRÍTICO para Docker/RPi
            "--disable-setuid-sandbox",
            "--no-sandbox",
            "--disable-accelerated-2d-canvas",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-blink-features=AutomationControlled",
            
            # Memory optimization
            "--memory-pressure-off",
            "--max-old-space-size=512",  # Limite de memória Node.js
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-client-side-phishing-detection",
            "--disable-component-extensions-with-background-pages",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-features=TranslateUI",
            "--disable-hang-monitor",
            "--disable-ipc-flooding-protection",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-renderer-backgrounding",
            "--disable-sync",
            "--force-color-profile=srgb",
            "--metrics-recording-only",
            "--no-first-run",
            "--enable-automation",
            "--password-store=basic",
            "--use-mock-keychain",
        ],
        
        # Timeouts
        "default_timeout": 30000,  # 30s
        "navigation_timeout": 60000,  # 1min
        
        # Resource blocking
        "block_resources": ["image", "stylesheet", "font", "media"],
        
        # Browser context
        "viewport": {"width": 1280, "height": 720},
        "user_agent": "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36",
        "java_script_enabled": True,
    }
    
    # ========== Scraping Settings ==========
    
    SCRAPING = {
        # Concurrency
        "max_concurrent_scrapers": 2,  # Será ajustado por auto-throttler
        "max_concurrent_http_requests": 10,
        "max_concurrent_browser_pages": 2,
        
        # Delays
        "min_delay_ms": 500,
        "max_delay_ms": 2000,
        "retry_delay_ms": 3000,
        
        # Retries
        "max_retries": 3,
        "retry_on_errors": ["timeout", "connection", "502", "503"],
        
        # Timeouts
        "http_timeout_s": 30,
        "browser_timeout_s": 60,
        
        # Batch processing
        "batch_size": 50,
        "batch_delay_s": 5,
    }
    
    # ========== Cache Settings ==========
    
    CACHE = {
        # Scraping cache
        "scraping_cache_size": 500,
        "scraping_cache_ttl": 1800,  # 30min
        "scraping_cache_max_mb": 30,
        
        # Vehicle cache
        "vehicle_cache_size": 1000,
        "vehicle_cache_ttl": 3600,  # 1h
        "vehicle_cache_max_mb": 20,
        
        # Persist to disk
        "persist_cache": True,
        "cache_dir": "cache",
    }
    
    # ========== Logging ==========
    
    LOGGING = {
        "level": "INFO",  # DEBUG muito verboso
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        "date_format": "%Y-%m-%d %H:%M:%S",
        
        # File logging (rotação para economizar disco)
        "file_enabled": True,
        "file_path": "logs/autohunter.log",
        "file_max_bytes": 10 * 1024 * 1024,  # 10MB
        "file_backup_count": 5,  # Mantém 5 arquivos
        
        # Console logging
        "console_enabled": True,
        "console_level": "INFO",
    }
    
    # ========== Monitoring ==========
    
    MONITORING = {
        # Resource check interval
        "check_interval_s": 60,  # Verifica a cada 1min
        
        # Health check
        "health_check_enabled": True,
        "health_check_interval_s": 300,  # 5min
        
        # Auto-throttle
        "auto_throttle_enabled": True,
        "throttle_check_interval_s": 30,  # 30s
        
        # Metrics retention
        "metrics_retention_hours": 24,  # Mantém últimas 24h
    }
    
    # ========== Cleanup ==========
    
    CLEANUP = {
        # Auto cleanup de dados antigos
        "cleanup_enabled": True,
        "cleanup_interval_hours": 24,
        
        # Retention
        "car_listings_retention_days": 90,
        "auction_lots_retention_days": 60,
        "logs_retention_days": 30,
        "cache_cleanup_interval_hours": 6,
    }
    
    @classmethod
    def get_config_for_system(cls) -> Dict[str, Any]:
        """Detecta sistema e retorna config otimizada."""
        import psutil
        
        # Detecta RAM
        ram_gb = round(psutil.virtual_memory().total / 1024 / 1024 / 1024)
        cpu_count = psutil.cpu_count()
        
        # Seleciona perfil
        if ram_gb >= 8:
            profile = cls.RPI_4_8GB
        elif ram_gb >= 4:
            profile = cls.RPI_4_4GB
        elif ram_gb >= 1:
            profile = cls.RPI_3
        else:
            profile = cls.GENERIC
        
        return {
            "profile": profile,
            "database": cls.DATABASE,
            "browser": cls.BROWSER,
            "scraping": cls.SCRAPING,
            "cache": cls.CACHE,
            "logging": cls.LOGGING,
            "monitoring": cls.MONITORING,
            "cleanup": cls.CLEANUP,
        }
    
    @classmethod
    def generate_env_file(cls, output_path: str = ".env.rpi") -> None:
        """Gera arquivo .env otimizado para RPi."""
        
        config = cls.get_config_for_system()
        profile = config["profile"]
        
        env_content = f"""# AutoHunter - Raspberry Pi Optimized Configuration
# Generated for: {profile['name']}
# RAM: {profile['ram_gb']}GB, CPU: {profile['cpu_cores']} cores

# ========== Database ==========
DB_POOL_SIZE={cls.DATABASE['pool_size']}
DB_MAX_OVERFLOW={cls.DATABASE['max_overflow']}
DB_POOL_TIMEOUT={cls.DATABASE['pool_timeout']}
DB_POOL_RECYCLE={cls.DATABASE['pool_recycle']}

# ========== Browser ==========
BROWSER_HEADLESS=true
BROWSER_MAX_INSTANCES={profile['recommended_browser_instances']}
BROWSER_TIMEOUT_MS={cls.BROWSER['default_timeout']}
BROWSER_BLOCK_RESOURCES=true

# ========== Scraping ==========
MAX_CONCURRENT_SCRAPERS={profile['recommended_concurrent_scrapers']}
MAX_CONCURRENT_HTTP={cls.SCRAPING['max_concurrent_http_requests']}
MIN_DELAY_MS={cls.SCRAPING['min_delay_ms']}
MAX_DELAY_MS={cls.SCRAPING['max_delay_ms']}
BATCH_SIZE={cls.SCRAPING['batch_size']}

# ========== Cache ==========
CACHE_ENABLED=true
CACHE_MAX_MB={profile['max_cache_mb']}
CACHE_PERSIST=true

# ========== Monitoring ==========
AUTO_THROTTLE_ENABLED=true
HEALTH_CHECK_ENABLED=true
RESOURCE_CHECK_INTERVAL_S={cls.MONITORING['check_interval_s']}

# ========== Logging ==========
LOG_LEVEL={cls.LOGGING['level']}
LOG_FILE_ENABLED={str(cls.LOGGING['file_enabled']).lower()}
LOG_FILE_MAX_MB=10
LOG_BACKUP_COUNT=5

# ========== Cleanup ==========
AUTO_CLEANUP_ENABLED=true
CLEANUP_INTERVAL_HOURS={cls.CLEANUP['cleanup_interval_hours']}
CAR_LISTINGS_RETENTION_DAYS={cls.CLEANUP['car_listings_retention_days']}
"""
        
        with open(output_path, "w") as f:
            f.write(env_content)
        
        print(f"✅ Config file generated: {output_path}")
        print(f"   Profile: {profile['name']}")
        print(f"   Recommended scrapers: {profile['recommended_concurrent_scrapers']}")
        print(f"   Recommended browsers: {profile['recommended_browser_instances']}")


# ========== Convenience Functions ==========

def get_rpi_config() -> Dict[str, Any]:
    """Obtém configuração otimizada para o sistema atual."""
    return RaspberryPiConfig.get_config_for_system()


def is_raspberry_pi() -> bool:
    """Detecta se está rodando em Raspberry Pi."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()
            return "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo
    except:
        return False
