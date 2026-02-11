"""
Performance Profiler

Script para profiling de performance e identificação de bottlenecks.

Uso:
    python scripts/profile_performance.py
"""

import time
import psutil
import tracemalloc
from typing import Dict, Any, List
from datetime import datetime
import json


class PerformanceProfiler:
    """Profiler de performance."""
    
    def __init__(self):
        """Inicializa profiler."""
        self.snapshots: List[Dict[str, Any]] = []
        self.start_time = None
        self.process = psutil.Process()
        
        # Inicia memory tracking
        tracemalloc.start()
        self.baseline_memory = tracemalloc.take_snapshot()
    
    def start(self):
        """Inicia profiling."""
        self.start_time = time.time()
        print("🔍 Performance Profiler Started")
        print(f"   Time: {datetime.now()}")
        print()
    
    def snapshot(self, label: str = "") -> Dict[str, Any]:
        """Captura snapshot de performance.
        
        Args:
            label: Label descritivo do snapshot
        
        Returns:
            Dict com métricas
        """
        if not self.start_time:
            self.start()
        
        elapsed = time.time() - self.start_time
        
        # CPU e memória do processo
        cpu_percent = self.process.cpu_percent(interval=0.1)
        mem_info = self.process.memory_info()
        mem_mb = mem_info.rss / 1024 / 1024
        
        # Memória do sistema
        sys_mem = psutil.virtual_memory()
        
        # Memory tracking
        current_memory = tracemalloc.take_snapshot()
        top_stats = current_memory.compare_to(self.baseline_memory, 'lineno')
        
        # Top 10 memory allocations
        top_allocations = []
        for stat in top_stats[:10]:
            top_allocations.append({
                "file": stat.traceback.format()[0] if stat.traceback else "unknown",
                "size_kb": stat.size_diff / 1024,
                "count": stat.count_diff,
            })
        
        snapshot = {
            "label": label,
            "timestamp": datetime.now().isoformat(),
            "elapsed_s": round(elapsed, 2),
            
            # Process metrics
            "process_cpu_percent": round(cpu_percent, 2),
            "process_memory_mb": round(mem_mb, 2),
            "process_threads": self.process.num_threads(),
            
            # System metrics
            "system_cpu_percent": psutil.cpu_percent(interval=0.1),
            "system_memory_percent": sys_mem.percent,
            "system_memory_available_mb": round(sys_mem.available / 1024 / 1024, 2),
            
            # Memory allocations
            "top_allocations": top_allocations,
        }
        
        self.snapshots.append(snapshot)
        
        return snapshot
    
    def print_snapshot(self, snapshot: Dict[str, Any]):
        """Imprime snapshot formatado."""
        print(f"📊 Snapshot: {snapshot['label'] or 'Unnamed'}")
        print(f"   Time: {snapshot['timestamp']}")
        print(f"   Elapsed: {snapshot['elapsed_s']}s")
        print()
        print(f"   Process:")
        print(f"     CPU: {snapshot['process_cpu_percent']}%")
        print(f"     Memory: {snapshot['process_memory_mb']:.2f} MB")
        print(f"     Threads: {snapshot['process_threads']}")
        print()
        print(f"   System:")
        print(f"     CPU: {snapshot['system_cpu_percent']}%")
        print(f"     Memory: {snapshot['system_memory_percent']}%")
        print(f"     Available: {snapshot['system_memory_available_mb']:.2f} MB")
        print()
        
        if snapshot['top_allocations']:
            print(f"   Top Memory Allocations:")
            for i, alloc in enumerate(snapshot['top_allocations'][:5], 1):
                print(f"     {i}. {alloc['file']}")
                print(f"        Size: {alloc['size_kb']:.2f} KB ({alloc['count']} objects)")
        
        print()
    
    def compare_snapshots(self, label1: str, label2: str):
        """Compara dois snapshots."""
        snap1 = next((s for s in self.snapshots if s['label'] == label1), None)
        snap2 = next((s for s in self.snapshots if s['label'] == label2), None)
        
        if not snap1 or not snap2:
            print("❌ Snapshot(s) não encontrado(s)")
            return
        
        print(f"📊 Comparação: {label1} → {label2}")
        print()
        
        # Memory diff
        mem_diff = snap2['process_memory_mb'] - snap1['process_memory_mb']
        mem_pct = (mem_diff / snap1['process_memory_mb'] * 100) if snap1['process_memory_mb'] > 0 else 0
        
        print(f"   Memory: {snap1['process_memory_mb']:.2f} MB → {snap2['process_memory_mb']:.2f} MB")
        print(f"           Diff: {mem_diff:+.2f} MB ({mem_pct:+.1f}%)")
        
        # CPU diff
        cpu_diff = snap2['process_cpu_percent'] - snap1['process_cpu_percent']
        print(f"   CPU:    {snap1['process_cpu_percent']:.1f}% → {snap2['process_cpu_percent']:.1f}%")
        print(f"           Diff: {cpu_diff:+.1f}%")
        
        # Time diff
        time_diff = snap2['elapsed_s'] - snap1['elapsed_s']
        print(f"   Time:   +{time_diff:.2f}s")
        
        print()
    
    def generate_report(self, output_file: str = "profile_report.json"):
        """Gera relatório completo."""
        report = {
            "generated_at": datetime.now().isoformat(),
            "total_duration_s": self.snapshots[-1]['elapsed_s'] if self.snapshots else 0,
            "total_snapshots": len(self.snapshots),
            "snapshots": self.snapshots,
            
            # Summary
            "summary": {
                "peak_memory_mb": max(s['process_memory_mb'] for s in self.snapshots) if self.snapshots else 0,
                "avg_cpu_percent": sum(s['process_cpu_percent'] for s in self.snapshots) / len(self.snapshots) if self.snapshots else 0,
                "peak_threads": max(s['process_threads'] for s in self.snapshots) if self.snapshots else 0,
            }
        }
        
        with open(output_file, "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"✅ Report saved: {output_file}")
        print()
        print("📊 Summary:")
        print(f"   Duration: {report['total_duration_s']:.2f}s")
        print(f"   Snapshots: {report['total_snapshots']}")
        print(f"   Peak Memory: {report['summary']['peak_memory_mb']:.2f} MB")
        print(f"   Avg CPU: {report['summary']['avg_cpu_percent']:.1f}%")
        print(f"   Peak Threads: {report['summary']['peak_threads']}")
    
    def stop(self):
        """Para profiling."""
        tracemalloc.stop()
        print("✅ Profiler stopped")


# ========== Example Usage ==========

def example_profiling():
    """Exemplo de uso do profiler."""
    
    profiler = PerformanceProfiler()
    profiler.start()
    
    # Snapshot inicial
    snap = profiler.snapshot("baseline")
    profiler.print_snapshot(snap)
    
    # Simula trabalho
    print("⏳ Simulando trabalho...")
    time.sleep(2)
    
    # Snapshot após trabalho
    snap = profiler.snapshot("after_work")
    profiler.print_snapshot(snap)
    
    # Compara
    profiler.compare_snapshots("baseline", "after_work")
    
    # Gera relatório
    profiler.generate_report()
    
    profiler.stop()


if __name__ == "__main__":
    example_profiling()
