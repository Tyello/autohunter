# Alembic PostgreSQL Validation (staging/test)

Date: 2026-04-29 (UTC)

## Scope
Validação da topologia Alembic e execução end-to-end **em PostgreSQL real/staging** após merge revision `0be3b0c71883`.

## DATABASE_URL (mascarado)
- Estado no ambiente desta execução: **não configurado** (`unset`).
- Exemplo de formato esperado (mascarado): `postgresql://<user>:<password>@<host>:5432/<database>`.

## Comandos executados e resultados

1. `alembic heads`
   - Resultado: `0be3b0c71883 (head)`
   - Status: ✅ único head confirmado.

2. `alembic upgrade head`
   - Resultado: **falhou antes de conectar ao banco**, por ausência de `DATABASE_URL`.
   - Erro observado: `ValidationError: database_url Field required`.
   - Status: ⚠️ bloqueado por ambiente (sem staging PostgreSQL configurado).

3. `pytest -q tests/test_alembic_topology.py`
   - Resultado: passou (`... [100%]`).
   - Status: ✅.

4. `pytest -q`
   - Resultado: passou (`[100%]`).
   - Status: ✅.

## Verificação de colunas solicitadas
Colunas alvo:
- `car_listings.doors`
- `car_listings.body_type`
- `car_listings.cross_source_fingerprint`

Status nesta execução:
- ⚠️ **Não validado em PostgreSQL real**, pois `alembic upgrade head` não pôde ser executado sem `DATABASE_URL` de staging/teste.

## Downgrade -1 / Upgrade head
- `alembic downgrade -1`: **não executado**.
- Motivo: sem banco PostgreSQL limpo configurado.
- `alembic upgrade head` pós-downgrade: **não executado** pelo mesmo motivo.

## Riscos remanescentes
1. Falta de evidência empírica de que todas migrations aplicam integralmente em PostgreSQL de staging limpo neste ambiente.
2. Falta de validação direta das colunas em `car_listings` no banco PostgreSQL alvo.
3. Falta de prova de reversibilidade imediata de `downgrade -1` em banco limpo.

## Próximo passo recomendado (quando houver staging PostgreSQL disponível)
1. Exportar `DATABASE_URL` de um banco de staging/teste vazio (não produção).
2. Reexecutar:
   - `alembic heads`
   - `alembic upgrade head`
   - validação SQL das 3 colunas em `car_listings`
   - `alembic downgrade -1`
   - `alembic upgrade head`
   - `pytest -q tests/test_alembic_topology.py`
   - `pytest -q`
