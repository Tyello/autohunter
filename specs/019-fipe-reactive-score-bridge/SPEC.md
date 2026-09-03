# Spec: Ponte entre bootstrap reativo de FIPE e o score (write-through + diagnóstico)  [spec-kit: T2]

`[spec-kit: T2 — 5pts: arquivos=1, decisões=1, risco=1, novidade=1, verif=1]`

Origem: `docs/diagnostico_score_66_fipe_ausente.md`, seção 7 (confirmação em runtime, 2026-09-03).
Achado: o pipeline reativo (`fipe_on_demand_lookup_service.py` + `fipe_lookup_job.py`) roda e
popula `fipe_catalog_entries` com sucesso (ex.: Honda Fit/Civic nos últimos dias), mas **0/20**
notificações históricas resolveram FIPE mesmo com catálogo presente. Causa suspeita: (a) o
bootstrap reativo só escreve em `FipeCatalogEntry` (passo 2 do score), nunca em `FipePrice`
(passo 1, lookup direto — hoje só o job mensal desligado escreve lá); (b) o motivo exato pelo
qual o fallback via catálogo (passo 2) nunca resolveu, mesmo com catálogo presente, não está
confirmado — falta dado de runtime.

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 12 iterações totais
- Parada: todos os REQs verdes | orçamento estourado → humano
- Registro: specs/019-fipe-reactive-score-bridge/RUN.md (append-only)

## Objetivo
Fechar o loop entre o pipeline reativo de FIPE e o score: (1) instrumentar um log de diagnóstico
no ponto onde o passo 2 (fallback via catálogo) decide usar ou rejeitar um candidato, para
confirmar em runtime por que ele nunca resolveu até hoje; (2) quando o bootstrap reativo criar
com sucesso ao menos uma entrada de catálogo, também gravar um preço em `FipePrice` (passo 1),
para que a PRÓXIMA notificação do mesmo wishlist+make+model+year encontre FIPE via lookup direto,
sem depender do fallback.

## Requisitos
- REQ-001: QUANDO `_fallback_fipe_price_via_catalog` (notifications_queue_service.py) chama
  `resolve_listing_to_fipe_candidates` e recebe um resultado, O SISTEMA DEVE registrar via
  `system_logs_service.log` (level="info", component="fipe_score_bridge") o `status`, e — se
  houver `best_candidate` — seu `confidence_score`, `confidence_label`, o threshold
  (`settings.fipe_lookup_min_confidence`) e a decisão final (`used` ou motivo de rejeição) —
  verificado por: `pytest tests/test_notifications_queue_service.py -k diagnostic_log -q`
- REQ-002: QUANDO `_process_one_reactive_fipe_lookup` cria com sucesso ao menos 1
  `FipeCatalogEntry` (created > 0) E a primeira entrada normalizada criada tem preço válido,
  O SISTEMA DEVE gravar/atualizar uma linha em `FipePrice` com
  `vehicle_key = "{make}|{model}|{year}"` (normalizado via `_normalize_key_token`) para o mês
  de referência corrente — verificado por:
  `pytest tests/test_fipe_on_demand_lookup_service.py -k writes_fipe_price -q`
- REQ-003: QUANDO já existe uma linha `FipePrice` para o mesmo par `(vehicle_key,
  reference_month)`, O SISTEMA DEVE atualizar `fipe_price` em vez de violar a constraint
  `uq_fipe_vehicle_month` — verificado por:
  `pytest tests/test_fipe_on_demand_lookup_service.py -k upserts_fipe_price -q`
- REQ-004: QUANDO `_bootstrap_fipe_catalog_entries_for_year` é chamada, O SISTEMA DEVE retornar
  `(created: int, first_entry: dict | None)`, mantendo o comportamento de criação de
  `FipeCatalogEntry` idêntico ao atual — verificado por:
  `pytest tests/test_fipe_on_demand_lookup_service.py -k bootstrap_fipe_catalog_entries_for_year -q`

## Não-objetivos
- Não altera `resolve_listing_to_fipe_candidates` nem sua assinatura (ver PREM-01).
- Não religa o job mensal (`settings.fipe_monthly_update_enabled`) — decisão operacional fora
  de escopo (ver PREM-03).
