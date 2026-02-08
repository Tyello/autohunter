"""AutoHunter - Base Scraper Infrastructure"""

from app.scrapers.scraper_base.scraper import BaseScraper, ScraperResult
from app.scrapers.scraper_base.fetcher import FetchResult
from app.scrapers.scraper_base.metrics import PipelineMetrics

__all__ = ["BaseScraper", "ScraperResult", "FetchResult", "PipelineMetrics"]