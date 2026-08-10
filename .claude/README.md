# .ai/skills

Skills operacionais carregáveis por agentes no Indiciário.

Antes de executar qualquer tarefa, o agente deve:

1. ler `AGENTS.md`;
2. ler `docs/LLM_CONTEXT.md`;
3. identificar a skill adequada nesta pasta;
4. carregar o arquivo correspondente;
5. executar seguindo a skill.

## Skills disponíveis

Liste e use apenas arquivos que realmente existem em `.ai/skills/`.

| Situação | Skill | Arquivo |
|---|---|---|
| Bug, regressão, falha de PDF/build/validator ou causa desconhecida | `diagnose` | `.ai/skills/diagnose.md` |
| Mudança em código, validator, schema, renderer, package builder ou regra automatizável | `tdd` | `.ai/skills/tdd.md` |
| Mudança editorial, progressão, envelopes, dicas, mapas ou guia | `grill-with-docs` | `.ai/skills/grill-with-docs.md` |
| Iniciativa grande demais para uma PR | `to-prd` | `.ai/skills/to-prd.md` |
| Quebrar PRD, roadmap ou playtest em tarefas pequenas | `to-issues` | `.ai/skills/to-issues.md` |
| Encerrar rodada e passar contexto | `handoff` | `.ai/skills/handoff.md` |
| Entender fluxo antes de mexer | `zoom-out` | `.ai/skills/zoom-out.md` |
| Revisão arquitetural explícita e incremental | `improve-codebase-architecture` | `.ai/skills/improve-codebase-architecture.md` |

## Regra de desempate

- Causa desconhecida: `diagnose`.
- Regra nova automatizável: `tdd`.
- Decisão editorial/produto: `grill-with-docs`.
- Escopo grande: `to-prd` antes de implementar.
- Contexto confuso: `zoom-out` antes de qualquer mudança.

## Conceitos que não devem ser confundidos

- **Skill**: procedimento reutilizável que orienta como executar uma tarefa.
- **Papel**: responsabilidade assumida por um agente em uma run, como Blind Solver, Gate Evaluator ou moderador.
- **Protocolo**: documento normativo que define regras, limites, segurança e governança.
- **Capacidade técnica**: código ou infraestrutura que executa funções como bundling, isolamento, hashing, validação ou orquestração.

A existência de um protocolo ou de uma entrada no roadmap não significa que a skill ou a capacidade técnica já exista.

## Skills planejadas

As skills abaixo são roadmap documental. Elas estão **PLANNED — NOT IMPLEMENTED**, não possuem arquivo em `.ai/skills/`, não estão disponíveis para seleção operacional e não devem ser simuladas como equivalentes a prompts informais.

### `context-firewall`

- **Status**: PLANNED — NOT IMPLEMENTED.
- **Objetivo**: orientar a preparação e auditoria de contexto isolado para um papel específico.
- **Quando será usada**: em futuras execuções cegas para selecionar artefatos permitidos, excluir materiais privados, normalizar nomes, registrar transformações e verificar a composição conceitual do bundle.
- **Pré-requisitos**: manifest, política de visibilidade, contratos conceituais aprovados e capacidade técnica de bundle.
- **Documentação normativa**: `docs/BLIND_CONTEXT_PROTOCOL.md`, `docs/MULTIAGENT_ARTIFACT_RUN_CONTRACTS.md` e `docs/MULTIAGENT_OPERATING_PROTOCOL.md`.
- **Issue/fase associada**: fase futura de Context Firewall após contratos de manifest, política de visibilidade e bundle.
- **Antes da implementação, não fazer**: não invocar `context-firewall`, não criar arquivo de skill, não prometer sandbox inexistente e não tratar revisão documental como isolamento técnico.

### `blind-solve`

- **Status**: PLANNED — NOT IMPLEMENTED.
- **Objetivo**: orientar um agente cego a tentar resolver uma etapa usando somente material autorizado.
- **Quando será usada**: depois que bundle cego auditado, papel, estágio, contexto isolado, output congelável e Gate Evaluator separado estiverem disponíveis.
- **Pré-requisitos**: Context Firewall funcional, manifest ou contrato de bundle implementado, schema futuro de output, política de ferramentas, protocolo de incidentes e Gate Evaluator.
- **Documentação normativa**: `docs/BLIND_CONTEXT_PROTOCOL.md`, `docs/MULTIAGENT_OPERATING_PROTOCOL.md` e `docs/MULTIAGENT_ARTIFACT_RUN_CONTRACTS.md`.
- **Issue/fase associada**: fase futura posterior ao Context Firewall e ao Gate Evaluator.
- **Antes da implementação, não fazer**: não invocar `blind-solve`, não simular cegueira em conversa contaminada, não deixar Blind Solver aprovar o próprio gate e não substituir playtest humano.

### `playtest-to-learning`

- **Status**: PLANNED — NOT IMPLEMENTED.
- **Objetivo**: transformar dados e observações de playtest em findings rastreáveis e decisões de aprendizado.
- **Quando será usada**: depois de sessão de playtest registrada, com observações concretas e necessidade de separar fato, hipótese causal e decisão.
- **Pré-requisitos**: schemas de sessão, finding e decisão de aprendizado, Learning Loop, política de generalização e validação de referências.
- **Documentação normativa**: `docs/MULTIAGENT_OPERATING_PROTOCOL.md`, `docs/MULTIAGENT_ARTIFACT_RUN_CONTRACTS.md`, `docs/PRD_MULTIAGENT_CASE_CREATION.md` e `docs/IMPLEMENTATION_PLAN_MULTIAGENT_PIPELINE.md`.
- **Issue/fase associada**: primeira skill futura recomendada, após os schemas do Learning Loop.
- **Antes da implementação, não fazer**: não invocar `playtest-to-learning`, não converter mesa simulada em playtest real, não transformar uma ocorrência isolada em regra global e não apagar finding histórico.

## Ordem recomendada para skills planejadas

1. `playtest-to-learning`, somente depois dos schemas de sessão, finding e decisão de aprendizado.
2. `context-firewall`, em paralelo após contratos de manifest, política de visibilidade e capacidade de bundle.
3. `blind-solve`, somente quando Context Firewall e Gate Evaluator estiverem operacionais.

`blind-solve` não deve ser criado antes do mecanismo de isolamento que o torna confiável.

## Seleção temporária enquanto as skills planejadas não existem

| Necessidade atual | Skill disponível a usar |
|---|---|
| Revisar decisões de segurança de contexto | `grill-with-docs` |
| Definir arquitetura ou escopo amplo | `to-prd` |
| Decompor uma iniciativa aprovada | `to-issues` |
| Depurar implementação futura | `diagnose` |
| Implementar com testes | `tdd` |

Não substitua `context-firewall` ou `blind-solve` por um prompt informal alegando equivalência.

## Obrigatório na resposta final do agente

- skill escolhida;
- motivo da escolha;
- arquivos alterados;
- comandos executados;
- resultados ou limitações;
- pendências reais.
