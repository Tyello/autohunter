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
