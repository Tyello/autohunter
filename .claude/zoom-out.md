# Skill: zoom-out

Use quando o contexto estiver confuso, a tarefa parecer grande demais ou houver risco de alterar o lugar errado.

## Procedimento

1. Leia `AGENTS.md` e `docs/LLM_CONTEXT.md`.
2. Mapeie o fluxo afetado de ponta a ponta.
3. Separe camadas: conteúdo, modelo, validação, renderização, pacote, PDF e documentação.
4. Identifique o menor ponto correto de mudança.
5. Evite solução superdimensionada.
6. Recomende a próxima ação ou próxima skill.

## Saída obrigatória

- Skill: `zoom-out`.
- Fluxo afetado.
- Camadas envolvidas.
- Menor ponto correto de mudança.
- Risco de complexidade desnecessária.
- Próxima skill recomendada, se aplicável.

## Guardrail

Não pule para código quando o problema for núcleo investigativo, e não mude núcleo investigativo quando o problema for apenas layout ou renderização.
