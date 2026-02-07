# 🚀 INSTALAÇÃO RÁPIDA - Fase 1

## ⚡ TL;DR

```bash
# 1. Backup
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql
git commit -am "Pre-Fase1 backup" && git tag pre-fase1

# 2. Copiar arquivos
cd autohunter_fase1
cp -r app/scrapers/base /seu/projeto/app/scrapers/
cp -r app/scrapers/shared /seu/projeto/app/scrapers/
cp migrations/versions/* /seu/projeto/migrations/versions/
cp migrations/seed_source_configs.sql /seu/projeto/migrations/
cp tests/* /seu/projeto/tests/

# 3. Ajustar migrations
cd /seu/projeto
# Editar migrations/versions/fase1_001_extend_source_configs.py
# Substituir <PREVIOUS_REVISION> pela última revision (veja com: alembic current)

# 4. Aplicar
alembic upgrade head
psql $DATABASE_URL -f migrations/seed_source_configs.sql

# 5. Testar
pytest tests/test_circuit_breaker.py tests/test_base_scraper.py -v
```

## ✅ Checklist

- [ ] Backup DB feito
- [ ] Backup código (git tag)
- [ ] Arquivos copiados
- [ ] down_revision ajustado
- [ ] Migrations aplicadas
- [ ] Seed executado
- [ ] Testes passando

## 📖 Documentação Completa

Consulte `README_INSTALACAO.md` para instruções detalhadas.

## 🐛 Problemas?

**Imports falhando:**
```bash
python -c "from app.scrapers.base import BaseScraper; print('OK')"
```

**Migrations falhando:**
```bash
alembic current  # ver onde está
alembic history | head -10  # ver últimas
```

**Testes falhando:**
```bash
pytest -v -s  # verbose com print
```

## 🎯 Próximo Passo

Após Fase 1 instalada → **Fase 2: Scrapers Piloto**
- Implementar iCarros com BaseScraper
- Implementar Mercado Livre com BaseScraper
- A/B test

---

**IMPORTANTE:** Leia `README_INSTALACAO.md` para detalhes completos!
