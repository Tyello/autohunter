# Spec 010 — Bootstrap FIPE reativo por anúncio

`[spec-kit: T2 — 7pts: arquivos=2(schema+2 services), decisões=2, risco=2(schema+hot path), novidade=1, verif=1]`

## Contexto / bug de origem

Usuário reportou (produção): anúncios que casam com uma wishlist saem sem comparação de preço FIPE ("💰 Preço informado — sem base de mercado"), de forma **persistente**, não só na primeira notificação.

Diagnóstico (via queries SQL diretas em produção, nesta sessão):

- Wishlist `query="a4 avant"`, filtro `year gte 2018` (sem `lte`) — casou com 5 anúncios reais de Audi A4 Avant (anos 1995, 2013, 2015, 2019, 2019). `fipe_catalog_entries` está **zerada** pra `brand_name ILIKE '%audi%' AND model_name ILIKE '%a4%'` — nenhuma linha, nenhum ano.
- Causa raiz: o bootstrap on-demand (spec 008/009) só é disparado por `FipeLookupRequest` vinculado a uma **wishlist**, e a marca/modelo pra consultar a API da FIPE são extraídos do **texto livre da query da wishlist** (`_build_pseudo_listing`, `app/services/fipe_on_demand_lookup_service.py:310-360`). A query "a4 avant" nunca menciona "Audi" — a heurística de fallback ("primeiro token = marca") produz `make="a4"`, que não bate com nenhuma marca real da API FIPE (`get_brands`). `_resolve_fipe_brand_and_models` retorna `None` na primeira tentativa, e como o resultado fica cacheado por toda a `FipeLookupRequest` (`bootstrap_attempted=True`), **nenhum ano do range chega a ser tentado**.
- O matching de anúncio↔wishlist (`app/services/matching_service.py`, `text_match`) **não tem esse problema** porque não depende de saber a marca — é interseção de tokens contra o título do próprio anúncio, e o título do anúncio (extraído pelo scraper) já contém "Audi" como texto.
- `car_listings.make`/`car_listings.model` (colunas estruturadas, ex.: `make="Audi"`, `model="A4"`) já vêm corretas do normalizer (`normalize_ad_v2`), independente do texto da wishlist.
- Achado adicional: `car_listings.year` está `NULL` na maioria dos anúncios amostrados (`quality_flags: ["missing_year", ...]` no `extras`) — falha de extração do scraper pra esse campo estruturado. Existe fallback já testado em produção: `_extract_year(listing)` (`app/services/matching_service.py:107`), que tenta `listing.year` e cai pra regex no título/URL quando nulo. É usado pelo próprio matching de wishlist hoje.

Decisão do usuário (verbatim, nesta sessão): abrir bootstrap reativo por anúncio, usando `listing.make`/`listing.model` (não mais o texto da wishlist), via fila assíncrona reaproveitando o job/poller já existente (`fipe_lookup_job`, roda a cada `fipe_lookup_poll_interval_s`=60s) — não criar nenhum processo/scanner novo. Confirmado explicitamente: **não mexer** no descarte de tokens de 1 caractere em `important_vehicle_tokens` (fica como está, fora de escopo desta spec).

## Objetivo

Quando um anúncio casa com uma wishlist e a busca de preço FIPE via catálogo local falha (`_fallback_fipe_price_via_catalog` retorna `None`), enfileirar um bootstrap reativo pontual usando marca/modelo/ano **do próprio anúncio** (estruturados, confiáveis) — reaproveitando a tabela `fipe_lookup_requests` e o job/poller já existentes — em vez de depender do texto livre da wishlist.

## Não-objetivos

- Não mexe em `important_vehicle_tokens`/descarte de tokens de 1 caractere (`fipe_catalog_resolver_service.py`) — decisão explícita do usuário, fica como está.
- Não mexe em `_resolve_target_years`, `_build_pseudo_listing`, nem no fluxo de bootstrap disparado por wishlist (specs 007/008/009 continuam intactas e funcionando como hoje para o caso em que a wishlist já contém a marca no texto).
- Não cria nenhum scheduler job novo — reaproveita `fipe_lookup_job`/`process_pending_fipe_lookups` já existentes.
- Não muda `build_listing_fipe_query` (uso de `listing.year` puro, sem fallback) nem `score_fipe_candidate` — fora de escopo; só reaproveita `_extract_year` para decidir o `target_year` do bootstrap reativo.
- Não faz retry ilimitado — respeita cooldown (PREM-03).

