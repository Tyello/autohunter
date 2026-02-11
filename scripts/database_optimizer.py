"""
Database Optimizer - Otimizações para PostgreSQL

Ferramentas para analisar e otimizar queries, criar índices eficientes,
e reduzir uso de memória no banco de dados.

Importante para Raspberry Pi com recursos limitados.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List, Dict
import logging


class DatabaseOptimizer:
    """Otimizador de banco de dados."""
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(__name__)
    
    def analyze_slow_queries(self, min_duration_ms: int = 100) -> List[Dict]:
        """Analisa queries lentas usando pg_stat_statements.
        
        PREREQUISITO: pg_stat_statements deve estar habilitado no PostgreSQL
        
        Args:
            min_duration_ms: Duração mínima em ms para considerar lenta
        
        Returns:
            Lista de queries lentas com estatísticas
        """
        query = text("""
            SELECT 
                query,
                calls,
                total_exec_time / 1000 as total_time_sec,
                mean_exec_time as avg_time_ms,
                max_exec_time as max_time_ms,
                stddev_exec_time as stddev_ms,
                rows
            FROM pg_stat_statements
            WHERE mean_exec_time > :min_duration
            ORDER BY mean_exec_time DESC
            LIMIT 20
        """)
        
        try:
            result = self.db.execute(query, {"min_duration": min_duration_ms})
            return [dict(row) for row in result]
        except Exception as e:
            self.logger.error(f"Erro ao analisar queries: {e}")
            self.logger.info("Dica: Habilite pg_stat_statements no PostgreSQL")
            return []
    
    def get_table_sizes(self) -> List[Dict]:
        """Retorna tamanho de cada tabela."""
        query = text("""
            SELECT 
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                pg_total_relation_size(schemaname||'.'||tablename) AS size_bytes
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
        """)
        
        result = self.db.execute(query)
        return [dict(row) for row in result]
    
    def get_index_usage(self) -> List[Dict]:
        """Analisa uso de índices."""
        query = text("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                idx_scan as index_scans,
                idx_tup_read as tuples_read,
                idx_tup_fetch as tuples_fetched,
                pg_size_pretty(pg_relation_size(indexrelid)) as index_size
            FROM pg_stat_user_indexes
            ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC
        """)
        
        result = self.db.execute(query)
        return [dict(row) for row in result]
    
    def find_missing_indexes(self) -> List[Dict]:
        """Identifica colunas que poderiam se beneficiar de índices."""
        query = text("""
            SELECT 
                schemaname,
                tablename,
                attname as column_name,
                n_distinct,
                correlation
            FROM pg_stats
            WHERE schemaname = 'public'
              AND n_distinct > 100  -- Alta cardinalidade
              AND correlation < 0.8  -- Baixa correlação (não sequencial)
            ORDER BY n_distinct DESC
            LIMIT 20
        """)
        
        result = self.db.execute(query)
        return [dict(row) for row in result]
    
    def vacuum_analyze_all(self):
        """Executa VACUUM ANALYZE em todas as tabelas.
        
        Importante para manter estatísticas atualizadas e performance.
        """
        tables_query = text("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        
        result = self.db.execute(tables_query)
        tables = [row[0] for row in result]
        
        for table in tables:
            try:
                self.logger.info(f"VACUUM ANALYZE {table}...")
                # VACUUM não pode rodar dentro de transaction block
                self.db.execute(text(f"VACUUM ANALYZE {table}"))
                self.db.commit()
            except Exception as e:
                self.logger.error(f"Erro ao fazer VACUUM em {table}: {e}")
    
    def get_database_size(self) -> Dict:
        """Retorna tamanho total do banco."""
        query = text("""
            SELECT 
                pg_database.datname,
                pg_size_pretty(pg_database_size(pg_database.datname)) AS size
            FROM pg_database
            WHERE datname = current_database()
        """)
        
        result = self.db.execute(query).first()
        return dict(result) if result else {}
    
    def get_connection_stats(self) -> Dict:
        """Retorna estatísticas de conexões."""
        query = text("""
            SELECT 
                count(*) as total,
                count(*) FILTER (WHERE state = 'active') as active,
                count(*) FILTER (WHERE state = 'idle') as idle,
                count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
            FROM pg_stat_activity
            WHERE datname = current_database()
        """)
        
        result = self.db.execute(query).first()
        return dict(result) if result else {}
    
    def suggest_indexes(self) -> List[str]:
        """Sugere índices baseado em uso.
        
        Returns:
            Lista de comandos CREATE INDEX sugeridos
        """
        suggestions = []
        
        # Analisa queries lentas
        slow_queries = self.analyze_slow_queries(min_duration_ms=50)
        
        # Heurística simples: procura por WHERE clauses frequentes
        # (Em produção, você usaria ferramentas mais sofisticadas como pgBadger)
        
        # Verifica índices não utilizados
        unused = self.get_index_usage()
        for idx in unused:
            if idx['index_scans'] == 0:
                suggestions.append(
                    f"-- Índice '{idx['indexname']}' nunca foi usado. Considere remover:"
                    f"\n-- DROP INDEX {idx['indexname']};"
                )
        
        # Verifica colunas sem índice
        missing = self.find_missing_indexes()
        for col in missing:
            suggestions.append(
                f"-- Coluna {col['tablename']}.{col['column_name']} pode se beneficiar de índice:"
                f"\nCREATE INDEX idx_{col['tablename']}_{col['column_name']} "
                f"ON {col['tablename']}({col['column_name']});"
            )
        
        return suggestions


def print_optimization_report(db: Session):
    """Imprime relatório completo de otimização."""
    optimizer = DatabaseOptimizer(db)
    
    print("="*60)
    print("RELATÓRIO DE OTIMIZAÇÃO DO BANCO DE DADOS")
    print("="*60)
    
    # Tamanho do banco
    print("\n📊 Tamanho do Banco:")
    db_size = optimizer.get_database_size()
    print(f"   {db_size.get('datname', 'N/A')}: {db_size.get('size', 'N/A')}")
    
    # Tamanho das tabelas
    print("\n📁 Tamanho das Tabelas (Top 10):")
    tables = optimizer.get_table_sizes()[:10]
    for table in tables:
        print(f"   {table['tablename']:30s} {table['size']:>10s}")
    
    # Conexões
    print("\n🔌 Conexões:")
    conn_stats = optimizer.get_connection_stats()
    print(f"   Total: {conn_stats.get('total', 0)}")
    print(f"   Ativas: {conn_stats.get('active', 0)}")
    print(f"   Idle: {conn_stats.get('idle', 0)}")
    
    # Queries lentas
    print("\n🐌 Queries Lentas (Top 5):")
    slow = optimizer.analyze_slow_queries(min_duration_ms=100)[:5]
    if slow:
        for q in slow:
            print(f"   Tempo médio: {q['avg_time_ms']:.2f}ms | Chamadas: {q['calls']}")
            print(f"   Query: {q['query'][:100]}...")
            print()
    else:
        print("   ✅ Nenhuma query lenta detectada (ou pg_stat_statements não habilitado)")
    
    # Índices não utilizados
    print("\n❌ Índices Não Utilizados:")
    unused = [idx for idx in optimizer.get_index_usage() if idx['index_scans'] == 0]
    if unused:
        for idx in unused[:5]:
            print(f"   {idx['indexname']:40s} {idx['index_size']:>10s}")
    else:
        print("   ✅ Todos os índices estão sendo utilizados")
    
    # Sugestões
    print("\n💡 Sugestões de Otimização:")
    suggestions = optimizer.suggest_indexes()
    if suggestions:
        for suggestion in suggestions[:5]:
            print(f"   {suggestion}")
    else:
        print("   ✅ Banco otimizado")
    
    print("\n" + "="*60)


# ========== Otimizações Específicas do AutoHunter ==========

def optimize_car_listings_queries(db: Session):
    """Cria índices otimizados para car_listings."""
    
    # Índices compostos para queries comuns
    indexes = [
        # Busca por marca/modelo
        "CREATE INDEX IF NOT EXISTS idx_car_listings_make_model ON car_listings(make, model)",
        
        # Busca por localização
        "CREATE INDEX IF NOT EXISTS idx_car_listings_location ON car_listings(city, state)",
        
        # Busca por preço
        "CREATE INDEX IF NOT EXISTS idx_car_listings_price ON car_listings(price) WHERE price IS NOT NULL",
        
        # Busca por ano
        "CREATE INDEX IF NOT EXISTS idx_car_listings_year ON car_listings(year) WHERE year IS NOT NULL",
        
        # Índice parcial: apenas listings ativos
        "CREATE INDEX IF NOT EXISTS idx_car_listings_active ON car_listings(created_at) WHERE deleted_at IS NULL",
        
        # Índice para deduplicação
        "CREATE INDEX IF NOT EXISTS idx_car_listings_source_external ON car_listings(source, external_id)",
    ]
    
    for idx_sql in indexes:
        try:
            db.execute(text(idx_sql))
            db.commit()
            print(f"✅ {idx_sql.split('idx_')[1].split(' ')[0]}")
        except Exception as e:
            print(f"⚠️ Erro: {e}")


def optimize_auction_lots_queries(db: Session):
    """Cria índices otimizados para auction_lots."""
    
    indexes = [
        # Busca por make/model
        "CREATE INDEX IF NOT EXISTS idx_auction_lots_make_model ON auction_lots(make, model)",
        
        # Busca por status
        "CREATE INDEX IF NOT EXISTS idx_auction_lots_status_city ON auction_lots(status, city)",
        
        # Busca por lance
        "CREATE INDEX IF NOT EXISTS idx_auction_lots_bid ON auction_lots(initial_bid) WHERE initial_bid IS NOT NULL",
        
        # Índice para lotes ativos
        "CREATE INDEX IF NOT EXISTS idx_auction_lots_active ON auction_lots(event_id, status) WHERE status IN ('scheduled', 'live')",
    ]
    
    for idx_sql in indexes:
        try:
            db.execute(text(idx_sql))
            db.commit()
            print(f"✅ {idx_sql.split('idx_')[1].split(' ')[0]}")
        except Exception as e:
            print(f"⚠️ Erro: {e}")


if __name__ == "__main__":
    from app.db.session import SessionLocal
    
    db = SessionLocal()
    
    try:
        print_optimization_report(db)
        
        print("\n🔧 Aplicando otimizações específicas...\n")
        optimize_car_listings_queries(db)
        optimize_auction_lots_queries(db)
        
    finally:
        db.close()
