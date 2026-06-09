# AutoHunter AI Skills

Este diretório contém skills operacionais para agentes/LLMs trabalhando no AutoHunter/Garagem Alvo.

## Regra de uso

Antes de executar qualquer tarefa, o agente deve:

1. Ler `AGENTS.md`.
2. Identificar o tipo de tarefa.
3. Escolher a skill adequada neste diretório.
4. Seguir a skill escolhida.
5. Validar localmente e reportar comandos/resultado.

## Mapa de seleção

| Tarefa | Skill |
|---|---|
| Bug, regressão, falha operacional | `diagnose.md` |
| Implementação com segurança | `tdd.md` |
| Refactor, v2, arquitetura | `improve-codebase-architecture.md` |
| Roadmap/documento para tarefas | `to-issues.md` |
| Classificar bug/ideia/dívida | `triage.md` |
| Entender fluxo antes de mexer | `zoom-out.md` |
| Confrontar plano contra docs | `grill-with-docs.md` |
| Feature grande/novo produto | `to-prd.md` |
| Novo chat/handoff | `handoff.md` |
| Experimento descartável | `prototype.md` |
| Segurança Git para agentes | `git-guardrails-claude-code.md` |
| Hooks/checks locais | `setup-pre-commit.md` |

## Guardrails comuns

- Código atual é fonte de verdade.
- Produto é Telegram-first; FastAPI é auxiliar.
- Não expor detalhes internos ao usuário final.
- Não redesenhar arquitetura sem evidência.
- Não remover legado sem prova de uso.
- Preservar scheduler, filas, matching, notifications e gates de leilões.
- Separar bug real, risco operacional, dívida técnica e melhoria de produto.
