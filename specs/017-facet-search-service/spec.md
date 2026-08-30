# PR3 — Serviço de busca facetada (read-only, sem tocar bot ainda)

`[spec-kit: T2 — 7pts: arquivos=1 (arquivo novo isolado + 1 teste novo), decisões=1 (buckets/predicado já resolvidos abaixo, tradução de filtro é mecânica), risco=1 (read-only, sem consumidor ainda, não é [sensível] — não toca schema/dado/produção), novidade=2 (query agregada nova, mistura UNION ALL + CASE bucket), verif=1 (testável com dados de fixture SQLite)]`

Ref: `docs/DESIGN_BUSCAR_AGORA.md` seção 3 (mapeamento 1:1), seção 4 (shape da query de facetas), seção 6 PR3. Depende de PR1 (specs/015) estar mesclado — usa a coluna `status`. **Não depende de PR2** (índices são otimização, não pré-requisito funcional).

## Objetivo
Serviço novo, **somente leitura**, que calcula contagens por faceta (state, city, color, body_type, doors, make, model, year, price, mileage_km) para um termo de busca livre, em **uma única query SQL** (uma única ida ao Supabase), reaproveitando `parse_wishlist_query_with_implicit_filters` (`app/services/wishlists_service.py:795`) para extrair filtros implícitos do texto (ex. "Civic 2019 até 80000" → filtros `make=Civic`? não — ver "Decisões tomadas" sobre o que written vira filtro vs termo livre).

## Não-objetivos
- Não integra com o bot ainda (PR5).
- Não busca/retorna os anúncios (top-10) — só contagens por faceta. PR5 reaproveita o predicado-base exposto aqui (`build_search_conditions`) para a query de listagem real.
- Não substitui `manual_search()` (PR6).
- Não implementa a UI de drill-down (escolher uma faceta e refinar) — isso é orquestração do bot, PR5.

## Decisões tomadas
- **Arquivo**: `app/services/facet_search_service.py`.
- **Predicado base (`status`)**: `CarListing.status != 'inativo'` — inclui `'ativo'` e `'suspeito'` (mesmo critério do design doc seção 4: um anúncio "suspeito" ainda aparece nos resultados, só os confirmadamente encerrados somem).
- **Tradução de filtros extraídos do termo → SQL**: `parse_wishlist_query_with_implicit_filters` retorna `ParsedWishlistDraft(cleaned_query, filters: list[NormalizedWishlistFilter])`, onde cada filtro já vem normalizado com `field` (nome de coluna canônico), `operator` (`eq|gte|lte|gt|lt`) e `value: str`. Tradução mecânica, por campo:
  - `price`, `year`, `mileage_km`, `doors` (numéricos): `int(value)` (ou `Decimal(value)` para `price`, que é `Numeric` no model) + operador SQLAlchemy correspondente (`==`, `>=`, `<=`, `>`, `<`) na coluna `CarListing.<field>`.
  - `make`, `model` (texto livre, seção 3 do design doc confirma que não são estruturados): SEMPRE `ilike(f"%{value}%")`, independente do operador reportado (esses campos só chegam com operator="eq" na prática, mas o texto é livre — busca por substring, não igualdade exata).
  - `state`, `city`, `color`, `body_type` (categóricos): `func.lower(CarListing.<field>) == value.lower()` — comparação case-insensitive, sem normalização adicional (a normalização de grafia, ex. "SP" vs "São Paulo", é achado documentado na seção 2 do design doc e fica fora de escopo desta PR).
  - Qualquer `field` retornado por `NormalizedWishlistFilter` que não exista em `CarListing.__table__.columns` → ignorar silenciosamente o filtro (não quebrar a busca; log em nível `warning`).
- **Termo livre residual (`cleaned_query`)**: se não-vazio após a extração de filtros, vira condição adicional `OR`-combinada: `CarListing.title.ilike(f"%{cleaned_query}%") | CarListing.make.ilike(f"%{cleaned_query}%") | CarListing.model.ilike(f"%{cleaned_query}%")`.
- **Buckets fixos (`CASE WHEN`, sem tabela de buckets à parte)**:
  - `year`: `< 2010` | `2010-2014` | `2015-2019` | `2020-2024` | `2025+`.
  - `price`: `< 20.000` | `20.000-39.999` | `40.000-59.999` | `60.000-79.999` | `80.000-99.999` | `100.000-149.999` | `150.000+`.
  - `mileage_km` (**PREM-C**, ver premissas): `< 20.000 km` | `20.000-49.999 km` | `50.000-99.999 km` | `100.000-149.999 km` | `150.000+ km`.
- **Facetas categóricas** (`state`, `city`, `color`, `body_type`, `doors`, `make`, `model`): `GROUP BY` direto na coluna, `ORDER BY COUNT(*) DESC LIMIT 20` (evita resultado gigante em campo de alta cardinalidade como `model`). `doors` (Integer) é castado para texto (`CAST(doors AS TEXT)` via `cast(CarListing.doors, Text)`) para caber na mesma coluna `bucket` (TEXT) do resultado combinado.
- **Uma única query = `UNION ALL`** de 10 sub-`SELECT`s (uma por faceta), todas com o mesmo predicado-base, mais uma 11ª sub-`SELECT` `'__total__'` sem `GROUP BY` (`COUNT(*)` geral, `bucket = NULL`) — usada por PR5 para decidir "0 resultados → oferecer criar wishlist". `GROUPING SETS` foi avaliado e descartado (ver "Não-objetivos" da seção 4 do design doc: mistura de expressões `CASE` e colunas categóricas na mesma `GROUPING SETS` exigiria uma única lista de `GROUP BY` com `COALESCE` por coluna, mais difícil de manter em SQLAlchemy Core do que 11 `SELECT`s simples unidos — o design doc já autoriza essa alternativa). Continua sendo **uma única ida ao banco** (uma única query SQL, uma única chamada `db.execute`).
- **Cada sub-SELECT filtra `<coluna> IS NOT NULL`** antes de agrupar (não conta nulos como uma "faceta").
- **Retorno**: `list[FacetCount]`, dataclass `FacetCount(facet: str, bucket: str | None, count: int)`.
- **Sem paginação/cache** nesta PR — cada chamada roda a query completa. Otimização de cache fica para avaliação futura se o volume de uso justificar (não é decisão desta PR).

