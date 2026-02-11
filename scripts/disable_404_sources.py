"""
Script para desabilitar fontes que retornam 404.

Desabilita Chaves na Mão e Kavak no banco de dados.

Uso:
    python scripts/disable_404_sources.py
"""

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.source_config import SourceConfig


def disable_sources():
    """Desabilita fontes com 404."""
    
    sources_to_disable = ['chavesnamao', 'kavak']
    
    print("🔧 Desabilitando fontes com 404...\n")
    
    db = SessionLocal()
    
    try:
        for source_name in sources_to_disable:
            # Busca config
            config = db.query(SourceConfig).filter(
                SourceConfig.source == source_name
            ).first()
            
            if config:
                if config.is_enabled:
                    config.is_enabled = False
                    db.commit()
                    print(f"✅ {source_name}: DESABILITADO")
                else:
                    print(f"ℹ️  {source_name}: Já estava desabilitado")
            else:
                print(f"⚠️  {source_name}: Não encontrado no banco")
        
        print("\n" + "="*60)
        print("📊 STATUS FINAL")
        print("="*60 + "\n")
        
        # Mostra todas as fontes e status
        all_configs = db.query(SourceConfig).all()
        
        for config in all_configs:
            status = "✅ HABILITADO" if config.is_enabled else "❌ DESABILITADO"
            print(f"{config.source:20s} {status}")
        
        print("\n✅ Operação concluída!")
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        db.rollback()
    
    finally:
        db.close()


if __name__ == "__main__":
    disable_sources()
