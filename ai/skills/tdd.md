# Skill: tdd

Use para features ou correções com risco operacional: wishlist, filtros, planos, tracking, notificações, source gates, leilões e admin.

## Objetivo

Implementar com teste guiando comportamento e protegendo regressões.

## Processo

1. Leia o fluxo afetado em `AGENTS.md` e docs específicas.
2. Escreva ou ajuste primeiro o teste que expressa o comportamento esperado.
3. Rode o teste e confirme falha relevante.
4. Implemente a menor alteração possível.
5. Rode o teste específico.
6. Rode uma suíte curta relacionada.
7. Liste validações e riscos.

## Regras AutoHunter

- Não quebre compatibilidade de comandos Telegram sem decisão explícita.
- Não faça teste dependente de credenciais reais.
- Prefira fixtures/mocks para sources e Telegram.
- Para DB/migrations, valide Alembic quando aplicável.

## Saída esperada

- Teste criado/alterado.
- Comportamento coberto.
- Implementação mínima.
- Comandos executados.
