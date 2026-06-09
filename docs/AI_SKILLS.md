# AI Skills — AutoHunter / Garagem Alvo

Este documento registra as skills recomendadas para trabalhar com agentes/LLMs no repositório AutoHunter.

Referência externa avaliada: `mattpocock/skills`, especialmente as categorias `engineering`, `productivity` e `misc`. As skills abaixo foram adaptadas ao contexto do AutoHunter, sem copiar o conteúdo original literalmente.

## Como usar

Antes de pedir uma tarefa para Codex/Claude/ChatGPT, escolha uma das skills abaixo e cole o bloco correspondente junto com a tarefa.

Regras gerais para qualquer skill:

- Trate o código atual como fonte de verdade.
- Leia `AGENTS.md`, `README.md`, `docs/LLM_CONTEXT.md`, `docs/ARCHITECTURE.md` e os documentos específicos da frente antes de propor mudanças amplas.
- Preserve o produto Telegram-first: bot, scheduler, filas, sources, matching e notificações.
- Não redesenhe arquitetura sem evidência.
- Não remova legado sem prova de ausência de uso.
- Separe bug real, risco operacional, melhoria técnica e melhoria de produto.
- Toda mudança prática deve terminar com validação local objetiva.

## 1. diagnose

Use para bugs difíceis, regressões, lentidão, falhas de source, scheduler, filas, matching, notificações, billing, admin ou Telegram.

Prompt base:

```text
Use a skill diagnose para investigar este problema no AutoHunter.

Objetivo: diagnosticar antes de corrigir.

Siga este fluxo:
1. Reproduza ou encontre o caminho mais próximo de reprodução.
2. Localize o menor fluxo afetado.
3. Declare hipóteses explícitas.
4. Instrumente apenas o necessário.
5. Corrija a menor causa raiz possível.
6. Adicione teste de regressão.
7. Rode validações objetivas.

Respeite AGENTS.md e a arquitetura Telegram-first. Não faça refactor amplo junto com o fix.
```

## 2. tdd

Use para features ou correções com risco operacional: wishlist, filtros, planos, tracking, notificações, source gates, leilões e admin.

Prompt base:

```text
Use a skill tdd para implementar esta alteração no AutoHunter.

Fluxo obrigatório:
1. Escreva ou ajuste primeiro o teste que expressa o comportamento esperado.
2. Rode o teste e confirme falha relevante.
3. Implemente a menor alteração possível.
4. Rode o teste específico.
5. Rode uma suíte curta relacionada.
6. Liste o que foi validado.

Não quebre compatibilidade de comandos Telegram ou fluxos legados sem decisão explícita.
```

## 3. improve-codebase-architecture

Use para avaliar acoplamento, legado, duplicidade, fronteiras de domínio e preparação para v2.

Prompt base:

```text
Use a skill improve-codebase-architecture para avaliar a arquitetura atual do AutoHunter.

Priorize:
- clareza entre bot, scheduler, workers, services, sources, models e API auxiliar;
- contratos de normalização, ingestão, matching e notificação;
- remoção segura de duplicidade;
- redução de acoplamento sem big bang;
- compatibilidade com Raspberry/execução 24/7;
- preservação de gates de leilões e planos.

Entregue recomendações em fatias pequenas, com risco, benefício e validação sugerida.
```

## 4. to-issues

Use para transformar roadmap, análise, PRD ou documentação em issues executáveis.

Prompt base:

```text
Use a skill to-issues para quebrar esta frente do AutoHunter em issues pequenas.

Cada issue deve ter:
- título objetivo;
- contexto;
- escopo incluído;
- fora de escopo;
- arquivos prováveis;
- critérios de aceite;
- validação local;
- risco operacional;
- dependências.

Prefira fatias verticais entregáveis, não tarefas genéricas por camada.
```

## 5. triage

Use para classificar bugs, ideias, dívidas técnicas e pedidos de produto.

Prompt base:

```text
Use a skill triage para classificar este item do AutoHunter.

Classifique como uma ou mais categorias:
- bug real;
- risco operacional;
- dívida técnica;
- melhoria de produto;
- melhoria de UX/copy;
- launch blocker;
- oportunidade futura;
- item a descartar.

Informe severidade, impacto, evidência, próximo passo mínimo e validação esperada.
```

## 6. zoom-out

Use quando a análise estiver presa em arquivo/função e precisar recuperar o fluxo completo do produto.

Prompt base:

