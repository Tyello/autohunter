# Spec 022 — Reformatar mensagem de notificação de anúncio

[spec-kit: T2 — 5pts: arquivos=1 (2-4: 1 fonte + 2 testes), decisões=1, risco=1, novidade=0, verif=2]

## Objetivo

`format_ad_message` (app/notifications/telegram_formatter.py) hoje mistura fato (FIPE, preço) com
julgamento de desvio (%) e promove um "motivo principal" que pode ser um sinal de score (ex.: preço
vs FIPE/mediana) mesmo quando o usuário nunca filtrou por preço. Objetivo: mostrar FIPE e preço como
valores absolutos, derivar o "motivo" exclusivamente dos critérios do wishlist que casaram, e remover
rótulos redundantes.

## Não-objetivos

- Não altera `app/scoring/score_v2.py` nem o cálculo do score.
- Não altera `format_tracked_price_drop_message` (notificação de queda de preço rastreada — feature
  separada).
- Não altera `app/bot/renderers.py`, `weekly_digest_renderer.py`, `app/core/scoring.py` (formatadores
  independentes, fora do escopo do brief).

## Premissas assumidas (PREM)

- **PREM-01**: o nome da fonte (`ad.source`) é exibido literalmente como armazenado (ex.: `webmotors`,
  `olx`), sem mapa de capitalização — fora de escopo ("mudança pontual, sem refactor amplo").
- **PREM-02**: o cap de 2 critérios em `_compact_filters` (já existente) é mantido — o brief não pede
  mudança de limite, só de exibição.
- **PREM-03** (resolvida com o usuário via pergunta objetiva): badges de km, câmbio, tipo de
  vendedor, sinistro/leilão/blindado e raridade são mantidos, anexados após o bloco
  cidade·preço·fonte na linha 2.
- **PREM-04** (resolvida com o usuário): recência não-confiável ("🆕 Anúncio novo no feed" / "🕐
  Recente", heurística por `created_at`) é removida. Recência confiável (`⏱️ Há Xh`/`Ontem`, baseada
  em `published_at` confiável) é mantida.
- **PREM-05** (resolvida com o usuário): o aviso "⚠️ {motivo} — vale negociar" é removido por
  completo — dependia do texto de desvio de preço que está saindo.
- **PREM-06**: o badge de contexto de preço (`_price_context_badge`, que produzia tanto `% vs FIPE`
  quanto `% vs mediana` e variantes "sem base de mercado") é removido por inteiro — é precisamente o
  cálculo de desvio que o objetivo 1 proíbe, e não é específico de FIPE.

## Arquivos e mudanças

### `app/notifications/telegram_formatter.py`

