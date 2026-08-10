# Skill: to-issues

Use para quebrar PRD, roadmap, relatório de playtest, auditoria ou proposta grande em tarefas pequenas para Codex/agentes.

## Procedimento

1. Leia `AGENTS.md` e `docs/LLM_CONTEXT.md`.
2. Leia o PRD ou documento de origem.
3. Separe tarefas por tipo: editorial, validator, renderer, package, docs, test ou architecture.
4. Gere tarefas pequenas, independentes e verificáveis.
5. Priorize em P0, P1, P2 ou P3.

## Prioridade

- P0: bloqueia baseline/playtest ou quebra geração.
- P1: melhora clareza, solvabilidade ou facilitador com impacto direto.
- P2: lapidação ou automação útil, mas não bloqueante.
- P3: ideia futura sem evidência suficiente.

## Template por issue

- Título.
- Prioridade.
- Tipo.
- Objetivo.
- Escopo.
- Fora de escopo.
- Critérios de aceitação.
- Validação sugerida.
- Arquivos prováveis.

## Guardrails

- Não misturar novo caso, renderer e validator na mesma issue.
- Issues P0/P1 devem ter validação objetiva.
- Tarefa de PDF deve mencionar build real com Playwright/Chromium.
- Cada issue deve proteger a experiência offline-first.
- Cada issue que tocar jogador deve preservar evidência bruta sem interpretação do autor.

## Resposta final

Entregue a lista de issues propostas, ordenadas por prioridade.
