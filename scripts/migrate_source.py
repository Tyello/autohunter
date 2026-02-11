"""
Script de Migração Gradual - Fase 3.

Migra scrapers um por um, com validação automática.

Uso:
    python scripts/migrate_source.py olx
    python scripts/migrate_source.py webmotors
    python scripts/migrate_source.py --all
"""

import sys
import time
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.scrapers.sources import get_scraper, list_scrapers
from app.scheduler.scraper_adapter import build_scrape_context


# Ordem de migração (segurança: HTTP → Hybrid → Browser)
MIGRATION_ORDER = [
    # HTTP-only (baixo risco)
    "chavesnamao",
    "kavak",
    
    # Hybrid (risco médio)
    "olx",
    
    # Browser required (risco alto)
    "webmotors",
    "gogarage",
    "mobiauto",
]


# Queries de teste por fonte
TEST_QUERIES = {
    "olx": ["civic", "corolla"],
    "webmotors": ["civic", "corolla"],
    "chavesnamao": ["civic"],
    "kavak": ["civic"],
    "gogarage": ["civic"],
    "mobiauto": ["civic"],
}


def validate_scraper(source: str, min_listings: int = 10) -> dict:
    """Valida que um scraper funciona adequadamente.
    
    Args:
        source: Nome da fonte
        min_listings: Mínimo de listings esperados
    
    Returns:
        Dict com resultado da validação
    """
    print(f"\n{'='*60}")
    print(f"🔍 Validando: {source}")
    print(f"{'='*60}\n")
    
    scraper = get_scraper(source)
    if not scraper:
        return {
            "ok": False,
            "reason": "scraper_not_found",
            "source": source,
        }
    
    db = SessionLocal()
    
    try:
        ctx = build_scrape_context(db, source)
        if not ctx:
            return {
                "ok": False,
                "reason": "source_not_configured",
                "source": source,
            }
        
        # Testa com queries padrão
        queries = TEST_QUERIES.get(source, ["civic"])
        
        results = []
        
        for query in queries:
            print(f"   Query: {query}")
            
            search_url = scraper.build_search_url(query)
            result = scraper.scrape(search_url, ctx)
            
            print(f"   ✅ {len(result.listings)} listings")
            print(f"   Método: {result.metrics.fetch_method}")
            print(f"   Tempo: {result.metrics.total_duration_ms}ms")
            
            if result.blocked:
                print(f"   ⚠️  BLOQUEADO!")
            
            results.append({
                "query": query,
                "listings": len(result.listings),
                "blocked": result.blocked,
                "duration_ms": result.metrics.total_duration_ms,
            })
            
            # Delay entre queries
            time.sleep(2)
        
        # Análise
        total_listings = sum(r["listings"] for r in results)
        blocked_count = sum(1 for r in results if r["blocked"])
        avg_duration = sum(r["duration_ms"] for r in results) / len(results)
        
        print(f"\n📊 Resumo:")
        print(f"   Total: {total_listings} listings")
        print(f"   Bloqueios: {blocked_count}/{len(results)}")
        print(f"   Latência média: {avg_duration:.0f}ms")
        
        # Critérios de aprovação
        passed = True
        issues = []
        
        if total_listings < min_listings:
            passed = False
            issues.append(f"Poucos listings ({total_listings} < {min_listings})")
        
        if blocked_count > len(results) * 0.5:
            passed = False
            issues.append(f"Taxa de bloqueio alta ({blocked_count}/{len(results)})")
        
        if avg_duration > 10000:  # 10s
            passed = False
            issues.append(f"Latência muito alta ({avg_duration:.0f}ms)")
        
        if passed:
            print(f"\n✅ APROVADO para migração!")
        else:
            print(f"\n❌ NÃO APROVADO:")
            for issue in issues:
                print(f"     - {issue}")
        
        return {
            "ok": passed,
            "source": source,
            "total_listings": total_listings,
            "blocked_count": blocked_count,
            "avg_duration_ms": avg_duration,
            "issues": issues,
            "results": results,
        }
        
    finally:
        db.close()


def migrate_source(source: str, enable_flag: bool = True) -> bool:
    """Migra uma fonte para novo scraper.
    
    Args:
        source: Nome da fonte
        enable_flag: Se True, habilita feature flag
    
    Returns:
        True se migração bem-sucedida
    """
    print(f"\n{'='*60}")
    print(f"🚀 Migrando: {source}")
    print(f"{'='*60}\n")
    
    # Valida primeiro
    validation = validate_scraper(source)
    
    if not validation["ok"]:
        print(f"\n❌ Validação falhou! Não é seguro migrar.")
        return False
    
    # Habilita feature flag
    if enable_flag:
        print(f"\n📝 Para habilitar, adicione ao .env:")
        print(f"   USE_NEW_SCRAPER_{source.upper()}=true")
        print(f"\nOu habilite globalmente:")
        print(f"   USE_NEW_SCRAPERS=true")
    
    print(f"\n✅ Migração de '{source}' validada e pronta!")
    print(f"\nPróximos passos:")
    print(f"  1. Habilitar feature flag (acima)")
    print(f"  2. Monitorar por 24-48h")
    print(f"  3. Se estável, migrar próxima fonte")
    
    return True


def migrate_all(interactive: bool = True):
    """Migra todas as fontes em ordem de segurança.
    
    Args:
        interactive: Se True, pede confirmação entre migrações
    """
    print(f"\n{'='*60}")
    print(f"🚀 MIGRAÇÃO EM MASSA - Fase 3")
    print(f"{'='*60}\n")
    
    print(f"Ordem de migração:")
    for i, source in enumerate(MIGRATION_ORDER, 1):
        print(f"  {i}. {source}")
    
    print(f"\nTotal: {len(MIGRATION_ORDER)} fontes")
    
    if interactive:
        resp = input("\nContinuar? (s/N): ")
        if resp.lower() != "s":
            print("Cancelado.")
            return
    
    results = {}
    
    for source in MIGRATION_ORDER:
        if interactive:
            print(f"\n\nPróximo: {source}")
            resp = input("Migrar esta fonte? (s/N/q para sair): ")
            
            if resp.lower() == "q":
                print("Migração interrompida.")
                break
            
            if resp.lower() != "s":
                print(f"Pulando {source}...")
                continue
        
        success = migrate_source(source, enable_flag=True)
        results[source] = success
        
        if interactive and success:
            print("\nPressione Enter para continuar...")
            input()
    
    # Resumo final
    print(f"\n{'='*60}")
    print(f"📊 RESUMO DA MIGRAÇÃO")
    print(f"{'='*60}\n")
    
    for source, success in results.items():
        status = "✅" if success else "❌"
        print(f"  {status} {source}")
    
    successful = sum(1 for s in results.values() if s)
    print(f"\nTotal: {successful}/{len(results)} migrações bem-sucedidas")


def main():
    if len(sys.argv) < 2:
        print("Uso:")
        print("  python migrate_source.py <source>       # Migra uma fonte")
        print("  python migrate_source.py --all          # Migra todas")
        print("  python migrate_source.py --all --batch  # Migra todas (não-interativo)")
        print("\nFontes disponíveis:")
        for source in MIGRATION_ORDER:
            print(f"  - {source}")
        sys.exit(1)
    
    if sys.argv[1] == "--all":
        interactive = "--batch" not in sys.argv
        migrate_all(interactive=interactive)
    else:
        source = sys.argv[1]
        migrate_source(source)


if __name__ == "__main__":
    main()
