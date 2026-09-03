# Spec: Score v2 — reduzir amostra mínima de mercado e expor completude de dados  [spec-kit: T2]

`[spec-kit: T2 — 7pts: arquivos=2, decisões=1, risco=2, novidade=1, verif=1]`

Origem: avaliação pedida pelo usuário — "avaliar se o score precisa ser melhorado em termos de
quantidade de avaliadores ou se de fato ele nao funciona e podemos removelo". Diagnóstico
confirmado em runtime (`docs/diagnostico_score_66_fipe_ausente.md`, seção 7): hoje 4 das 6
dimensões do score (`match`, `market_price`, `fipe_price`, `rarity`) tendem a cair no valor
default estrutural na maioria das notificações — `match` por design (gate de matching já garante
match, não é falta de dado); `market_price`/`rarity` porque `min_market_sample=8` raramente é
atingido; `fipe_price` pela causa raiz coberta em `specs/019-fipe-reactive-score-bridge`. Isso
torna impossível hoje distinguir "dimensão não funciona" de "dimensão nunca recebeu dado real" —
não há base para decidir remover nada ainda.

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 12 iterações totais
- Parada: todos os REQs verdes | orçamento estourado → humano
- Registro: specs/020-score-v2-data-completeness/RUN.md (append-only)

## Objetivo
Duas mudanças concretas, decididas agora, que não decidem remoção de dimensão nenhuma: (1) baixar
o piso de amostra mínima de mercado (`min_market_sample`) de 8 (hardcoded) para um valor
configurável via `settings.score_min_market_sample` (default 4), para que `market_price` e
`rarity` deixem de cair no default só por causa de um piso alto demais em cohorts pequenos; (2)
tornar visível, no próprio `ScoreResult` e na notificação enviada ao Telegram, quais dimensões
foram calculadas com dado real vs. quais caíram no default (`defaulted_dimensions`) — para que
depois de rodar por um tempo com os pontos 1 e desta spec 019 (FIPE) resolvidos, exista dado real
para decidir se alguma dimensão deve ser simplificada/removida. Esta spec **não** remove nem
redesenha nenhuma dimensão.

## Requisitos
- REQ-001: `settings.py` DEVE expor `score_min_market_sample: int = 4` — verificado por:
  `python -c "from app.core.settings import settings; assert settings.score_min_market_sample == 4"`
- REQ-002: QUANDO `queue_notifications_for_matches` (ambos os call sites, linhas 267 e 411 de
  `notifications_queue_service.py`) chama `score_ad`, O SISTEMA DEVE passar
  `min_market_sample=settings.score_min_market_sample` explicitamente (em vez de usar o default
  implícito de `score_ad`) — verificado por: `grep -n "min_market_sample=settings" app/services/notifications_queue_service.py` retorna 2 ocorrências
- REQ-003: QUANDO `score_ad` calcula `market_price_score` usando o valor de fallback (12) por
  `market_stats is None` ou `sample_size < min_market_sample`, O SISTEMA DEVE incluir
  `"market_price"` em `ScoreResult.defaulted_dimensions` — verificado por:
  `pytest tests/test_score_v2.py -k defaulted_dimensions_market_price -q`
- REQ-004: QUANDO `score_ad` calcula `fipe_score` usando o valor de fallback (5) por
  `fipe_price is None`, O SISTEMA DEVE incluir `"fipe_price"` em `defaulted_dimensions` —
  verificado por: `pytest tests/test_score_v2.py -k defaulted_dimensions_fipe -q`
- REQ-005: QUANDO `score_ad` calcula `mileage_score` usando o valor de fallback (8) por `km is
  None` ou dados de ano ausentes, O SISTEMA DEVE incluir `"mileage"` em `defaulted_dimensions` —
  verificado por: `pytest tests/test_score_v2.py -k defaulted_dimensions_mileage -q`
- REQ-006: QUANDO `score_ad` calcula `rarity_score` usando o valor de fallback (2) por amostra
  insuficiente, O SISTEMA DEVE incluir `"rarity"` em `defaulted_dimensions` — verificado por:
  `pytest tests/test_score_v2.py -k defaulted_dimensions_rarity -q`
- REQ-007: QUANDO todas as 4 dimensões acima (`market_price`, `fipe_price`, `mileage`, `rarity`)
  são calculadas a partir de dado real (nenhum fallback), O SISTEMA DEVE retornar
  `defaulted_dimensions == []` — verificado por: `pytest tests/test_score_v2.py -k defaulted_dimensions_empty_when_all_real -q`