## Premissas assumidas (PREM)

- **PREM-01** [sensível]: `fipe_lookup_requests` ganha 3 colunas novas, todas nullable: `listing_make TEXT`, `listing_model TEXT`, `target_year INTEGER`. Quando as 3 estão preenchidas (not null), o processing usa o caminho **reativo** (pula `_build_pseudo_listing`/`_resolve_target_years`). Quando estão nulas (comportamento atual — requests criados a partir de wishlist), mantém o fluxo já existente. 100% retrocompatível — nenhuma linha existente é afetada.
- **PREM-02**: Trigger fica em `app/services/notifications_queue_service.py`, logo após a chamada a `_fallback_fipe_price_via_catalog` retornar `None`. Condições pra enfileirar: `listing.make` e `listing.model` não vazios (strip), E `_extract_year(listing)` (reaproveitado de `matching_service.py`, import cross-module — mesmo padrão já usado pra `_ensure_month`) retorna um ano não-nulo.
- **PREM-03** (dedup/cooldown, evita spam de API): antes de criar a request reativa, normaliza `make`/`model` via `normalize_fipe_text` (já existe em `fipe_monthly_sync_service.py`) e verifica se já existe `FipeLookupRequest` com o mesmo `(wishlist_id, listing_make normalizado, listing_model normalizado, target_year)`:
  - status em `('pending','processing')` → não cria (já está na fila).
  - status em `('done','skipped','failed')` E `processed_at` mais recente que `fipe_lookup_reactive_cooldown_days` dias atrás (nova setting, default `7`) → não cria (evita bater na API de novo pra dado que genuinamente não existe/falhou recentemente).
  - caso contrário → cria nova request com `status="pending"`.
- **PREM-04**: Resolução de marca/modelo no caminho reativo chama `_resolve_fipe_brand_and_models(client, make=listing_make, model=listing_model)` diretamente (função já existente, spec 009) — sem `_build_pseudo_listing`, sem heurística de parsing de texto de wishlist.
- **PREM-05**: Bootstrap roda só pro `target_year` da própria request via `_bootstrap_fipe_catalog_entries_for_year` (já existente, spec 009) — não itera range de anos.
- **PREM-06**: Falha em achar marca/modelo na API real (`_resolve_fipe_brand_and_models` retorna `None`) marca a request como `status="skipped"` (mesma semântica do fluxo por wishlist hoje) — respeitando o cooldown do PREM-03 nas próximas tentativas.
- **PREM-07**: A criação da request reativa em `notifications_queue_service.py` é best-effort — qualquer exceção (incluindo erro ao criar a linha) é capturada e ignorada (nunca bloqueia o enfileiramento da notificação, mesmo padrão de `try/except Exception: return None` já usado em `_fallback_fipe_price_via_catalog`).
- **PREM-08**: `db.commit()` da request reativa acontece dentro do mesmo commit/flush já existente no loop de `queue_notifications_for_matches` (não abre transação própria) — mas a criação em si (`db.add`) deve sobreviver a rollback de notificação individual (usa o `db` da sessão externa, fora do `db.begin_nested()` da notificação, para não ser desfeita se a notificação falhar).

## Contratos

### `app/models/fipe_lookup_request.py` (alteração)

```python
listing_make: Mapped[str | None] = mapped_column(Text, nullable=True)
listing_model: Mapped[str | None] = mapped_column(Text, nullable=True)
target_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

### Migração (nova, `migrations/versions/`)

- `down_revision = "d4e6f8a0b2c4"` (head atual da linhagem fipe_lookup_requests — repo já tem múltiplos heads pré-existentes, documentado em `test_alembic_topology.py::test_alembic_has_single_head` como falha conhecida; esta migração não tenta consolidar heads, só encadeia na linhagem FIPE).
- `upgrade()`: `op.add_column("fipe_lookup_requests", sa.Column("listing_make", sa.Text(), nullable=True))` + `listing_model` + `sa.Column("target_year", sa.Integer(), nullable=True)`.
- `downgrade()`: `op.drop_column` nas 3, ordem inversa.

### `app/core/settings.py` (nova setting)

```python
fipe_lookup_reactive_cooldown_days: int = 7
```

### `app/services/fipe_on_demand_lookup_service.py`

Nova função `_process_one_reactive_fipe_lookup(db, client, request) -> str` (retorna outcome: `"bootstrapped"` | `"skipped"`):

```python
def _process_one_reactive_fipe_lookup(db: Session, client: FipeApiClient, request: FipeLookupRequest) -> str:
    """
    Caminho reativo: request.listing_make/listing_model/target_year já setados (PREM-01).
    Não usa _build_pseudo_listing nem _resolve_target_years.
    """
    resolved = _resolve_fipe_brand_and_models(client, make=request.listing_make, model=request.listing_model)
    if resolved is None:
        return "skipped"
    brand, candidates, reference_code = resolved
    model_years_cache: dict[str, list[dict]] = {}
    created = _bootstrap_fipe_catalog_entries_for_year(
        db, client, brand=brand, model_candidates=candidates,
        reference_code=reference_code, year=request.target_year,
        model_years_cache=model_years_cache,
    )
    return "bootstrapped" if created > 0 else "skipped"
