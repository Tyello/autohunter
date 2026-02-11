"""
Health Check e Monitoring

Script para verificar saúde do sistema e realizar monitoramento contínuo.

Uso:
    python scripts/health_check.py           # Check único
    python scripts/health_check.py --monitor # Monitoring contínuo
"""

import sys
import time
import argparse
from datetime import datetime
from typing import Dict, Any

import psutil
from sqlalchemy import text

from app.db.session import SessionLocal
from app.core.resource_monitor import resource_monitor
from app.core.throttler import auto_throttler
from app.core.cache import scraping_cache, vehicle_cache


def check_database() -> Dict[str, Any]:
    """Verifica saúde do banco de dados."""
    
    try:
        db = SessionLocal()
        
        # Testa conexão
        start = time.time()
        result = db.execute(text("SELECT 1"))
        elapsed_ms = (time.time() - start) * 1000
        
        # Conta registros
        car_count = db.execute(text("SELECT COUNT(*) FROM car_listings")).scalar()
        
        db.close()
        
        return {
            "status": "healthy",
            "response_time_ms": round(elapsed_ms, 2),
            "car_listings_count": car_count,
            "connection_ok": True,
        }
    
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "connection_ok": False,
        }


def check_cache() -> Dict[str, Any]:
    """Verifica status do cache."""
    
    scraping_stats = scraping_cache.get_stats()
    vehicle_stats = vehicle_cache.get_stats()
    
    return {
        "status": "healthy",
        "scraping_cache": scraping_stats,
        "vehicle_cache": vehicle_stats,
        "total_memory_mb": scraping_stats["memory_usage_mb"] + vehicle_stats["memory_usage_mb"],
    }


def check_system_resources() -> Dict[str, Any]:
    """Verifica recursos do sistema."""
    
    health = resource_monitor.check_health()
    
    return {
        "status": health["status"],
        "alerts": health["alerts"],
        "warnings": health["warnings"],
        "snapshot": health["snapshot"],
        "throttle_recommended": health["throttle_recommended"],
    }


def check_disk_space() -> Dict[str, Any]:
    """Verifica espaço em disco."""
    
    disk = psutil.disk_usage("/")
    
    status = "healthy"
    alerts = []
    
    if disk.percent > 95:
        status = "critical"
        alerts.append("Disk usage critical (>95%)")
    elif disk.percent > 90:
        status = "warning"
        alerts.append("Disk usage high (>90%)")
    
    return {
        "status": status,
        "percent": disk.percent,
        "free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
        "total_gb": round(disk.total / 1024 / 1024 / 1024, 2),
        "alerts": alerts,
    }


def check_processes() -> Dict[str, Any]:
    """Verifica processos do sistema."""
    
    process_count = len(psutil.pids())
    
    # Processos Python
    python_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            if 'python' in proc.info['name'].lower():
                python_processes.append({
                    "pid": proc.info['pid'],
                    "name": proc.info['name'],
                    "cpu_percent": proc.info['cpu_percent'],
                    "memory_percent": round(proc.info['memory_percent'], 2),
                })
        except:
            pass
    
    return {
        "status": "healthy",
        "total_processes": process_count,
        "python_processes": len(python_processes),
        "top_python_processes": sorted(
            python_processes,
            key=lambda x: x['memory_percent'],
            reverse=True
        )[:5],
    }


