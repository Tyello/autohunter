"""
Cache Manager - Sistema de Cache para AutoHunter

Implementa cache em memória e Redis (opcional) para reduzir
carga no banco de dados e melhorar performance.

Especialmente importante para Raspberry Pi com recursos limitados.
"""

from typing import Any, Optional, Callable
from functools import wraps
import pickle
import hashlib
import time
from datetime import timedelta

from app.core.settings import settings


class CacheManager:
    """Gerenciador de cache flexível.
    
    Suporta:
    - In-memory cache (dicionário Python)
    - Redis cache (opcional, se disponível)
    - TTL configurável
    - Cache invalidation
    """
    
    def __init__(self, use_redis: bool = False, redis_url: Optional[str] = None):
        """Inicializa cache manager.
        
        Args:
            use_redis: Se True, tenta usar Redis
            redis_url: URL do Redis (ex: redis://localhost:6379/0)
        """
        self.use_redis = use_redis
        self._memory_cache = {}
        self._cache_timestamps = {}
        self._redis_client = None
        
        if use_redis:
            try:
                import redis
                self._redis_client = redis.from_url(redis_url or "redis://localhost:6379/0")
                self._redis_client.ping()  # Testa conexão
                print("✅ Redis cache habilitado")
            except Exception as e:
                print(f"⚠️ Redis não disponível, usando cache em memória: {e}")
                self.use_redis = False
    
    def get(self, key: str) -> Optional[Any]:
        """Busca valor do cache.
        
        Args:
            key: Chave do cache
        
        Returns:
            Valor cacheado ou None
        """
        if self.use_redis and self._redis_client:
            try:
                data = self._redis_client.get(key)
                if data:
                    return pickle.loads(data)
            except Exception:
                pass
        
        # Fallback: memória
        return self._memory_cache.get(key)
    
    def set(self, key: str, value: Any, ttl: int = 300):
        """Salva valor no cache.
        
        Args:
            key: Chave do cache
            value: Valor a cachear
            ttl: Time-to-live em segundos (padrão: 5 minutos)
        """
        if self.use_redis and self._redis_client:
            try:
                data = pickle.dumps(value)
                self._redis_client.setex(key, ttl, data)
            except Exception:
                pass
        
        # Sempre salva em memória também
        self._memory_cache[key] = value
        self._cache_timestamps[key] = time.time() + ttl
    
    def delete(self, key: str):
        """Remove item do cache."""
        if self.use_redis and self._redis_client:
            try:
                self._redis_client.delete(key)
            except Exception:
                pass
        
        self._memory_cache.pop(key, None)
        self._cache_timestamps.pop(key, None)
    
    def clear(self):
        """Limpa todo o cache."""
        if self.use_redis and self._redis_client:
            try:
                self._redis_client.flushdb()
            except Exception:
                pass
        
        self._memory_cache.clear()
        self._cache_timestamps.clear()
    
    def cleanup_expired(self):
        """Remove itens expirados do cache em memória."""
        now = time.time()
        expired = [k for k, ts in self._cache_timestamps.items() if ts < now]
        
        for key in expired:
            self._memory_cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        
        return len(expired)
    
    def stats(self) -> dict:
        """Retorna estatísticas do cache."""
        return {
            "backend": "redis" if self.use_redis else "memory",
            "memory_items": len(self._memory_cache),
            "memory_size_kb": sum(len(pickle.dumps(v)) for v in self._memory_cache.values()) / 1024,
        }


# Instância global
_cache = None


def get_cache() -> CacheManager:
    """Retorna instância global do cache."""
    global _cache
    if _cache is None:
        # Tenta Redis, fallback para memória
        use_redis = settings.use_redis_cache
        redis_url = settings.redis_url
        _cache = CacheManager(use_redis=use_redis, redis_url=redis_url)
    return _cache


def cached(ttl: int = 300, key_prefix: str = ""):
    """Decorator para cachear resultado de função.
    
    Args:
        ttl: Time-to-live em segundos
        key_prefix: Prefixo da chave do cache
    
    Exemplo:
        @cached(ttl=600, key_prefix="source_config")
        def get_source_config(db, source):
            return db.query(...).first()
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Gera chave única baseada em argumentos
            cache_key = _generate_cache_key(func.__name__, key_prefix, args, kwargs)
            
            # Tenta buscar do cache
            cache = get_cache()
            cached_value = cache.get(cache_key)
            
            if cached_value is not None:
                return cached_value
            
            # Executa função
            result = func(*args, **kwargs)
            
            # Salva no cache
            cache.set(cache_key, result, ttl=ttl)
            
            return result
        
        return wrapper
    return decorator


def _generate_cache_key(func_name: str, prefix: str, args: tuple, kwargs: dict) -> str:
    """Gera chave de cache única."""
    # Serializa argumentos
    key_parts = [prefix, func_name]
    
    # Adiciona args (skip self/cls)
    for arg in args[1:] if args else []:
        if hasattr(arg, 'id'):  # SQLAlchemy model
            key_parts.append(f"{arg.__class__.__name__}_{arg.id}")
        else:
            key_parts.append(str(arg))
    
    # Adiciona kwargs
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")
    
    # Hash para chave compacta
    key_str = ":".join(key_parts)
    return hashlib.md5(key_str.encode()).hexdigest()


# ========== Funções de Conveniência ==========

def cache_listing(listing_id: int, listing_data: dict, ttl: int = 3600):
    """Cacheia dados de um listing."""
    cache = get_cache()
    cache.set(f"listing:{listing_id}", listing_data, ttl=ttl)


def get_cached_listing(listing_id: int) -> Optional[dict]:
    """Busca listing do cache."""
    cache = get_cache()
    return cache.get(f"listing:{listing_id}")


def invalidate_listing(listing_id: int):
    """Invalida cache de um listing."""
    cache = get_cache()
    cache.delete(f"listing:{listing_id}")


def cache_search_results(query: str, filters: dict, results: list, ttl: int = 600):
    """Cacheia resultados de busca."""
    cache = get_cache()
    key = f"search:{hashlib.md5(f'{query}:{str(filters)}'.encode()).hexdigest()}"
    cache.set(key, results, ttl=ttl)


def get_cached_search(query: str, filters: dict) -> Optional[list]:
    """Busca resultados de busca do cache."""
    cache = get_cache()
    key = f"search:{hashlib.md5(f'{query}:{str(filters)}'.encode()).hexdigest()}"
    return cache.get(key)