- REQ-008: `ScoreResult.to_dict()` e a reconstrução a partir do dict persistido em
  `notification.score_breakdown` DEVEM preservar `defaulted_dimensions` (round-trip) — verificado
  por: `pytest tests/test_score_v2.py -k defaulted_dimensions_roundtrip -q`
- REQ-009: QUANDO uma notificação é formatada para o Telegram E
  `score_breakdown["defaulted_dimensions"]` tem 2 ou mais itens, O SISTEMA DEVE incluir no texto
  formatado uma linha indicando score parcial e listando as dimensões (em português, ex.:
  "⚠️ Score parcial — sem dados reais de: preço de mercado, FIPE") — verificado por:
  `pytest tests/test_telegram_formatter_vnext.py -k partial_score -q`

## Não-objetivos
- Não remove, redesenha pesos, nem substitui nenhuma das 6 dimensões existentes.
- Não decide (nem prepara decisão automática) se alguma dimensão deve ser removida — essa
  decisão só é tomada depois, com dado real observado após esta spec + a 019 estarem em produção.
- Não altera o cálculo de `match_score` — o caso `terms == []` (match=35) não é tratado como
  "dado faltando": é estrutural ao tipo de wishlist (só filtros, sem busca livre), não algo que
  mais dado resolveria (ver PREM-01).
- Não altera os caps pós-hoc (`cap_price_missing_65`, `cap_images_missing_60`,
  `cap_many_missing_50`).
- Não altera `notifications_service.py`, apenas o formatador do Telegram, entre os consumidores
  de `score_breakdown` (outros consumidores, se existirem, ficam fora de escopo).

## Premissas assumidas (gate de fechamento)
- PREM-01: `match_score` não entra em `defaulted_dimensions` porque seu valor fixo (35) quando
  `terms == []` não é uma falta de dado — é o comportamento correto para wishlists compostas só
  de filtros estruturados (sem termo de busca livre). Incluir `match` na lista geraria falso
  alarme de "score parcial" em toda wishlist desse tipo (a maioria, conforme dado de runtime da
  seção 7 do diagnóstico: todas as 8 wishlists ativas amostradas têm query não-vazia, mas isso
  pode não valer para todo usuário futuro).
- PREM-02: o valor `score_min_market_sample = 4` é uma redução deliberada pela metade do piso
  atual (8), não uma calibração estatística fina. Racional: n=4 ainda dá uma mediana utilizável
  para um cohort estreito (make+model+year), e reduzir o piso é reversível/ajustável via env var
  depois de observar o efeito real na distribuição de scores — não é uma decisão que precise de
  mais investigação para ser tomada agora.
- PREM-03: o limiar "2 ou mais dimensões defaulted" para mostrar o aviso no Telegram (REQ-009) é
  escolhido porque 1 dimensão defaulted isolada é comum e não necessariamente compromete a
  utilidade do score; 2+ já é o padrão observado nas notificações históricas (3-4 dimensões
  defaulted simultaneamente, por isso o score sempre convergia a valores fixos).

## Decisões tomadas
- `defaulted_dimensions` é uma lista de strings com os nomes já usados em `components` (subset:
  `"market_price"`, `"fipe_price"`, `"mileage"`, `"rarity"`), computada com flags booleanas
  locais setadas no momento de cada cálculo (não inferida do valor final, para evitar falso
  positivo quando um valor real coincide numericamente com o default).
- `settings.score_min_market_sample` é passado explicitamente nos 2 call sites de `score_ad` em
  vez de depender do parâmetro default da função — torna a configuração visível e testável sem
  depender de mock do default de `score_ad`.
- A linha de aviso no Telegram é adicionada como uma badge adicional, seguindo o padrão já
  existente de `_price_context_badge` (`telegram_formatter.py:214` e vizinhança) — nova função
  `_partial_score_badge(breakdown: dict) -> str | None`, chamada no ponto de montagem de badges
  (`telegram_formatter.py:452+`, junto de `_get_breakdown`).

## Etapas

### Etapa 1: Config `score_min_market_sample` e propagação nos call sites (REQ-001, REQ-002)
- FAZ: em `app/core/settings.py`, adicionar `score_min_market_sample: int = 4` próximo aos outros
  campos `fipe_lookup_*`/`score_*` existentes. Em `app/services/notifications_queue_service.py`,
  nos dois call sites de `score_ad(...)` (linhas 267 e 411), adicionar o argumento
  `min_market_sample=settings.score_min_market_sample` (import de `settings` já existe na linha
  11).
- TOCA: `app/core/settings.py`, `app/services/notifications_queue_service.py`
- VALIDA COM: `python -c "from app.core.settings import settings; assert settings.score_min_market_sample == 4"`
  → sem erro; `grep -c "min_market_sample=settings.score_min_market_sample" app/services/notifications_queue_service.py`
  → `2`
