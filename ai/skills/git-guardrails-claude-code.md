# Skill: git-guardrails-claude-code

Use quando um agente com acesso ao repositório puder executar comandos Git perigosos.

## Objetivo

Reduzir risco de perda de trabalho local ou alteração destrutiva acidental.

## Guardrails

O agente deve evitar sem autorização explícita:

- `git reset --hard`
- `git clean -fd`
- `git push --force`
- deleção de branch
- rebase destrutivo
- alteração em massa sem diff revisável

## Processo

1. Verifique `git status` antes de mudanças.
2. Preserve trabalho não commitado.
3. Use branches/commits pequenos quando aplicável.
4. Mostre diff relevante antes de encerrar.
5. Nunca esconda falhas de merge, teste ou lint.

## Regras AutoHunter

- Não apagar migrations, fixtures, docs vivas ou inventário legado sem validação.
- Não fazer push direto se o fluxo esperado for PR.
- Não tratar artefatos locais/cache como código de produto sem confirmar.