- Não altera o algoritmo de `score_fipe_candidate` nem seus pesos.
- Não reprocessa/recalcula notificações históricas já enviadas.
- Não altera o threshold `fipe_lookup_min_confidence` (80) — só instrumenta a decisão.
- Não adiciona write-through no caminho de bootstrap "broad" (`_process_one_fipe_lookup`,
  usado por outro fluxo) — só no caminho reativo (`_process_one_reactive_fipe_lookup`).

## Premissas assumidas (gate de fechamento)
- PREM-01: o log de diagnóstico fica em `_fallback_fipe_price_via_catalog`
  (`notifications_queue_service.py:27-66`), não em `resolve_listing_to_fipe_candidates`
  (`fipe_catalog_resolver_service.py:195`, local originalmente cogitado). Motivo: essa segunda
  função também é chamada em loop por `build_fipe_resolver_coverage_report` (até 200x por
  chamada); logar ali geraria volume sem valor de diagnóstico adicional. O ponto que importa
  para o score real é o fallback efetivamente usado em `queue_notifications_for_matches`.
- PREM-02: quando o bootstrap reativo cria múltiplas entradas (vários `model_candidates` e/ou
  variantes de combustível na mesma chamada), o write-through em `FipePrice` usa apenas a
  primeira entrada criada (maior relevância, conforme a ordenação já existente de
  `_match_all_fipe_catalog_items`). É uma aproximação: o valor exato por versão/trim continua
  vindo do fallback via catálogo (passo 2), que já faz scoring correto por listing. O
  write-through é um cache "melhor que nada" para o passo 1, não substitui o passo 2.
- PREM-03: nenhuma alteração de configuração de produção (kill switches, env vars) faz parte
  desta spec — só código. Religar `fipe_monthly_update_enabled` é decisão operacional separada
  a ser tomada pelo usuário depois de observar o efeito desta spec.

## Decisões tomadas
- Log usa `component="fipe_score_bridge"` (novo, não reaproveita `"fipe_lookup"` para não
  misturar métricas dos dois pipelines).
- `vehicle_key` do write-through é gerado com `_normalize_key_token` (mesma função usada por
  `listing_vehicle_keys` em `fipe_service.py`), garantindo compatibilidade com o lookup direto
  do score.
- Upsert manual (query + update-ou-insert) em vez de `INSERT ... ON CONFLICT`, para manter o
  padrão SQLAlchemy ORM já usado no resto do arquivo (sem SQL bruto).

## Etapas

### Etapa 1: Instrumentar log de diagnóstico no fallback via catálogo (REQ-001)
- FAZ: em `_fallback_fipe_price_via_catalog` (`app/services/notifications_queue_service.py:27-66`),
  logo após `result = resolve_listing_to_fipe_candidates(...)` (linha ~38-43), adicionar chamada a
  `log(db, "info", "fipe_score_bridge", "fipe catalog fallback candidate", payload)` (import `log`
  já existe na linha 20) com `payload` contendo: `listing_id` (str(listing.id)), `status`
  (`result["status"]`), `confidence_score`/`confidence_label` do `best_candidate` (ou `None` se
  não houver), `threshold=settings.fipe_lookup_min_confidence`, `decision` (`"used"` se a função
  vai retornar um preço não-None ao final da lógica atual, ou um motivo entre
  `"rejected_insufficient_data"` / `"rejected_no_candidate"` / `"rejected_low_confidence"` /
  `"rejected_entry_not_found"`, conforme o ponto de retorno correspondente já existente no código).
  Não alterar a lógica de decisão existente, só adicionar a chamada de log antes de cada `return`.
- TOCA: `app/services/notifications_queue_service.py`, `tests/test_notifications_queue_service.py`
- VALIDA COM: `pytest tests/test_notifications_queue_service.py -k fallback_fipe -q` → verde;
  novo teste `test_fallback_fipe_price_via_catalog_logs_diagnostic` monkeypatcha `log` (ou usa
  `db` de teste real e faz query em `SystemLog`) e confere que o payload contém as chaves
  `status`, `confidence_score`, `decision`.
- ESCALA SE: a assinatura de `log()` em `system_logs_service.py:28-40` não bater com o uso
  esperado (parâmetro obrigatório extra não documentado no docstring atual).