```

Dentro de `process_pending_fipe_lookups` (ou onde hoje itera `FipeLookupRequest` pendentes): quando `request.listing_make is not None` (marcador do caminho reativo, PREM-01), chamar `_process_one_reactive_fipe_lookup` em vez de `_process_one_fipe_lookup`. Erros de `FipeApiError` seguem o mesmo tratamento de retry/backoff já existente (`_apply_bootstrap_api_error` ou equivalente) — reaproveitar, não duplicar lógica de retry.

### `app/services/notifications_queue_service.py`

Nova função `_enqueue_reactive_fipe_lookup(db, wishlist, listing) -> None`:

```python
def _enqueue_reactive_fipe_lookup(db: Session, wishlist, listing) -> None:
    """Best-effort: nunca lança. Enfileira FipeLookupRequest reativo se make/model/year disponíveis e sem cooldown ativo."""
    try:
        make = normalize_fipe_text(getattr(listing, "make", None) or "")
        model = normalize_fipe_text(getattr(listing, "model", None) or "")
        if not make or not model:
            return
        year = _extract_year(listing)
        if year is None:
            return
        cooldown_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.fipe_lookup_reactive_cooldown_days)
        existing = (
            db.query(FipeLookupRequest)
            .filter(FipeLookupRequest.wishlist_id == wishlist.id)
            .filter(FipeLookupRequest.listing_make == make)
            .filter(FipeLookupRequest.listing_model == model)
            .filter(FipeLookupRequest.target_year == year)
            .filter(
                or_(
                    FipeLookupRequest.status.in_(("pending", "processing")),
                    and_(
                        FipeLookupRequest.status.in_(("done", "skipped", "failed")),
                        FipeLookupRequest.processed_at.isnot(None),
                        FipeLookupRequest.processed_at > cooldown_cutoff,
                    ),
                )
            )
            .first()
        )
        if existing is not None:
            return
        db.add(FipeLookupRequest(
            id=uuid.uuid4(), wishlist_id=wishlist.id,
            listing_make=make, listing_model=model, target_year=year,
            status="pending",
        ))
    except Exception:
        pass
