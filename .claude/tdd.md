# Skill: tdd

Use quando a tarefa alterar comportamento de código, validação, schema, renderer, package builder, manifest, case kernel, case review ou regra automatizável dos casos canônicos.

## Procedimento

1. Leia `AGENTS.md` e `docs/LLM_CONTEXT.md`.
2. Defina a regra esperada em uma frase.
3. Escreva ou ajuste um teste que falhe sem a mudança.
4. Rode o teste específico e confirme a falha correta.
5. Implemente a menor mudança para passar.
6. Refatore apenas o necessário.
7. Rode validações compatíveis com o escopo.

## Validação

- Teste específico primeiro.
- `pytest tests/ -q` quando viável.
- `ruff check generator/` se tocar Python.
- Validators strict se tocar blueprint/schema/validator.
- Build real se tocar renderização/pacote.

## Guardrails

- Não reduza qualidade editorial para fazer teste passar.
- Se tocar documento de jogador, preserve evidência bruta sem interpretação.
- Se tocar PDF, registre limitação de Playwright/Chromium quando houver.

## Resposta final

Informe:

- skill: `tdd`;
- regra protegida;
- teste criado/alterado;
- evidência de red/green, se disponível;
- arquivos alterados;
- comandos e resultados;
- limitações de ambiente.
