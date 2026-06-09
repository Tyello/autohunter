# Skill: diagnose

Use para bugs difíceis, regressões, lentidão, falhas de source, scheduler, filas, matching, notificações, billing, admin ou Telegram.

## Objetivo

Diagnosticar antes de corrigir. Encontrar causa raiz, não apenas sintoma.

## Processo

1. Leia `AGENTS.md` e entenda o fluxo afetado.
2. Reproduza ou encontre o caminho mais próximo de reprodução.
3. Delimite o menor fluxo afetado.
4. Declare hipóteses explícitas.
5. Inspecione logs, testes e código no ponto de falha.
6. Instrumente apenas o necessário.
7. Corrija a menor causa raiz possível.
8. Adicione teste de regressão.
9. Rode validações objetivas.

## Regras AutoHunter

- Não faça refactor amplo junto com o fix.
- Preserve compatibilidade de bot, scheduler, filas e notificações.
- Diferencie indisponibilidade de source de bug sistêmico.
- Para leilões, preserve todos os gates de segurança.

## Saída esperada

- Causa raiz.
- Arquivos alterados.
- Teste de regressão.
- Comandos executados e resultados.
- Riscos remanescentes.