def run_health_check() -> Dict[str, Any]:
    """Executa health check completo."""
    
    print("="*60)
    print("🏥 AUTOHUNTER HEALTH CHECK")
    print(f"   Time: {datetime.now()}")
    print("="*60)
    print()
    
    results = {}
    overall_status = "healthy"
    
    # Database
    print("📊 Database...")
    db_health = check_database()
    results["database"] = db_health
    
    if db_health["status"] != "healthy":
        overall_status = "unhealthy"
        print(f"   ❌ {db_health['status']}: {db_health.get('error', 'Unknown error')}")
    else:
        print(f"   ✅ {db_health['status']}")
        print(f"      Response time: {db_health['response_time_ms']}ms")
        print(f"      Car listings: {db_health['car_listings_count']}")
    print()
    
    # Cache
    print("💾 Cache...")
    cache_health = check_cache()
    results["cache"] = cache_health
    print(f"   ✅ {cache_health['status']}")
    print(f"      Scraping cache: {cache_health['scraping_cache']['size']} items, {cache_health['scraping_cache']['hit_rate']}% hit rate")
    print(f"      Vehicle cache: {cache_health['vehicle_cache']['size']} items, {cache_health['vehicle_cache']['hit_rate']}% hit rate")
    print(f"      Total memory: {cache_health['total_memory_mb']:.2f} MB")
    print()
    
    # Resources
    print("⚡ System Resources...")
    resource_health = check_system_resources()
    results["resources"] = resource_health
    
    if resource_health["status"] == "critical":
        overall_status = "critical"
        print(f"   ❌ CRITICAL")
    elif resource_health["status"] == "warning":
        if overall_status == "healthy":
            overall_status = "warning"
        print(f"   ⚠️  WARNING")
    else:
        print(f"   ✅ {resource_health['status']}")
    
    snapshot = resource_health["snapshot"]
    print(f"      CPU: {snapshot['cpu_percent']}%")
    print(f"      Memory: {snapshot['memory_percent']}% ({snapshot['memory_available_mb']} MB available)")
    
    if snapshot['temperature_c']:
        print(f"      Temperature: {snapshot['temperature_c']}°C")
    
    if resource_health["alerts"]:
        for alert in resource_health["alerts"]:
            print(f"      🚨 {alert}")
    
    if resource_health["warnings"]:
        for warning in resource_health["warnings"]:
            print(f"      ⚠️  {warning}")
    
    print()
    
    # Disk
    print("💽 Disk Space...")
    disk_health = check_disk_space()
    results["disk"] = disk_health
    
    if disk_health["status"] == "critical":
        overall_status = "critical"
        print(f"   ❌ CRITICAL")
    elif disk_health["status"] == "warning":
        if overall_status == "healthy":
            overall_status = "warning"
        print(f"   ⚠️  WARNING")
    else:
        print(f"   ✅ {disk_health['status']}")
    
    print(f"      Used: {disk_health['percent']}%")
    print(f"      Free: {disk_health['free_gb']:.2f} GB")
    
    if disk_health["alerts"]:
        for alert in disk_health["alerts"]:
            print(f"      🚨 {alert}")
    
    print()
    
    # Processes
    print("🔄 Processes...")
    process_health = check_processes()
    results["processes"] = process_health
    print(f"   ✅ {process_health['status']}")
    print(f"      Total: {process_health['total_processes']}")
    print(f"      Python: {process_health['python_processes']}")
    
    if process_health["top_python_processes"]:
        print(f"      Top Python processes:")
        for proc in process_health["top_python_processes"][:3]:
            print(f"        PID {proc['pid']}: {proc['memory_percent']:.1f}% RAM, {proc['cpu_percent']:.1f}% CPU")
    
    print()
    
    # Throttler status
    print("🎛️  Auto Throttler...")
    throttle_config = auto_throttler.get_current_config()
    results["throttler"] = throttle_config
    print(f"   Level: {throttle_config['throttle_level']}")
    print(f"   Concurrent scrapers: {throttle_config['concurrent_scrapers']}")
    print(f"   Delay: {throttle_config['delay_ms']}ms")
    print()
    
    # Overall
    print("="*60)
    
    if overall_status == "healthy":
        print("✅ Overall Status: HEALTHY")
    elif overall_status == "warning":
        print("⚠️  Overall Status: WARNING")
    else:
        print("❌ Overall Status: CRITICAL")
    
    print("="*60)
    print()
    
    results["overall_status"] = overall_status
    results["timestamp"] = datetime.now().isoformat()
    
    return results


def monitor_continuous(interval: int = 60):
    """Monitoramento contínuo.
    
    Args:
        interval: Intervalo entre checks em segundos
    """
    
    print(f"🔄 Starting continuous monitoring (interval: {interval}s)")
    print("   Press Ctrl+C to stop")
    print()
    
    try:
        while True:
            results = run_health_check()
            
            # Auto-ajusta throttling se necessário
            if results["resources"]["throttle_recommended"]:
                print("⚙️  Auto-adjusting throttle...")
                throttle_result = auto_throttler.adjust()
                print(f"   New level: {throttle_result['throttle_level']}")
                print()
            
            # Cleanup de cache expirado
            scraping_expired = scraping_cache.cleanup_expired()
            vehicle_expired = vehicle_cache.cleanup_expired()
            
            if scraping_expired > 0 or vehicle_expired > 0:
                print(f"🧹 Cleaned {scraping_expired + vehicle_expired} expired cache entries")
                print()
            
            # Aguarda próximo check
            time.sleep(interval)
    
    except KeyboardInterrupt:
        print()
        print("✅ Monitoring stopped")


def main():
    """Main function."""
    
    parser = argparse.ArgumentParser(description="AutoHunter Health Check")
    parser.add_argument("--monitor", action="store_true", help="Continuous monitoring mode")
    parser.add_argument("--interval", type=int, default=60, help="Monitoring interval in seconds")
    
    args = parser.parse_args()
    
    if args.monitor:
        monitor_continuous(interval=args.interval)
    else:
        run_health_check()


if __name__ == "__main__":
    main()