1. **REQ-001**: `build_recency_badge` — remover o ramo de fallback não confiável (heurística sobre
   `created_at`); QUANDO `reliable` for falso, o sistema DEVE retornar `None` (nunca mais "🆕 Anúncio
   novo no feed" nem "🕐 Recente").
2. **REQ-002**: remover `_price_context_badge` e `_delta_badge_text` (mortos após REQ-004/005) e sua
   chamada em `build_badges`.
3. **REQ-003**: `build_badges` — remover também o badge de localização (`loc_badge`); a localização
   passa a compor a linha 2 junto com preço/fonte (REQ-006). `build_badges` passa a devolver apenas:
   recência (só confiável), km, câmbio, vendedor, flags de sinistro/leilão/blindado.
4. **REQ-004**: adicionar `_fipe_price(breakdown: dict) -> float | None`, lendo
   `market_context.fipe.fipe_price` (mesma forma aninhada que `_price_context_badge` já lia para o
   delta) — SEM cálculo de percentual.
5. **REQ-005**: remover `_main_reason`, `_negative_price_reason`, `_is_negative_reason`,
   `_NEGATIVE_REASON_MARKERS`, `_NON_ACTIONABLE_REASONS`, `build_reasons`, `_build_context_lines`,
   `_MAX_REASON`, `_MAX_REASONS` — o "motivo" nunca mais deriva de `breakdown["reasons"]` (sinal de
   score).
6. **REQ-006**: adicionar `_build_criteria_lines(ad) -> list[str]`: SE `_compact_filters(ad)` não for
   vazio, retorna `[f"✓ {f}" for f in matched]`; SENÃO, SE `ad.wishlist_query`/`ad.query` existir,
   retorna `[f"✓ {query_clipped}"]`; SENÃO `[]`. Nunca lê `breakdown`/`reasons`.
7. **REQ-007**: reescrever `format_ad_message`:
   - linha 1: `f"🔥 {score_i}/100 · {title}"` quando `score_i > 0` (separador `·`, não `—`); senão só
     `title` (comportamento de score parcial/ausente preservado).
   - linha 2 (`core`): `"📍 {loc} · {price_txt} · {source}"` (cada segmento omitido se vazio), seguido
     de `" | ".join(badges)` quando houver badges (REQ-003), tudo unido com `" | "`.
   - linha 3: sempre presente — `f"💰 FIPE {_format_price_brl(_fipe_price(breakdown))}"` (que já
     retorna `"—"` quando `None`).
   - linha(s) de raridade (`_rarity_context_line`): mantidas, inseridas entre a linha 2 e a linha 3,
     mesma posição relativa de hoje (feature não tocada pelo brief).
   - sem aviso de "vale negociar" (REQ removido, PREM-05).
   - linhas seguintes: `_build_criteria_lines(ad)` (REQ-006), sem cabeçalho "Por que você recebeu:",
     sem "Motivo principal:"/"Critério:".
   - sem "Fonte: " como rótulo — fonte é só um segmento da linha 2 (REQ-007).

### `tests/test_telegram_formatter_vnext.py`

8. **REQ-008**: reescrever/remover os testes que pinam o contrato antigo (motivo principal, `Critério:`,
   `Fonte:`, `_price_context_badge`, aviso "vale negociar", "Anúncio novo no feed"/"Recente" como
   badge de mensagem) para o novo formato. Lista de testes afetados (por nome atual):
   `test_complete_score_gt_zero_snapshot_and_order`, `test_score_92/77/58/35/12_shows_*` (só ajustar
   separador `·`), `test_score_header_keeps_badges_and_context_block`,
   `test_score_zero_with_query_shows_minimum_context`,
   `test_score_zero_with_filters_shows_criteria_context`,
   `test_year_filters_*` (4 testes — trocar `• Critério: X` por `✓ X`),
   `test_without_context_does_not_add_empty_context_block` (trocar a asserção de ausência de "Por que
   você recebeu:" por ausência de qualquer linha `✓`),
   `test_missing_price_shows_dash_and_no_invented_data` (trocar `"— • Fonte: webmotors"` por
   `"— · webmotors"` ou equivalente),
   `test_missing_delta_shows_conservative_price_context_badge`,
   `test_delta_badge_below_median_kept_when_delta_exists`,
   `test_delta_badge_above_median_kept_when_delta_exists`,
   `test_price_context_without_market_context`,
   `test_price_context_with_small_market_sample`,
   `test_price_context_with_enough_sample_but_missing_delta`,
   `test_missing_price_shows_explicit_not_informed_badge` (todos esses 6 dependiam do badge removido —
   REMOVER e substituir por testes de `_fipe_price`/linha FIPE conforme REQ-009),
   `test_recency_badge_fallback_created_at_new`, `test_recency_badge_fallback_created_at_recent`
   (ajustar: `build_recency_badge` agora retorna `None` quando não confiável),
   `test_format_ad_message_includes_created_at_fallback_badge` (ajustar: badge não confiável não
   aparece mais),
   `test_explainability_includes_compact_wishlist_filters` (trocar `• Critério:` por `✓`),
   `test_formatter_caps_extreme_fields_and_prioritizes_core_content` (trocar contagem de
   `"• Critério:"` por `"✓ "`, remover asserção de "Por que você recebeu:"),
   `test_non_actionable_reason_not_used_as_main_reason_when_query_exists` (trocar `• Motivo
   principal:`/`• Busca:` por ausência de reasons-based text / `✓ civic si`),
   `test_positive_score_with_reason_keeps_main_reason` — REMOVER (a premissa do teste, "reason vira
   motivo principal", é exatamente o que REQ-005 proíbe).

9. **REQ-009**: adicionar 3 testes novos cobrindo o deliverable pedido no brief:
   - `test_fipe_line_shows_absolute_value_when_present`: `market_context.fipe.fipe_price=36500` →
     texto contém `"💰 FIPE R$ 36.500,00"` e NÃO contém `"%"`.
   - `test_fipe_line_shows_dash_when_absent`: sem `market_context.fipe` → texto contém
     `"💰 FIPE —"`.
   - `test_criteria_lines_list_only_user_filters_never_price_reason`: `wishlist_filters=[{"field":
     "year", "operator": "lte", "value": "2008"}]` e `score_breakdown["reasons"] = ["Preço 11% abaixo
     da FIPE"]` → texto contém `"✓ ano ≤ 2008"` e NÃO contém `"abaixo da FIPE"` nem `"Motivo
     principal"`.

### `tests/test_contract_telegram_message.py`

10. **REQ-010**: `test_telegram_message_contract_vnext_formatting` — a asserção `assert any("Fonte:
    chavesnamao" in l for l in lines)` não é mais válida (rótulo "Fonte:" removido). Trocar por
    `assert any("chavesnamao" in l for l in lines)` (a fonte continua aparecendo, só sem o rótulo).

## Critérios de aceitação (EARS)

- QUANDO `market_context.fipe.fipe_price` existir no breakdown, o sistema DEVE exibir `💰 FIPE R$
  {valor}` sem nenhum caractere `%` na mensagem.
- QUANDO `market_context.fipe.fipe_price` não existir, o sistema DEVE exibir `💰 FIPE —`.
- QUANDO houver `wishlist_filters` que casaram, o sistema DEVE listar cada um como `✓ {texto}` e NUNCA
  incluir texto vindo de `breakdown["reasons"]`.
- QUANDO não houver `wishlist_filters` mas houver `wishlist_query`/`query`, o sistema DEVE mostrar
  `✓ {query}`.
- O sistema NUNCA DEVE emitir as strings "Por que você recebeu:", "Motivo principal:", "Critério:",
  "Fonte:", "Anúncio novo no feed", "vale negociar".
- QUANDO `score_i <= 0`, o sistema DEVE preservar o comportamento atual (linha 1 só com o título, sem
  badges de score).

## Condição de escalação

Se algum teste do arquivo `tests/test_telegram_formatter_vnext.py` não listado no REQ-008 falhar após
a mudança (efeito colateral não previsto), PARE e escale — não adivinhe uma correção fora do escopo
descrito aqui.

## Validação

`pytest tests/test_telegram_formatter_vnext.py tests/test_contract_telegram_message.py -q`
