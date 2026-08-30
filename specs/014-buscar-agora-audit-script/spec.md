# PR0 — Script de auditoria empírica read-only

`[spec-kit: T0 — script utilitário isolado, sem consumidores, read-only, sem decisões em aberto]`

Ref: `docs/DESIGN_BUSCAR_AGORA.md` seção 6, PR0.

## Objetivo
Script standalone, **somente leitura** (nenhum `INSERT`/`UPDATE`/`DDL`), que roda `SELECT`s de diagnóstico contra `car_listings` (usando `DATABASE_URL` do ambiente) e imprime: % de nulos por campo de faceta (year, state, city, price, mileage_km, color, make, model), valores fora de faixa plausível (year fora de [1900,2100], mileage_km negativo ou >1_500_000), distinct count de `state` não normalizado (`lower(state)` com múltiplas grafias), e — via HTTP real (não Playwright) — para 5-10 URLs amostradas por marketplace (Mercado Livre, OLX, Chaves na Mão), o status code/redirect observado hoje, para começar a documentar a assinatura de "anúncio encerrado" por fonte (Webmotors excluído, PerimeterX).

Motivo de não rodar aqui: este ambiente não resolve `db.ardfiehsxmwsrnlfrrcw.supabase.co` (sem rede até o Supabase). O script deve ser entregue pronto para o usuário rodar num ambiente com acesso (Pi ou local com VPN/rede liberada).

## Arquivo
`scripts/audit_buscar_agora_facets.py` — script standalone, não integrado a nenhum job do scheduler, não importado por nenhum outro módulo (isolado de propósito, é uma ferramenta de diagnóstico de uma vez).

## Critério de pronto
- `.venv/Scripts/python.exe scripts/audit_buscar_agora_facets.py --help` funciona sem erro de import.
- Nenhuma query do script contém `INSERT`, `UPDATE`, `DELETE` ou `DDL`.
- Script aceita `--sample-size` (default 8) e `--skip-http` (pula a parte de checagem de URLs, só roda os SELECTs).
