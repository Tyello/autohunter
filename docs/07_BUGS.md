# Bugs — Rastreamento e Pendências
> Bugs confirmados no código v2 que ainda não foram resolvidos ou precisam de validação.

---

## BUG-01 — `max_overflow` não passado ao `create_engine` (crítico para escala)

**Arquivo:** `app/db/session.py`

**Status:** corrigido no código atual.

**Nota de validação:** `app/db/session.py` já aplica `max_overflow=settings.db_max_overflow` e `connect_args={"connect_timeout": int(settings.db_connect_timeout)}` para conexões não-SQLite.

**Impacto histórico:** sem a correção, o pool poderia abrir mais conexões do que o banco suporta sob carga.

---

## BUG-02 — Index `notifications(user_id, sent_at WHERE status='sent')` não confirmado

**Arquivo:** `migrations/versions/f6a1b2c3d4e5_notifications_sent_at_index.py`

**Status:** resolvido e validado em banco real (PostgreSQL/Supabase).

**Nota de validação:** a migration `f6a1b2c3d4e5_notifications_sent_at_index.py` já cria em PostgreSQL o índice:

`ix_notifications_user_sent_today ON notifications (user_id, sent_at) WHERE status = 'sent'`

`count_sent_today` faz:

```sql
SELECT COUNT(*) FROM notifications
WHERE user_id = $1
  AND status = 'sent'
  AND sent_at >= now() - interval '24 hours'
```

Sem `WHERE status='sent'` no índice, esse filtro faz varredura parcial.

**Validação executada (banco real):**
```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'notifications'
  AND indexname LIKE '%sent%';
```

**Resultado confirmado:** `ix_notifications_user_sent_today` é índice partial com `WHERE status = 'sent'` no banco real, conforme validação do script `scripts/validate_postgres_schema.py` (OK).

---

## BUG-03 — `scripts/cache_manager.py` e `scripts/database_optimizer.py` referenciados em crontab

**Arquivo:** `config/raspberry-pi/crontab`

**Status:** corrigido nesta branch.

**Correção aplicada:** removidas referências a scripts legados e consolidada limpeza operacional em:

```bash
/home/autohunter/autohunter/venv/bin/python /home/autohunter/autohunter/scripts/cleanup_operational_data.py --apply
```

**Validação operacional contínua:**
```bash
grep -E "cache_manager|database_optimizer" config/raspberry-pi/crontab
```

---


## BUG-08 — Chamada incompatível em `match_listings_for_active_wishlists` (P0 runtime)

**Arquivo:** `app/services/matching_service.py`

**Problema confirmado:** havia chamada incorreta `match_listing_to_wishlist(w, l).ok` dentro do loop de match ativo.

- assinatura real exige `db` como primeiro parâmetro;
- retorno é `bool`, sem atributo `.ok`.

**Status:** corrigido nesta branch para `match_listing_to_wishlist(db, w, l)`.

**Cobertura de regressão:** adicionada para garantir execução sem `TypeError`/`AttributeError` e inclusão de listing compatível no resultado.

---

## BUG-04 — Validação end-to-end de migrations em PostgreSQL real

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P0 aberto

**Status:** resolvido e validado em PostgreSQL/Supabase real.

**Mudança desta PR:** novo script read-only `scripts/validate_postgres_schema.py` valida conexão PostgreSQL, estado Alembic, colunas críticas de `car_listings` e índice partial de `notifications`.

**Importante:** o script **não** executa `alembic upgrade head` automaticamente e não aplica alterações destrutivas.

**Validação executada (resultado):**
```bash
python scripts/validate_postgres_schema.py
```

**Resultado confirmado em banco real:**
- conexão PostgreSQL estabelecida e dialect confirmado;
- Alembic com head único `aa21b3c4d5e6`;
- revision atual do banco em `aa21b3c4d5e6` (alinhada ao head esperado);
- `car_listings` contém `doors`, `body_type`, `cross_source_fingerprint`;
- resumo da execução: `OK=8, WARNING=0, FAIL=0`.

---

## BUG-05 — Filtros estruturados para `km`, `seller`, `body_type`, `doors` não implementados

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P1 aberto

