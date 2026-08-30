# PR1 — Colunas de liveness em `car_listings` (status, last_seen_at)

`[spec-kit: T2 — 6pts: arquivos=1 (schema+model+repo+teste=4 arquivos), decisões=1 (defaults/backfill definidos abaixo), risco=2 (schema de produção, tabela quente), novidade=1 (variação do padrão is_sold/sold_at existente), verif=1 (testável com testes existentes de upsert)]`

Ref: `docs/DESIGN_BUSCAR_AGORA.md` seção 5 (schema de liveness) e seção 6, PR1.

## Objetivo
Adicionar as colunas `status` e `last_seen_at` em `car_listings`, e atualizar o upsert único (`insert_ignore_duplicates_return_ids`, `app/repositories/car_listings_repo.py`) para tocá-las a cada ciclo de scrape **sem round-trip extra ao Supabase** — usando o mesmo `ON CONFLICT DO UPDATE` já existente.

## Não-objetivos
- Não implementar liveness check ao vivo (PR4).
- Não criar índices novos (PR2).
- Não alterar semântica de `is_sold`/`sold_at` (mantida como está).
- Não fazer backfill de dados históricos com script separado — o `server_default` cobre linhas existentes automaticamente.

## Decisões tomadas
- **Tipo de `status`**: `Text` + `CHECK` constraint (não enum nativo) — decisão do usuário, consistente com o padrão observado no schema (colunas de texto livre controlado, ex. `listing_type`).
- Valores permitidos (em português, conforme `docs/DESIGN_BUSCAR_AGORA.md` seção 5): `'ativo'`, `'suspeito'`, `'inativo'`. Constraint: `status IN ('ativo','suspeito','inativo')`.
- `status` é `NOT NULL` com `server_default='ativo'` — Postgres 11+ não reescreve a tabela ao adicionar coluna NOT NULL com default constante, custo de migração é O(1) (apenas catalog update), seguro para tabela quente.
- `last_seen_at` é `DateTime(timezone=True)`, `NOT NULL`, `server_default=sa.func.now()` — mesmo raciocínio de custo O(1).
- **No upsert**: toda linha que participa de um upsert (inserida OU atualizada) teve, por definição, um scrape que a "viu agora" — então:
  - `last_seen_at` = `func.now()` **incondicional** (sempre, não é COALESCE) — every touch is a sighting.
  - `status` = `'ativo'` **incondicional** — reaparecer num scrape reativa o anúncio, mesmo que estivesse `'suspeito'`/`'inativo'` antes (liveness check e futuro job de expiração são os únicos escritores de `'suspeito'`/`'inativo'`; este PR não implementa esse job, só a coluna e o "keep-alive" no upsert).
- Ambos os campos entram no cálculo de `changed` (linha ~547-571 do repo) como **excluídos** — `last_seen_at` muda em toda linha tocada por definição, incluí-lo em `is_distinct_from` faria `updated_at` bater toda vez, o que é ruído. `status` também fica fora do `changed` (normalmente é sempre `'ativo'` vindo de scrape, então nunca diverge do valor incondicional que estamos setando).

## Arquivos e mudanças
1. `migrations/versions/211de43e94c3_car_listings_liveness_columns_status_.py` (já criado via `alembic revision`, head correto `f4a8c1d3e7b2`) — implementar `upgrade()`/`downgrade()`:
   - `upgrade()`: `op.add_column` para `status` (Text, NOT NULL, server_default='ativo') e `last_seen_at` (DateTime(timezone=True), NOT NULL, server_default=sa.text('now()')); `op.create_check_constraint('ck_car_listings_status_valid', 'car_listings', "status IN ('ativo','suspeito','inativo')")`.
   - `downgrade()`: drop da check constraint, depois drop das duas colunas (ordem inversa).
2. `app/models/car_listing.py` — adicionar após `sold_at` (linha 73):
   ```python
   status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
   last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
   ```
   Import `func` de `sqlalchemy` se ainda não importado no arquivo (checar `from sqlalchemy import Text, Numeric, Integer, Boolean, DateTime, UniqueConstraint` — adicionar `func`).
3. `app/repositories/car_listings_repo.py`, função `insert_ignore_duplicates_return_ids` — no `set_={...}` do `on_conflict_do_update` (~linha 575-606), adicionar:
   ```python
   "status": literal_column("'ativo'"),
   "last_seen_at": func.now(),
   ```
   (usar `func.now()` diretamente, sem passar por `changed`; não adicionar a `changed` OR-chain).
4. `tests/test_car_listings_repo_updated_at.py` (já existe e cobre `insert_ignore_duplicates_return_ids` + `changed`/`updated_at` — adicionar os casos abaixo neste arquivo) — casos novos:
   - Insert novo → `status == 'ativo'`, `last_seen_at` ~ `now()`.
   - Update de linha existente com `status='inativo'` setado manualmente antes → após novo upsert do mesmo `(source, external_id)`, `status` volta a `'ativo'` e `last_seen_at` avança.
   - Dois upserts consecutivos sem mudança de dado (mesmo payload) → `updated_at` NÃO muda (comportamento existente preservado), mas `last_seen_at` MUDA (novo comportamento, incondicional).

