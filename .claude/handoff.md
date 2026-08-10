# Skill: handoff

Use ao encerrar uma rodada de trabalho, passar contexto para outro agente ou registrar estado seguro após uma PR, investigação ou tentativa de build.

## Procedimento

1. Leia `AGENTS.md` e `docs/LLM_CONTEXT.md`.
2. Resuma o objetivo original.
3. Registre o estado atual.
4. Liste arquivos alterados.
5. Registre decisões técnicas e editoriais.
6. Registre validações executadas.
7. Declare limitações de ambiente.
8. Indique uma única próxima ação recomendada.

## Estrutura obrigatória

- Objetivo original.
- Estado atual.
- Arquivos alterados.
- Decisões tomadas.
- Validações executadas.
- Limitações ou falhas de ambiente.
- Pendências reais.
- Próximo passo recomendado.

## Guardrails

- Não esconda falha de Playwright/Chromium, build PDF, validator ou teste.
- Se usou PDF fake, diga que não prova baseline visual real.
- Diferencie pendência real de ideia futura.
- Se a mudança foi docs-only, diga que testes não foram necessários ou não foram executados por esse motivo.

## Resposta final

Entregue um handoff claro e reutilizável pelo próximo agente.
