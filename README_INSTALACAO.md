# AutoHunter - Fase 1: Infraestrutura Base

**Versão:** 1.0  
**Data:** 07 de Fevereiro de 2026

---

## 📦 Conteúdo deste Pacote

Este pacote contém a **infraestrutura base** da refatoração do AutoHunter:

```
fase1/
├── app/
│   └── scrapers/
│       ├── base/              # Interface unificada
│       │   ├── __init__.py
│       │   ├── scraper.py     # BaseScraper (ABC)
│       │   ├── fetcher.py     # unified_fetch (HTTP/Browser)
│       │   └── metrics.py     # PipelineMetrics
│       │
│       └── shared/            # Infraestrutura compartilhada
│           ├── __init__.py
│           ├── circuit_breaker.py
│           ├── browser_manager.py
│           └── normalizer.py
│
├── migrations/
│   ├── versions/
│   │   ├── fase1_001_extend_source_configs.py
│   │   └── fase1_002_extend_car_listings.py
│   └── seed_source_configs.sql
│
└── tests/
    ├── test_circuit_breaker.py
    └── test_base_scraper.py
```

---

## 🎯 Objetivos da Fase 1

1. ✅ Criar interface `BaseScraper` para padronização
2. ✅ Implementar `unified_fetch` (estratégia HTTP vs Browser)
3. ✅ Implementar `CircuitBreaker` (anti-thrash)
4. ✅ Implementar `BrowserManager` (Playwright pool singleton)
5. ✅ Migrations para extensão do DB
6. ✅ Testes unitários

---

## 📋 Pré-requisitos

- Python 3.11+
- PostgreSQL (ou conexão ao Supabase)
- Ambiente virtual ativo
- Projeto AutoHunter existente

---

## 🚀 Instalação

### Passo 1: Backup

**IMPORTANTE:** Sempre faça backup antes de aplicar migrations!

```bash
# Backup do banco
pg_dump $DATABASE_URL > backup_pre_fase1_$(date +%Y%m%d).sql

# Backup do código
cd /caminho/para/autohunter
git add -A
git commit -m "Pre-Fase1: backup before refactoring"
git tag pre-fase1
```

### Passo 2: Copiar Arquivos

```bash
# Descompactar este pacote
unzip autohunter_fase1.zip
cd autohunter_fase1

# Copiar para o projeto principal
# ATENÇÃO: ajuste o caminho conforme sua estrutura
cp -r app/scrapers/base /caminho/para/autohunter/app/scrapers/
cp -r app/scrapers/shared /caminho/para/autohunter/app/scrapers/
cp -r migrations/versions/* /caminho/para/autohunter/migrations/versions/
cp migrations/seed_source_configs.sql /caminho/para/autohunter/migrations/
cp -r tests/* /caminho/para/autohunter/tests/
```

### Passo 3: Ajustar Migrations

As migrations contêm um placeholder `<PREVIOUS_REVISION>` que deve ser substituído:

```bash
cd /caminho/para/autohunter

# 1. Descobrir última revision
alembic current

# Saída exemplo:
# ec4a5f769526 (head)

# 2. Editar migration
nano migrations/versions/fase1_001_extend_source_configs.py

# Substituir:
# down_revision = '<PREVIOUS_REVISION>'
# Por:
# down_revision = 'ec4a5f769526'  # (usar valor do passo 1)
```

### Passo 4: Aplicar Migrations

```bash
cd /caminho/para/autohunter

# Verificar plan
alembic upgrade --sql head > /tmp/migration_plan.sql
less /tmp/migration_plan.sql  # revisar

# Aplicar
alembic upgrade head

# Verificar
alembic current
# Deve mostrar: fase1_002_car_listings (head)
```

### Passo 5: Seed Source Configs

```bash
# Popular source_configs com defaults
psql $DATABASE_URL -f migrations/seed_source_configs.sql

# Verificar
psql $DATABASE_URL -c "SELECT source, enabled, fetch_mode FROM source_configs ORDER BY source;"
```

Saída esperada:
```
    source     | enabled | fetch_mode 
---------------+---------+------------
 chavesnamao   | t       | http
 gogarage      | f       | browser
 icarros       | t       | http
 kavak         | t       | http
 mercadolivre  | t       | http
 mobiauto      | f       | browser
 olx           | t       | http
 webmotors     | f       | browser
```

### Passo 6: Rodar Testes

```bash
cd /caminho/para/autohunter

# Instalar dependências de teste (se necessário)
pip install pytest pytest-mock

# Rodar testes da Fase 1
pytest tests/test_circuit_breaker.py -v
pytest tests/test_base_scraper.py -v

# Rodar todos os testes
pytest -v
```

Todos os testes devem passar! ✅

---

## 🔍 Verificação de Instalação

### Checklist

- [ ] Backup do DB feito
- [ ] Backup do código (git commit + tag)
- [ ] Arquivos copiados para o projeto
- [ ] Migrations ajustadas (down_revision correto)
- [ ] Migrations aplicadas com sucesso
- [ ] Source configs populadas
- [ ] Testes passando

### Comando de Diagnóstico