```text
Use a skill zoom-out no AutoHunter.

Antes de alterar código, explique:
- qual fluxo maior este trecho pertence;
- quem chama;
- que dados entram e saem;
- que tabela/configuração/runtime participa;
- que comportamento chega ao usuário no Telegram;
- quais contratos não podem quebrar.

Depois proponha a menor intervenção segura.
```

## 7. grill-with-docs

Use para confrontar um plano contra docs vivas antes de implementar.

Prompt base:

```text
Use a skill grill-with-docs para desafiar este plano do AutoHunter.

Leia e confronte com:
- AGENTS.md;
- README.md;
- docs/LLM_CONTEXT.md;
- docs/ARCHITECTURE.md;
- docs/PROJECT_GUIDELINE.md;
- docs/ROADMAP.md;
- docs/LAUNCH_PLAN.md quando envolver lançamento;
- docs/AUCTION_RUNTIME.md quando envolver leilões.

Aponte inconsistências, termos errados, decisões já tomadas, riscos e ajustes necessários antes de implementar.
```

## 8. to-prd

Use para features maiores: Mercado Pago/webhook, leilões v2, onboarding Premium, UX de busca, growth, Instagram/social ou source nova.

Prompt base:

```text
Use a skill to-prd para transformar esta ideia em PRD do AutoHunter.

Inclua:
- problema;
- público afetado;
- objetivo de produto;
- não objetivos;
- fluxo Telegram esperado;
- regras de negócio;
- impacto técnico;
- dados/tabelas/config envolvidos;
- riscos;
- métricas de sucesso;
- critérios de aceite;
- plano incremental de implementação.

Não trate API web como jornada principal do usuário final, salvo requisito explícito.
```

## 9. handoff

Use para compactar uma conversa longa em contexto reutilizável para outro chat/agente.

Prompt base:

```text
Use a skill handoff para gerar um handoff do AutoHunter.

Inclua:
- estado atual confirmado;
- decisões tomadas;
- arquivos alterados ou relevantes;
- problemas resolvidos;
- pendências;
- riscos;
- próximos passos recomendados;
- comandos de validação;
- pontos que não devem ser reabertos sem evidência nova.

O resultado deve ser copiável para um novo chat.
```

## 10. prototype

Use para explorar rapidamente UX, copy, scoring, alertas, menu Telegram ou regra de negócio antes de mexer no runtime real.

Prompt base:

```text
Use a skill prototype para explorar esta ideia do AutoHunter sem acoplar ao runtime principal.

Crie um protótipo descartável ou isolado que ajude a decidir.

O protótipo deve:
- ser simples de rodar;
- não exigir credenciais reais;
- não alterar banco de produção;
- deixar claro o que foi aprendido;
- indicar se deve virar implementação real, ser ajustado ou descartado.
```

## 11. git-guardrails-claude-code

Use quando um agente com acesso ao repositório puder executar comandos Git perigosos.

Prompt base:

```text
Use a skill git-guardrails-claude-code para propor guardrails de Git neste repo.

Objetivo:
- impedir comandos destrutivos acidentais;
- bloquear push direto sem intenção explícita;
- evitar reset hard, clean agressivo, force push e deleção de branch;
- preservar trabalho local não commitado;
- documentar exceções seguras.

Adapte ao fluxo real do AutoHunter e não assuma stack Node/Husky se não fizer sentido.
```

## 12. setup-pre-commit

Use para propor hooks/checks locais de qualidade adaptados a Python.

Prompt base:

```text
Use a skill setup-pre-commit para avaliar e propor pre-commit no AutoHunter.

Adapte para Python e para o estado real do projeto.

Considere:
- ruff/format/lint quando aplicável;
- pytest seletivo ou smoke tests leves;
- checagem de secrets;
- checagem de arquivos grandes/cache/debug artifacts;
- proteção contra alteração acidental de migrations críticas;
- custo aceitável para uso local.

Não introduza ferramenta pesada sem justificar benefício operacional.
```

## Ordem recomendada por cenário

| Cenário | Skill principal | Apoio |
|---|---|---|
| Bug em produção/admin/source | `diagnose` | `tdd`, `zoom-out` |
| Nova feature de produto | `to-prd` | `to-issues`, `tdd` |
| Roadmap/documento grande | `to-issues` | `triage`, `grill-with-docs` |
| Refactor ou v2 | `improve-codebase-architecture` | `zoom-out`, `tdd` |
| Dúvida se plano faz sentido | `grill-with-docs` | `triage` |
| Novo chat/agente | `handoff` | `zoom-out` |
| Ideia ainda nebulosa | `prototype` | `to-prd` |
| Segurança operacional local | `git-guardrails-claude-code` | `setup-pre-commit` |
