"""
Resource Monitor - Monitoramento de Recursos do Sistema

Monitora CPU, memória, disco, temperatura (RPi) e alerta quando
recursos estão próximos do limite.

Essencial para Raspberry Pi com recursos limitados.
"""

import psutil
import time
from datetime import datetime
from typing import Dict, Optional, List
import logging


class ResourceMonitor:
    """Monitor de recursos do sistema."""
    
    def __init__(
        self,
        cpu_threshold: float = 80.0,
        memory_threshold: float = 85.0,
        disk_threshold: float = 90.0,
        temp_threshold: float = 70.0,
    ):
        """Inicializa monitor.
        
        Args:
            cpu_threshold: % de CPU para alertar
            memory_threshold: % de memória para alertar
            disk_threshold: % de disco para alertar
            temp_threshold: Temperatura (°C) para alertar
        """
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.disk_threshold = disk_threshold
        self.temp_threshold = temp_threshold
        
        self.logger = logging.getLogger(__name__)
    
    def get_cpu_usage(self) -> float:
        """Retorna % de uso de CPU."""
        return psutil.cpu_percent(interval=1)
    
    def get_memory_usage(self) -> Dict[str, float]:
        """Retorna informações de memória."""
        mem = psutil.virtual_memory()
        return {
            "total_mb": mem.total / (1024 * 1024),
            "used_mb": mem.used / (1024 * 1024),
            "available_mb": mem.available / (1024 * 1024),
            "percent": mem.percent,
        }
    
    def get_disk_usage(self, path: str = "/") -> Dict[str, float]:
        """Retorna informações de disco."""
        disk = psutil.disk_usage(path)
        return {
            "total_gb": disk.total / (1024 ** 3),
            "used_gb": disk.used / (1024 ** 3),
            "free_gb": disk.free / (1024 ** 3),
            "percent": disk.percent,
        }
    
    def get_temperature(self) -> Optional[float]:
        """Retorna temperatura do CPU (Raspberry Pi).
        
        Returns:
            Temperatura em °C ou None se não disponível
        """
        try:
            # Tenta ler temperatura do RPi
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp = float(f.read().strip()) / 1000.0
                return temp
        except:
            pass
        
        # Tenta usar psutil (outras plataformas)
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        return entries[0].current
        except:
            pass
        
        return None
    
    def get_network_io(self) -> Dict[str, int]:
        """Retorna estatísticas de rede."""
        net = psutil.net_io_counters()
        return {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }
    
    def get_process_info(self, pid: Optional[int] = None) -> Dict:
        """Retorna informações do processo atual ou especificado."""
        try:
            proc = psutil.Process(pid)
            
            mem_info = proc.memory_info()
            
            return {
                "pid": proc.pid,
                "name": proc.name(),
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(interval=0.1),
                "memory_mb": mem_info.rss / (1024 * 1024),
                "memory_percent": proc.memory_percent(),
                "num_threads": proc.num_threads(),
                "create_time": datetime.fromtimestamp(proc.create_time()).isoformat(),
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_all_stats(self) -> Dict:
        """Retorna todas as estatísticas."""
        return {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": self.get_cpu_usage(),
            "memory": self.get_memory_usage(),
            "disk": self.get_disk_usage(),
            "temperature": self.get_temperature(),
            "network": self.get_network_io(),
            "process": self.get_process_info(),
        }
    
    def check_thresholds(self) -> List[str]:
        """Verifica se algum threshold foi ultrapassado.
        
        Returns:
            Lista de alertas (vazia se tudo OK)
        """
        alerts = []
        
        # CPU
        cpu = self.get_cpu_usage()
        if cpu > self.cpu_threshold:
            alerts.append(f"⚠️ CPU alta: {cpu:.1f}% (limite: {self.cpu_threshold}%)")
        
        # Memória
        mem = self.get_memory_usage()
        if mem["percent"] > self.memory_threshold:
            alerts.append(f"⚠️ Memória alta: {mem['percent']:.1f}% (limite: {self.memory_threshold}%)")
        
        # Disco
        disk = self.get_disk_usage()
        if disk["percent"] > self.disk_threshold:
            alerts.append(f"⚠️ Disco cheio: {disk['percent']:.1f}% (limite: {self.disk_threshold}%)")
        
        # Temperatura
        temp = self.get_temperature()
        if temp and temp > self.temp_threshold:
            alerts.append(f"⚠️ Temperatura alta: {temp:.1f}°C (limite: {self.temp_threshold}°C)")
        
        return alerts
    
    def log_stats(self):
        """Loga estatísticas atuais."""
        stats = self.get_all_stats()
        
        self.logger.info(f"CPU: {stats['cpu_percent']:.1f}%")
        self.logger.info(f"Memória: {stats['memory']['percent']:.1f}% "
                        f"({stats['memory']['used_mb']:.0f}MB / {stats['memory']['total_mb']:.0f}MB)")
        self.logger.info(f"Disco: {stats['disk']['percent']:.1f}% "
                        f"({stats['disk']['used_gb']:.1f}GB / {stats['disk']['total_gb']:.1f}GB)")
        
        if stats['temperature']:
            self.logger.info(f"Temperatura: {stats['temperature']:.1f}°C")
        
        # Alerta se necessário
        alerts = self.check_thresholds()
        for alert in alerts:
            self.logger.warning(alert)
    
    def monitor_loop(self, interval: int = 60, max_iterations: Optional[int] = None):
        """Loop de monitoramento contínuo.
        
        Args:
            interval: Intervalo entre checks (segundos)
            max_iterations: Máximo de iterações (None = infinito)
        """
        iteration = 0
        
        while True:
            self.log_stats()
            
            alerts = self.check_thresholds()
            if alerts:
                # Aqui você pode enviar notificação (email, telegram, etc)
                pass
            
            iteration += 1
            if max_iterations and iteration >= max_iterations:
                break
            
            time.sleep(interval)


def print_system_info():
    """Imprime informações do sistema."""
    print("="*60)
    print("INFORMAÇÕES DO SISTEMA")
    print("="*60)
    
    # CPU
    print(f"\n💻 CPU:")
    print(f"   Núcleos físicos: {psutil.cpu_count(logical=False)}")
    print(f"   Núcleos lógicos: {psutil.cpu_count(logical=True)}")
    print(f"   Uso atual: {psutil.cpu_percent(interval=1)}%")
    
    # Memória
    mem = psutil.virtual_memory()
    print(f"\n🧠 Memória:")
    print(f"   Total: {mem.total / (1024**3):.2f} GB")
    print(f"   Disponível: {mem.available / (1024**3):.2f} GB")
    print(f"   Uso: {mem.percent}%")
    
    # Disco
    disk = psutil.disk_usage("/")
    print(f"\n💾 Disco:")
    print(f"   Total: {disk.total / (1024**3):.2f} GB")
    print(f"   Livre: {disk.free / (1024**3):.2f} GB")
    print(f"   Uso: {disk.percent}%")
    
    # Temperatura
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = float(f.read().strip()) / 1000.0
            print(f"\n🌡️  Temperatura: {temp:.1f}°C")
    except:
        print(f"\n🌡️  Temperatura: N/A")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    # Teste rápido
    print_system_info()
    
    print("\n🔍 Monitorando recursos...\n")
    
    monitor = ResourceMonitor(
        cpu_threshold=75.0,
        memory_threshold=80.0,
        disk_threshold=85.0,
        temp_threshold=65.0,
    )
    
    # Monitora por 5 minutos
    monitor.monitor_loop(interval=30, max_iterations=10)
