"""
Script de comparação A/B: Novo Scraper vs Legacy.

Compara resultados do novo scraper (BaseScraper) com o legacy
para validar que não há regressão.

Uso:
    python scripts/compare_scrapers.py icarros "civic si"
    python scripts/compare_scrapers.py mercadolivre "honda civic"
"""

import sys
import json
from decimal import Decimal
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.scrapers.sources import get_scraper
from app.scheduler.scraper_adapter import build_scrape_context


def compare_scrapers(source: str, query: str):
    """Compara novo scraper com legacy.
    
    Args:
        source: Nome da fonte (icarros, mercadolivre)
        query: Query de busca
    """
    print(f"\n{'='*60}")
    print(f"🔍 Comparação A/B: {source}")
    print(f"Query: {query}")
    print(f"{'='*60}\n")
    
    db = SessionLocal()
    
    try:
        # ========== NOVO SCRAPER ==========
        print("🆕 Executando NOVO scraper...")
        
        scraper = get_scraper(source)
        if not scraper:
            print(f"❌ Scraper '{source}' não encontrado!")
            return
        
        ctx = build_scrape_context(db, source)
        if not ctx:
            print(f"❌ Source '{source}' não configurado ou desabilitado!")
            return
        
        search_url = scraper.build_search_url(query)
        print(f"   URL: {search_url}")
        
        result_new = scraper.scrape(search_url, ctx)
        
        print(f"   ✅ Novo: {len(result_new.listings)} listings")
        print(f"   Método: {result_new.metrics.fetch_method}")
        print(f"   Tempo: {result_new.metrics.total_duration_ms}ms")
        print(f"   Blocked: {result_new.blocked}")
        print(f"   Warnings: {len(result_new.warnings)}")
        
        # ========== LEGACY SCRAPER ==========
        print("\n🔄 Executando LEGACY scraper...")
        print("   ⚠️  Legacy scraper não implementado neste script")
        print("   (use o scheduler atual para comparação)")
        
        # ========== ANÁLISE ==========
        print(f"\n{'='*60}")
        print("📊 ANÁLISE")
        print(f"{'='*60}\n")
        
        if result_new.blocked:
            print("❌ Novo scraper foi BLOQUEADO")
            print("   Verifique circuit breaker e configurações")
            return
        
        if not result_new.success:
            print("❌ Novo scraper FALHOU (0 listings)")
            print("   Warnings:")
            for w in result_new.warnings[:5]:
                print(f"     - {w}")
            return
        
        # Mostra sample de listings
        print(f"✅ Novo scraper: {len(result_new.listings)} listings encontrados\n")
        print("Sample (primeiros 3):")
        
        for i, listing in enumerate(result_new.listings[:3], 1):
            print(f"\n  {i}. {listing.get('title', 'N/A')}")
            print(f"     ID: {listing['external_id']}")
            print(f"     Preço: R$ {listing.get('price', 'N/A')}")
            print(f"     Ano: {listing.get('year', 'N/A')}")
            print(f"     KM: {listing.get('mileage_km', 'N/A')}")
            print(f"     URL: {listing['url'][:60]}...")
        
        # Métricas
        print(f"\n📈 Métricas do Pipeline:")
        metrics_dict = result_new.metrics.to_dict()
        print(f"   Fetch: {metrics_dict['fetch']['duration_ms']}ms ({metrics_dict['fetch']['method']})")
        print(f"   Extract: {metrics_dict['extract']['raw_items']} items em {metrics_dict['extract']['duration_ms']}ms")
        print(f"   Parse: {metrics_dict['parse']['parsed']} válidos, {metrics_dict['parse']['errors']} erros")
        print(f"   Validação: {metrics_dict['validate']['valid']} OK, {metrics_dict['validate']['invalid']} inválidos")
        print(f"   Total: {metrics_dict['total']['duration_ms']}ms")
        
        # Campos populados
        print(f"\n📋 Campos Populados:")
        if result_new.listings:
            sample = result_new.listings[0]
            fields_present = [k for k, v in sample.items() if v is not None]
            print(f"   {', '.join(fields_present)}")
        
        print(f"\n{'='*60}")
        print("✅ Comparação concluída!")
        print(f"{'='*60}\n")
        
    finally:
        db.close()


def main():
    if len(sys.argv) < 3:
        print("Uso: python compare_scrapers.py <source> <query>")
        print("Exemplo: python compare_scrapers.py icarros 'civic si'")
        sys.exit(1)
    
    source = sys.argv[1]
    query = " ".join(sys.argv[2:])
    
    compare_scrapers(source, query)


if __name__ == "__main__":
    main()