## Arquivos e mudanças
1. **Novo** `app/services/facet_search_service.py`:
   - `FACET_FIELDS = ["state", "city", "color", "body_type", "doors", "make", "model"]` (categóricas).
   - `_year_bucket_expr()`, `_price_bucket_expr()`, `_mileage_bucket_expr()` — cada uma retorna um `sqlalchemy.case(...)` conforme "Decisões tomadas".
   - `build_search_conditions(term: str) -> tuple[list, str]` — chama `parse_wishlist_query_with_implicit_filters`, traduz cada `NormalizedWishlistFilter` conforme a tabela acima, monta a condição do `cleaned_query`; retorna `(lista_de_condicoes_sqlalchemy, cleaned_query)`. Pública — PR5/PR6 reaproveitam para a query de listagem real.
   - `compute_facet_counts(db: Session, term: str) -> list[FacetCount]` — monta o predicado-base (`status != 'inativo'` + `build_search_conditions(term)`), monta os 11 `SELECT`s, executa via `db.execute(union_all(...))`, retorna a lista de `FacetCount`.
2. **Novo** `tests/test_facet_search_service.py` — casos do "Plano de teste" abaixo.

## Critérios de aceitação (EARS)
- **REQ-001**: `compute_facet_counts` DEVE retornar exatamente uma linha `facet='__total__'` com a contagem total de listings que satisfazem o predicado (termo + filtros extraídos + `status != 'inativo'`).
- **REQ-002**: QUANDO o termo contém um filtro numérico extraível (ex. "até 80000" → `price lte 80000`), O sistema DEVE aplicar esse filtro como condição SQL (não como substring no termo livre) — contagens refletem o filtro.
- **REQ-003**: QUANDO um listing tem `status = 'inativo'`, O sistema NÃO DEVE contá-lo em nenhuma faceta nem no total.
- **REQ-004**: Facetas categóricas DEVEM retornar no máximo 20 buckets cada, ordenados por contagem decrescente.
- **REQ-005**: Facetas numéricas (`year`, `price`, `mileage_km`) DEVEM agrupar por faixa fixa conforme "Decisões tomadas", não por valor exato.
- **REQ-006**: A função DEVE executar exatamente 1 `db.execute()` (uma única ida ao banco) para calcular todas as facetas + total.

## Condições de escalação
- Se `parse_wishlist_query_with_implicit_filters` não existir mais em `wishlists_service.py` ou tiver assinatura diferente da descrita — ler o arquivo atual e reportar divergência (não é decisão residual, é fato a confirmar; se a interface mudou de forma incompatível, escalar).
- Se `CarListing.__table__.columns` não tiver algum dos campos categóricos listados (`state`, `city`, `color`, `body_type`, `doors`, `make`, `model`) — escalar (a spec assume que esses campos existem conforme seção 2 do design doc).

## Plano de teste
`tests/test_facet_search_service.py`, usando a fixture `db` (SQLite) já existente em `tests/conftest.py`:
- Inserir 3-5 `CarListing` via `car_listings_repo.insert_ignore_duplicates_return_ids` (ou ORM direto) com combinações variadas de `state`/`year`/`price`/`status`.
- `compute_facet_counts(db, "")` (termo vazio) → total bate com `count(*)` manual (excluindo `status='inativo'`).
- Um listing com `status='inativo'` → não aparece em nenhuma faceta nem no total.
- Termo `"até 80000"` → filtro `price <= 80000` aplicado (total menor ou igual ao total sem filtro).
- Um listing com `year=2019` → aparece no bucket `2015-2019`.
- Comando: `.venv/Scripts/python.exe -m pytest tests/test_facet_search_service.py -v`.

## Desvio pós-aprovação (durante execução de PR5)

`compute_facet_counts(db, term)` ganhou um terceiro parâmetro opcional, `extra_conditions: list | None = None`, ANDado ao predicado base junto com `status != 'inativo'` e as condições de `build_search_conditions`. Motivo: PR5 (`specs/018-buscar-agora-bot-flow`) precisa re-rodar as contagens de faceta com filtros de refinamento acumulados interativamente (cliques do usuário), e a assinatura original não previa isso — achado via escalação do `spec-executor` da Etapa 1 de PR5 (gatilho 2: realidade ≠ spec). Mudança 100% retrocompatível (parâmetro opcional, `None` por padrão preserva o comportamento exato de antes); suíte de PR3 revalidada (26/26 passed) sem alteração de nenhum teste existente.

## Premissas assumidas
- **PREM-C** (resolvida, decisão mecânica análoga aos buckets de year/price já confirmados pelo usuário): buckets de `mileage_km` fixados em `< 20.000 km | 20.000-49.999 km | 50.000-99.999 km | 100.000-149.999 km | 150.000+ km`. Ajustável depois sem migração (é só `CASE WHEN` no código).
- **PREM-D** (resolvida): campo residual de termo livre (`cleaned_query`) casa contra `title OR make OR model` via `ilike` — não há precedente exato no código para "o que resta do termo livre" em uma busca facetada nova (o fluxo de wishlist não tem esse conceito, só filtros estruturados), então esta é a interpretação mais direta da seção 3 do design doc (make/model = texto livre).