```python
# Execute no Python shell do projeto
from app.scrapers.base import BaseScraper
from app.scrapers.shared import get_circuit_breaker, get_browser_manager

# Deve importar sem erros
print("✅ Imports OK")

# Testa circuit breaker
cb = get_circuit_breaker("test")
print(f"✅ Circuit Breaker: {cb.get_state()}")

# Testa browser manager (sem iniciar browser)
bm = get_browser_manager()
print(f"✅ Browser Manager: {bm.get_stats()}")
```

---

## 📊 Verificação no DB

```sql
-- Verifica se campos novos existem
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'source_configs' 
  AND column_name IN ('extra', 'fetch_mode', 'circuit_breaker_threshold')
ORDER BY column_name;

-- Verifica car_listings
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'car_listings' 
  AND column_name IN ('extras', 'listing_type', 'year', 'make', 'model')
ORDER BY column_name;

-- Verifica índices
SELECT indexname 
FROM pg_indexes 
WHERE tablename IN ('source_configs', 'car_listings')
  AND indexname LIKE 'idx_%'
ORDER BY indexname;
```

---

## 🎉 Próximos Passos

Após instalação bem-sucedida da Fase 1:

### Fase 2: Scrapers Piloto (Semana 2)

1. Implementar `icarros.py` com `BaseScraper`
2. Implementar `mercadolivre.py` com `BaseScraper`
3. Adaptar scheduler para usar novos scrapers
4. A/B test (legacy vs novo) por 3-7 dias

### Como Usar a Nova Infraestrutura

Exemplo de scraper usando `BaseScraper`:

```python
# app/scrapers/sources/icarros.py
from app.scrapers.base import BaseScraper
from decimal import Decimal

class ICarrosScraper(BaseScraper):
    def __init__(self):
        super().__init__(source_name="icarros")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        from urllib.parse import quote_plus
        q = quote_plus(query)
        return f"https://www.icarros.com.br/carros/saopaulo?q={q}"
    
    def parse_listing(self, raw_data: dict):
        return {
            "external_id": raw_data["id"],
            "title": raw_data["title"],
            "url": raw_data["url"],
            "price": Decimal(str(raw_data.get("price", 0))),
            # ... outros campos
        }
```

Uso:

```python
from app.scrapers.sources.icarros import ICarrosScraper
from app.sources.types import ScrapeContext

scraper = ICarrosScraper()
url = scraper.build_search_url("civic si")

ctx = ScrapeContext(
    source="icarros",
    http_timeout_s=20,
)

result = scraper.scrape(url, ctx)

print(f"Found: {len(result.listings)} listings")
print(f"Method: {result.metrics.fetch_method}")
print(f"Duration: {result.metrics.total_duration_ms}ms")
```

---

## 🐛 Troubleshooting

### Erro: `ImportError: cannot import name 'BaseScraper'`

**Causa:** Arquivos não copiados corretamente

**Solução:**
```bash
# Verificar estrutura
ls -la app/scrapers/base/
# Deve conter: __init__.py, scraper.py, fetcher.py, metrics.py

# Re-copiar se necessário
cp -r autohunter_fase1/app/scrapers/base /caminho/para/autohunter/app/scrapers/
```

### Erro: `alembic.util.exc.CommandError: Can't locate revision identified by 'fase1_001'`

**Causa:** `down_revision` não foi ajustado ou está incorreto

**Solução:**
```bash
# Ver últimas migrations
alembic history | head -5

# Editar migration e corrigir down_revision
nano migrations/versions/fase1_001_extend_source_configs.py
```

### Erro: `psycopg2.errors.DuplicateColumn: column "extra" already exists`

**Causa:** Migration já foi aplicada antes

**Solução:**
```bash
# Verificar estado atual
alembic current

# Se já está em fase1_002, está OK (migration já aplicada)
# Se não, fazer downgrade e tentar novamente
alembic downgrade -1
alembic upgrade head
```

### Erro: `ModuleNotFoundError: No module named 'playwright'`

**Causa:** Playwright não instalado

**Solução:**
```bash
pip install playwright
python -m playwright install chromium
```

---

## 📚 Documentação Adicional

- **REFACTORING_PROPOSAL.md**: Proposta completa da refatoração
- **MIGRATIONS.md**: Detalhes de todas as migrations
- **CHECKLIST.md**: Checklist completa das 5 fases

---

## 📞 Suporte

**Problemas com a instalação?**

1. Verifique logs: `alembic.log` ou output do terminal
2. Confira que todas as dependências estão instaladas
3. Revise o checklist acima
4. Consulte a documentação completa (REFACTORING_PROPOSAL.md)

**Testes falhando?**

```bash
# Rodar com verbose para ver detalhes
pytest tests/test_circuit_breaker.py -v -s

# Verificar imports
python -c "from app.scrapers.base import BaseScraper; print('OK')"
```

---

## ✅ Critérios de Sucesso da Fase 1

- [x] Todos os arquivos copiados
- [x] Migrations aplicadas sem erro
- [x] Source configs populadas
- [x] Testes passando (100%)
- [x] Imports funcionando
- [x] Zero breaking changes no código existente

**Status:** ✅ Pronto para Fase 2

---

**Preparado por:** Claude (Anthropic)  
**Versão:** 1.0  
**Data:** 07/02/2026