```

Chamada logo após `fipe = _fallback_fipe_price_via_catalog(db, listing)` retornar `None`, dentro do bloco `try` do score (import cross-module: `from app.services.matching_service import _extract_year`; `from app.models.fipe_lookup_request import FipeLookupRequest`; `from app.services.fipe_monthly_sync_service import normalize_fipe_text`).

## Plano de testes (nomes exatos a criar)

**`tests/test_fipe_on_demand_lookup_service.py`** (novos):
- `test_process_one_reactive_fipe_lookup_bootstraps_from_listing_make_model_year` — request com `listing_make="Audi"`, `listing_model="A4"`, `target_year=2019`; FakeClient com marca/modelo/ano batendo; assert `FipeCatalogEntry` criada com `model_year=2019`, retorno `"bootstrapped"`.
- `test_process_one_reactive_fipe_lookup_returns_skipped_when_brand_not_found` — FakeClient sem a marca; assert retorno `"skipped"`, nenhuma entry criada.
- `test_process_pending_fipe_lookups_routes_reactive_request_to_reactive_path` — cria uma `FipeLookupRequest` com os 3 campos setados e uma outra "clássica" (só `wishlist_id`) na mesma chamada de `process_pending_fipe_lookups`; assert que a reativa não chama `_build_pseudo_listing`/`_resolve_target_years` (monkeypatch espiando que não foram chamadas) e a clássica segue seu fluxo normal.

**`tests/test_notifications_queue_service.py`** (novos — checar se arquivo existe; se não, criar):
- `test_enqueue_reactive_fipe_lookup_creates_request_when_fallback_returns_none` — listing com `make="Audi"`, `model="A4"`, `year=None` mas título parseável por `_extract_year`; monkeypatch `_fallback_fipe_price_via_catalog` retornando `None`; assert 1 `FipeLookupRequest` criada com `listing_make="Audi"`, `listing_model="A4"`, `target_year` = ano extraído do título.
- `test_enqueue_reactive_fipe_lookup_skips_when_pending_request_already_exists` — cria manualmente uma `FipeLookupRequest` pending pro mesmo `(wishlist_id, make, model, year)`; assert que nenhuma nova é criada (dedup).
- `test_enqueue_reactive_fipe_lookup_skips_within_cooldown_after_skipped` — cria uma `FipeLookupRequest` `status="skipped"` com `processed_at` = agora (dentro do cooldown de 7 dias); assert que nenhuma nova é criada.
- `test_enqueue_reactive_fipe_lookup_retries_after_cooldown_expires` — mesma coisa mas `processed_at` = 8 dias atrás; assert que uma nova É criada.
- `test_enqueue_reactive_fipe_lookup_skips_when_make_or_model_missing` — listing com `make=None`; assert nenhuma request criada.
- `test_enqueue_reactive_fipe_lookup_skips_when_year_not_extractable` — listing com `year=None` e título sem ano parseável; assert nenhuma request criada.
- `test_enqueue_reactive_fipe_lookup_never_raises_on_db_error` — força uma exceção (ex.: monkeypatch `db.add` pra lançar); assert que a função não propaga.

**`tests/test_fipe_lookup_request_model.py` ou equivalente existente** (se houver arquivo de teste de modelo): verificar que `listing_make`/`listing_model`/`target_year` aceitam `None` (linha existente do fluxo por wishlist continua válida).

## Grafo de dependências / etapas

| Etapa | Descrição | Arquivos | Depende de | Sensível? |
|---|---|---|---|---|
| 1 | Migração + colunas no model `FipeLookupRequest` | `migrations/versions/<nova>.py`, `app/models/fipe_lookup_request.py`, `app/core/settings.py` (nova setting) | — | **Sim** — schema/migração |
| 2 | `_process_one_reactive_fipe_lookup` + roteamento em `process_pending_fipe_lookups` + testes | `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py` | Etapa 1 | Não |
| 3 | `_enqueue_reactive_fipe_lookup` + trigger em `queue_notifications_for_matches` + testes | `app/services/notifications_queue_service.py`, `tests/test_notifications_queue_service.py` | Etapa 1, 2 | Não |
| 4 | Fechamento: checagem de código órfão, regressão completa, veredito | — | Etapa 1-3 | Não (auto, mas eu mesmo verifico dado o padrão desta sessão) |

## Riscos

| Risco | Mitigação |
|---|---|
| Migração de schema em produção (coluna nova) | Todas as 3 colunas nullable, sem default obrigatório, sem backfill — `ADD COLUMN ... NULL` é operação leve/segura em Postgres, não trava tabela. |
| Reactive trigger no hot path de notificação pode gerar N requests duplicadas sob carga concorrente | PREM-03 (dedup via query antes do insert) reduz mas não elimina 100% corrida entre duas notificações simultâneas pro mesmo (make,model,year) — aceitável: pior caso é 2 requests processando o mesmo bootstrap, resultado idempotente via `upsert_fipe_catalog_entries`. |
| `_extract_year` é função privada (`_`) de outro módulo | Import cross-module de função privada já é padrão aceito neste repo (`_ensure_month` já é importado assim em `notifications_queue_service.py:19`). |
| Cooldown de 7 dias pode atrasar correção de um bootstrap que falhou por erro transitório de API (não por dado inexistente) | Aceitável para esta spec — mesmo padrão de retry/backoff já usado no fluxo por wishlist; não há requisito do usuário pra retry mais agressivo. |

## Análise de consistência (pré-execução)

- REQ implícitos cobertos: enfileirar reativo (PREM-02/03), processar reativo sem depender de texto de wishlist (PREM-04/05), não quebrar fluxo existente (PREM-01 retrocompatível), não bloquear notificação em caso de erro (PREM-07).
- Etapa 2 depende de colunas da Etapa 1 existirem no model — ordem correta.
- Etapa 3 depende de `_enqueue_reactive_fipe_lookup` conseguir criar uma request que a Etapa 2 sabe processar — mesmo contrato de campos (`listing_make`/`listing_model`/`target_year`) usado nos dois lados — consistente.
- Nenhuma etapa exige julgamento de design não resolvido nas premissas acima.