### Etapa 2: `_bootstrap_fipe_catalog_entries_for_year` retorna a primeira entrada (REQ-004)
- FAZ: em `app/services/fipe_on_demand_lookup_service.py:149-226`, mudar o tipo de retorno de
  `int` para `tuple[int, dict | None]`. Manter a lógica de criação/contagem (`created`) idêntica;
  capturar o `normalized` da primeira iteração do loop interno (quando `created` ainda é 0, antes
  do incremento) em uma variável `first_entry`, e retornar `(created, first_entry)` no final da
  função (se `created == 0`, `first_entry` permanece `None`). Atualizar a docstring da função para
  refletir o novo retorno.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py`
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -k bootstrap_fipe_catalog_entries_for_year -q`
  → verde; teste confere que, com client mockado retornando 1 ano/combustível, o retorno é
  `(1, {...})` com `first_entry["price"]` igual ao valor mockado; e que sem matches o retorno é
  `(0, None)`.
- ESCALA SE: grep por `_bootstrap_fipe_catalog_entries_for_year(` no repo revelar outro caller
  além da linha 571 de `fipe_on_demand_lookup_service.py` (mudança de assinatura quebraria esse
  outro fluxo e exige decisão nova).

### Etapa 3: Write-through para FipePrice no caminho reativo (REQ-002, REQ-003)  [sensível]
- FAZ: em `_process_one_reactive_fipe_lookup` (`app/services/fipe_on_demand_lookup_service.py:543-586`),
  trocar `created = _bootstrap_fipe_catalog_entries_for_year(...)` por
  `created, first_entry = _bootstrap_fipe_catalog_entries_for_year(...)`. Quando
  `created > 0 and first_entry is not None`: importar `_normalize_key_token` de
  `app.services.fipe_service` e `FipePrice` de `app.models.fipe_price` (se ainda não importados);
  construir `vehicle_key = f"{_normalize_key_token(request.listing_make)}|{_normalize_key_token(request.listing_model)}|{request.target_year}"`;
  usar o mesmo `current_month = datetime.now(timezone.utc).strftime("%Y-%m")` já calculado dentro
  de `_bootstrap_fipe_catalog_entries_for_year` (replicar o cálculo aqui, já que não é retornado);
  fazer `existing = db.query(FipePrice).filter(FipePrice.vehicle_key == vehicle_key, FipePrice.reference_month == current_month).first()`;
  se existir, atualizar `existing.fipe_price = Decimal(str(first_entry["price"]))`; senão,
  `db.add(FipePrice(vehicle_key=vehicle_key, fipe_price=Decimal(str(first_entry["price"])), reference_month=current_month))`.
  Fazer isso ANTES do `db.commit()` já existente (linha 583), reaproveitando o mesmo commit — não
  adicionar `db.commit()` extra.
- TOCA: `app/services/fipe_on_demand_lookup_service.py`, `tests/test_fipe_on_demand_lookup_service.py`
- VALIDA COM: `pytest tests/test_fipe_on_demand_lookup_service.py -k reactive_fipe_lookup -q` →
  verde; 2 testes novos: (a) `test_process_one_reactive_fipe_lookup_writes_fipe_price` — roda com
  client mockado retornando 1 ano/combustível, confere via query que existe `FipePrice` com
  `vehicle_key` esperado e `fipe_price` correto; (b)
  `test_process_one_reactive_fipe_lookup_upserts_fipe_price_on_rerun` — roda a função duas vezes
  para o mesmo `wishlist_id`/make/model/year (com preços mockados diferentes), confere que não há
  exceção de unique constraint e que o valor final em `FipePrice` é o da segunda chamada.
- ESCALA SE: o campo de preço em `first_entry` (retorno de `normalize_external_fipe_row`) não se
  chamar `"price"` (nome divergente do assumido nesta spec), ou o teste (b) levantar
  `IntegrityError` (padrão de upsert manual não é suficiente, indicando corrida de constraint que
  a spec não previu).

## Critérios de aceitação globais
1. Todos os REQ-001..004 cobertos por teste com evidência arquivo:linha.
2. Suíte completa verde: `pytest -q` (sem regressão nos testes existentes de
   `fipe_on_demand_lookup_service`, `notifications_queue_service`, `fipe_catalog_resolver_service`).
3. Nenhuma chamada nova a API externa real nos testes — tudo mockado, como já é o padrão em
   `test_fipe_on_demand_lookup_service.py`.
4. Nenhuma migration nova (schema de `FipePrice` e `FipeCatalogEntry` já existe e não muda).
