# RUN log — 020-score-v2-data-completeness

Append-only. Uma linha por evento (etapa concluída, escalação, reprovação+DVG, veredito).

- 2026-09-03: spec criada, tier T2, nenhuma etapa executada ainda.
- 2026-09-03: Etapa 1 (REQ-001, REQ-002) reprovada pelo spec-reviewer com "Causa provável: spec"
  (DVG-002) — spec citava linhas 267 e 411 de `notifications_queue_service.py` como os 2 call
  sites de `score_ad(`, mas a spec 019 (executada antes, commit b212c90) adicionou ~84 linhas de
  logging no mesmo arquivo e deslocou os call sites para ~351 e ~495. O executor já tinha usado
  grep em vez de linha literal e corrigido os 2 call sites reais corretamente (um em
  `queue_notifications_for_matches`, outro em `queue_notifications_for_matches_diag` — confirmado
  por leitura do código atual como caminho de produção real do scheduler, não diagnóstico morto).
  Resolução (spec-resolver): SPEC.md corrigida (REQ-002, Etapa 1, Decisões tomadas) para usar
  `grep -n "score_ad("` como critério de localização em vez de número de linha fixo, e para citar
  ambas as funções nominalmente. Nenhuma re-execução necessária — implementação já presente
  satisfaz a intenção corrigida. Etapa 1 RE-APROVADA.
- 2026-09-03: Etapa 1 commitada (d8d6c82) — `settings.score_min_market_sample` e propagação nos
  2 call sites de `score_ad(`.
- 2026-09-03: Etapa 2 (REQ-003 a REQ-008, `defaulted_dimensions` em `ScoreResult`) executada,
  aprovada pelo spec-reviewer sem defeitos (4 flags booleanos explícitos por dimensão, round-trip
  to_dict/from_dict validado, PREM-01 respeitada — match_score fora do tracking). Commitada
  (4277397).
- 2026-09-03: Etapa 3 (REQ-009, badge "⚠️ Score parcial" no Telegram) executada. Reprovada 2x:
  DVG-001 (major, causa execução) — `_partial_score_badge()` retornava só o texto fixo sem a
  lista de dimensões em português exigida pela spec; corrigido com mapa `_DIMENSION_LABELS_PT`.
  DVG-002 (major, causa execução) — `build_badges()` aplicava `_clip(text, 34)` genérico em toda
  badge, truncando a lista de dimensões na mensagem final do Telegram e esvaziando o propósito do
  REQ-009; corrigido com limite de 120 chars específico para a badge de score parcial, preservando
  clip de 34 nas demais badges. 3ª revisão: APROVADO. Commitada (fc19ad7).
- 2026-09-03: Spec 020 fechada — 3/3 etapas aprovadas e commitadas (d8d6c82, 4277397, fc19ad7).
  Sem etapas `[sensível]`; sem exigência de spec-verifier independente (aplica-se só a T2 com
  passos sensíveis). Suíte completa de testes do repositório confirmada verde durante o processo.