## Critérios de aceitação (EARS)
- **REQ-001**: O sistema DEVE adicionar as colunas `status` (Text, NOT NULL, default `'ativo'`) e `last_seen_at` (timestamptz, NOT NULL, default `now()`) a `car_listings` via migração Alembic com `down_revision = 'f4a8c1d3e7b2'`.
- **REQ-002**: QUANDO um upsert de listing ocorre (insert ou update), O sistema DEVE definir `last_seen_at = now()` incondicionalmente, independentemente de qualquer outro campo ter mudado.
- **REQ-003**: QUANDO um upsert de listing ocorre, O sistema DEVE definir `status = 'ativo'` incondicionalmente.
- **REQ-004**: O sistema DEVE rejeitar (via CHECK constraint) qualquer valor de `status` fora de `{'ativo','suspeito','inativo'}`.
- **REQ-005**: A migração DEVE ser reversível (`downgrade()` remove constraint e colunas sem erro).

## Condições de escalação
- Se `func` já estiver importado em `car_listing.py` sob outro alias, ou se o import de `sqlalchemy` no repo já tiver `literal_column`/`func` fora do padrão esperado — ajustar import, não é decisão residual (mecânico).
- Se a suíte de testes de upsert existente falhar por motivo NÃO relacionado a este PR (pré-existente) — reportar como achado, não tentar corrigir (fora de escopo).

## Plano de teste
`.venv/Scripts/python.exe -m pytest tests/test_car_listings_repo_updated_at.py -v` — todos os casos acima DEVEM passar.

## Premissas assumidas
- **PREM-A** (resolvida): teste existente é `tests/test_car_listings_repo_updated_at.py` — cobre `insert_ignore_duplicates_return_ids`. Estender esse arquivo, não criar um novo.

## Desvios registrados durante execução/resolução (pós spec-reviewer-senior, REPROVADO major → corrigido)

1. **`func.now()` → timestamp Python bindado.** `func.now()` compila para `CURRENT_TIMESTAMP` no SQLite (resolução de segundo inteiro), quebrando asserts de "o timestamp avançou" em upserts rápidos (testes com `time.sleep(0.1)`). Corrigido usando `now_ts = datetime.now(timezone.utc)` calculado uma vez no início da função e bindado tanto em `last_seen_at` quanto na branch "changed" do CASE de `updated_at`. Risco de clock skew avaliado e aceito pelo `spec-reviewer-senior` (liveness tolera imprecisão de segundos; PR4 opera em janelas de horas/dias).
2. **`db.commit()` adicionado ao caminho principal do upsert.** Sem ele, a identity map do SQLAlchemy não sincroniza com o resultado de um `db.execute()` de Core statement, causando leituras obsoletas na mesma sessão — bug latente pré-existente, nunca exercitado porque o caminho principal de `ON CONFLICT` falhava silenciosamente no SQLite de teste. Avaliado pelo `spec-reviewer-senior`: nenhum caller de `insert_ignore_duplicates_return_ids` depende de rollback conjunto com operações posteriores na mesma sessão (todos já fazem seu próprio `commit()` depois); o fallback ORM já commitava antes desta PR, então isso elimina uma inconsistência preexistente, não introduz uma nova.
3. **Fix não relacionado: `RETURNING` com branch por dialeto (`dialect_name == 'sqlite'`).** Confirmado via `git stash` que os 3 testes pré-existentes já falhavam em HEAD (antes desta PR) porque `stmt.returning(CarListing.id, inserted_expr)` referenciava `xmax` (específico de Postgres) incondicionalmente, quebrando no SQLite de teste. Sem esse fix nenhum teste desta PR (nem os pré-existentes) rodaria. Segue o mesmo padrão de branch por `dialect_name` já usado mais abaixo na função para stats; não toca o caminho Postgres de produção. **Este desvio não foi divulgado na primeira rodada de revisão — registrado aqui formalmente após o `spec-reviewer-senior` apontar a omissão.**
4. **REQ-004 sem evidência de teste (achado do `spec-reviewer-senior`, corrigido).** A CHECK constraint só existia na migração Alembic; o schema de teste é criado via `Base.metadata.create_all` (não via `alembic upgrade head`), então nenhum teste exercitava a constraint de fato. Corrigido mirrorando `CheckConstraint("status IN ('ativo','suspeito','inativo')", name="check_status_valid")` em `__table_args__` de `app/models/car_listing.py` (mesmo nome da constraint da migração, para consistência), e adicionando `test_status_check_constraint_rejects_invalid_value` em `tests/test_car_listings_repo_updated_at.py`.
5. **Import morto (`func`) removido (achado da 2ª rodada do `spec-reviewer-senior`).** A correção do item 4 trouxe `func` no import de `app/models/car_listing.py` por engano (não é usado no arquivo — `last_seen_at` usa `sql_text('CURRENT_TIMESTAMP')`, não `func.now()`). Removido; suíte revalidada (7/7 passed).

## Status final: APROVADO (2ª rodada do spec-reviewer-senior, achado único corrigido)
