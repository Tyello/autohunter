"""
AutoHunter - Base Scraper Infrastructure

Exports principais classes e funções para scrapers padronizados.
"""

from app.scrapers.base.scraper import BaseScraper, ScraperResult
from app.scrapers.base.fetcher import unified_fetch, FetchResult
from app.scrapers.base.metrics import PipelineMetrics

__all__ = [
    "BaseScraper",
    "ScraperResult",
    "unified_fetch",
    "FetchResult",
    "PipelineMetrics",
]