**Problema:** os campos `doors`, `body_type` existem no modelo `CarListing` e nas migrations, mas os handlers de filtro guiado ainda não os suportam. O usuário não consegue filtrar por carroceria ou número de portas pela UX.

**O que falta:**
- `wishlist_filters` aceita `field="body_type"` e `field="doors"` no banco
- O handler de criação de filtro não oferece essas opções no fluxo guiado
- O matching não aplica esses filtros (ou aplica? — validar em `matching_service.py`)

**Validar:**
```python
# Em matching_service.py — verificar se body_type e doors estão no map de filtros:
FILTER_FIELD_MAP = {
    "price": ...,
    "year": ...,
    "km": ...,       # ← confirmar se existe
    "body_type": ..., # ← confirmar se existe
    "doors": ...,     # ← confirmar se existe
}
```

---

## BUG-06 — Cross-source dedupe não funcional

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P1 aberto

**Problema:** o campo `cross_source_fingerprint` foi adicionado ao modelo para identificar o mesmo carro em fontes diferentes. Mas o código que calcula e usa esse fingerprint não está implementado (ou está incompleto).

**Consequência:** usuário recebe o mesmo carro anunciado em ML e OLX como dois alertas diferentes.

**O que implementar:**
```python
# Ao ingerir um listing, calcular fingerprint:
def compute_cross_source_fingerprint(listing: dict) -> str | None:
    """Fingerprint que identifica o mesmo carro em fontes diferentes.
    Usa make, model, year, price (tolerância 5%), km (tolerância 10%).
    """
    make = normalize(listing.get("make", ""))
    model = normalize(listing.get("model", ""))
    year = listing.get("year")
    price = round_to_bucket(listing.get("price"), bucket=500)
    km = round_to_bucket(listing.get("mileage_km"), bucket=5000)

    if not all([make, model, year]):
        return None

    key = f"{make}:{model}:{year}:{price}:{km}"
    return hashlib.md5(key.encode()).hexdigest()
```

**Modo diagnóstico primeiro:** calcular e persistir o fingerprint sem ainda usar para dedupe. Observar colisões por 7 dias antes de ativar a lógica de supressão.

---

## BUG-07 — `score_v2` automotivo incompleto (P2 incremental)

**Arquivo:** `docs/CLAUDE_REVIEW_FOLLOWUP.md` → P2 aberto

**Problema original:** `score_v2` existe no modelo `Notification` e é persistido, mas a lógica de score automotivo (FIPE, mercado, raridade) estava incompleta.

**Implementado na P2:**
- componente `market_price` com delta vs mediana de mercado quando `market_stats_cohorts` possui amostra mínima (fallback neutro quando não possui);
- componente `fipe_price` com lookup opcional em `fipe_prices` (sem integração externa) e fallback neutro quando ausente;
- componente `rarity` leve/conservador com fallback neutro quando não há amostra mínima;
- componente `quality` com sinais baratos (preço, km, localização, imagem, URL, make/model/year);
- breakdown auditável com componentes nomeados e alias `price` mantido por compatibilidade.

**Pendência real pós-P2:**
- cobertura/população operacional da tabela `fipe_prices` ainda depende de etapa futura de dados; enquanto isso, o score permanece estável via fallback neutro.

---

## Resumo por severidade

| Bug | Severidade | Esforço | Status |
|---|---|---|---|
| BUG-01 | Alta — escala | Trivial (1 linha) | Corrigido |
| BUG-02 | Alta — performance | Baixo | Resolvido e validado em banco real |
| BUG-03 | Média — operação | Baixo | Corrigido |
| BUG-08 | Alta — runtime | Baixo | Corrigido |
| BUG-04 | Alta — estabilidade | Médio | Resolvido e validado em PostgreSQL/Supabase real |
| BUG-05 | Média — produto | Médio (handlers + matching) | Aberto |
| BUG-06 | Baixa — produto | Alto (implementar + observar) | Aberto |
| BUG-07 | Média — produto | Alto (validar scoring) | Parcialmente resolvido (P2) |