- ESCALA SE: `score_ad` já receber `min_market_sample` de outra origem (ex.: outro parâmetro
  calculado) nesses call sites, tornando a adição direta ambígua.

### Etapa 2: `defaulted_dimensions` em `ScoreResult` (REQ-003 a REQ-008)
- FAZ: em `app/scoring/types.py`, adicionar campo `defaulted_dimensions: list[str] =
  field(default_factory=list)` ao dataclass `ScoreResult`, e incluí-lo em `to_dict()`/qualquer
  método de (des)serialização existente. Em `app/scoring/score_v2.py` (`score_ad`, linhas
  100-257): introduzir 4 flags booleanas junto de cada bloco de cálculo — `market_price_defaulted`
  (True quando entra no ramo `market_stats is None or sample_size < min_market_sample`, linha
  ~139), `fipe_defaulted` (True quando `fipe_price is None or fipe_price <= 0`, ou quando
  `price_dec is None`, espelhando a condição negativa do `if` da linha ~151), `mileage_defaulted`
  (True quando não entra no `if km is not None and ... year <= now.year`, linha ~165),
  `rarity_defaulted` (True quando não satisfaz `rarity_ratio is not None and sample_size >=
  min_market_sample`, linha ~181). Construir
  `defaulted_dimensions = [name for name, flag in [("market_price", market_price_defaulted), ("fipe_price", fipe_defaulted), ("mileage", mileage_defaulted), ("rarity", rarity_defaulted)] if flag]`
  e passar para o `ScoreResult(...)` retornado (linha 257).
- TOCA: `app/scoring/types.py`, `app/scoring/score_v2.py`, `tests/test_score_v2.py`
- VALIDA COM: `pytest tests/test_score_v2.py -k defaulted_dimensions -q` → verde (cobre REQ-003 a
  REQ-007); teste de round-trip via `to_dict()`/reconstrução manual do dict (REQ-008).
- ESCALA SE: alguma das 4 condições de fallback identificadas acima não bater exatamente com o
  código real ao editar (ex.: `fipe_score` também depende de `price_dec is not None`, então
  `fipe_defaulted` deve ser True também quando `price_dec is None`, mesmo com `fipe_price`
  presente — se isso gerar ambiguidade sobre "faltou dado do anúncio" vs "faltou dado de FIPE",
  escalar para decidir se são dimensões separadas).

### Etapa 3: Badge de score parcial no Telegram (REQ-009)
- FAZ: em `app/notifications/telegram_formatter.py`, adicionar função `_partial_score_badge(breakdown: dict) -> str | None`
  que lê `breakdown.get("defaulted_dimensions") or []`, retorna `None` se `len(...) < 2`, senão
  monta a linha `"⚠️ Score parcial — sem dados reais de: " + ", ".join(rótulo em pt-br para cada dimensão)`
  usando o mapa `{"market_price": "preço de mercado", "fipe_price": "FIPE", "mileage": "km/ano", "rarity": "raridade"}`.
  Chamar essa função no ponto de montagem de badges (próximo a `_get_breakdown`/`_price_context_badge`,
  `telegram_formatter.py:452+`), anexando o resultado (se não `None`) à lista de badges existente,
  respeitando o limite já existente (`_MAX_BADGES`, se houver).
- TOCA: `app/notifications/telegram_formatter.py`, `tests/test_telegram_formatter_vnext.py`
- VALIDA COM: `pytest tests/test_telegram_formatter_vnext.py -k partial_score -q` → verde; teste
  monta uma notificação com `score_breakdown={"defaulted_dimensions": ["market_price", "fipe_price"]}`
  e confere que a linha aparece na saída formatada; outro teste com `defaulted_dimensions=["mileage"]`
  (1 item) confere que a linha NÃO aparece.
- ESCALA SE: `_MAX_BADGES` ou o padrão de composição de badges em uso real divergir do assumido
  (ex.: badges não são uma lista simples, mas montadas por concatenação de string sem função
  central) — nesse caso a integração precisa ser redesenhada.

## Critérios de aceitação globais
1. Todos os REQ-001..009 cobertos por teste com evidência arquivo:linha.
2. Suíte completa verde: `pytest -q` (sem regressão em `test_score_v2.py`,
   `test_score_v2_integration_message.py`, `test_notifications_queue_service.py`,
   `test_telegram_formatter_vnext.py`, `test_contract_telegram_message.py`).
3. Nenhuma mudança de schema/migration (campo novo vive só no dataclass Python e no JSON de
   `score_breakdown`, que já é `JSONB` livre de schema fixo).
