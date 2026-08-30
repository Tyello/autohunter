# PR2 — Índices faltantes para facetas (price, mileage_km, status)

`[spec-kit: T2 sensível — 6pts: arquivos=1 (migration única), decisões=1 (quais colunas indexar, resolvido abaixo), risco=2 (DDL em tabela de produção quente no Supabase — CREATE INDEX pode travar escritas se não for CONCURRENTLY), novidade=1 (variação do padrão de índice parcial já usado 8+ vezes no projeto), verif=1 (testável via inspeção do plano da migração/EXPLAIN, não requer dado real)]`

Ref: `docs/DESIGN_BUSCAR_AGORA.md` seção 4 e seção 6, PR2. Depende de PR1 (specs/015) para a coluna `status` existir antes deste índice parcial.

## Objetivo
`car_listings` já tem `idx_car_listings_year`, `idx_car_listings_make_model`, `idx_car_listings_city_state`, `idx_car_listings_listing_type` (`migrations/versions/fase1_002_extend_car_listings.py`, `fase1_007_car_listings_contract_fields.py`). Faltam índices para os dois campos de faceta/ordenação restantes usados pelo motor de busca (`price`, `mileage_km`) e para a coluna nova `status` (toda query de facetas do PR3 vai filtrar `WHERE status = 'ativo'` como base).

## Não-objetivos
- Não recriar índices já existentes.
- Não usar `postgresql_using='gin'` (não é caso de índice de texto livre).

## Decisões tomadas
- `idx_car_listings_price`: B-tree parcial, `postgresql_where="price IS NOT NULL"` — mesmo padrão de `idx_car_listings_year`.
- `idx_car_listings_mileage_km`: B-tree parcial, `postgresql_where="mileage_km IS NOT NULL"`.
- `idx_car_listings_status_active`: B-tree parcial em `status`, `postgresql_where="status = 'ativo'"` — como toda query de facetas filtra por isso, um índice parcial cobrindo só as linhas ativas é mais barato de manter e mais seletivo do que indexar as 3 categorias.
- **CONCORRÊNCIA — padrão já existe no projeto, seguir EXATAMENTE.** `migrations/versions/f4a8c1d3e7b2_hot_query_index_coverage_audit.py` (a própria revisão-base de PR1) já resolve isso: usar `bind = op.get_bind(); is_pg = bind.dialect.name == "postgresql"`, e dentro de `with op.get_context().autocommit_block():` rodar `op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS <nome> ON car_listings (<col>) WHERE <condição>")` para cada um dos 3 índices. Para dialetos não-Postgres (SQLite, usado em testes), usar o fallback com `op.create_index(...)` normal (sem `postgresql_where`, já que SQLite não suporta `WHERE` em `CREATE INDEX` da mesma forma — replicar o padrão exato do arquivo de referência, incluindo o `else:` branch). `downgrade()` usa o mesmo padrão com `DROP INDEX CONCURRENTLY IF EXISTS` dentro do `autocommit_block()`.

## Arquivos e mudanças
1. Gerar nova revisão via `alembic revision -m "car_listings facet indexes price mileage status"` com `down_revision` apontando para a revisão de PR1 (`211de43e94c3`) — **só gerar depois que PR1 estiver mesclado/aprovado**, para a cadeia de revisões ficar correta.
2. `upgrade()`: 3x `op.create_index` conforme "Decisões tomadas".
3. `downgrade()`: 3x `op.drop_index`.

## Critérios de aceitação (EARS)
- **REQ-001**: O sistema DEVE criar `idx_car_listings_price` (parcial, `price IS NOT NULL`), `idx_car_listings_mileage_km` (parcial, `mileage_km IS NOT NULL`) e `idx_car_listings_status_active` (parcial, `status = 'ativo'`) em `car_listings`.
- **REQ-002**: A migração DEVE evitar lock exclusivo prolongado na tabela `car_listings` durante a criação dos índices em produção.
- **REQ-003**: A migração DEVE ser reversível.

## Condições de escalação
- Se o padrão em `f4a8c1d3e7b2_hot_query_index_coverage_audit.py` divergir do descrito acima (arquivo pode ter mudado) — ler o arquivo primeiro e replicar o que estiver lá, não o que está descrito nesta spec de memória. Divergência real entre spec e arquivo-fonte é motivo de ajuste mecânico, não escalação.

## Plano de teste
- `.venv/Scripts/python.exe -m alembic heads` deve mostrar só uma head após a migração (cadeia linear, sem branch).
- Testar import do arquivo de migração (sem DB): `.venv/Scripts/python.exe -c "import importlib.util as u; s=u.spec_from_file_location('m','migrations/versions/<arquivo_gerado>.py'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.upgrade, m.downgrade)"`.
- Não é possível testar a criação real do índice contra Supabase neste ambiente (sem rede) — marcar como validado apenas estruturalmente; execução real fica para o usuário rodar em ambiente com acesso.

## Premissas assumidas
- **PREM-B** (resolvida): confirmado precedente `CONCURRENTLY` em `migrations/versions/f4a8c1d3e7b2_hot_query_index_coverage_audit.py` — usar o mesmo padrão, ver "Decisões tomadas".
