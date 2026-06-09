# Skill: improve-codebase-architecture

Use para avaliar acoplamento, legado, duplicidade, fronteiras de domínio e preparação para v2.

## Objetivo

Melhorar a arquitetura de forma incremental, preservando a operação 24/7.

## Processo

1. Leia `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_GUIDELINE.md` e docs da frente.
2. Mapeie o fluxo real antes de propor mudanças.
3. Identifique acoplamentos, duplicidades e contratos frágeis.
4. Separe recomendações em fatias pequenas.
5. Para cada fatia, declare benefício, risco e validação.
6. Evite alterar áreas estáveis sem evidência.

## Prioridades AutoHunter

- Clareza entre bot, scheduler, workers, services, sources, models e API auxiliar.
- Contratos de normalização, ingestão, matching e notificação.
- Redução de acoplamento sem interromper runtime.
- Compatibilidade com Raspberry e execução contínua.
- Preservação dos gates de leilões e planos.

## Saída esperada

- Diagnóstico arquitetural.
- Lista priorizada de mudanças pequenas.
- Risco de cada mudança.
- Validação sugerida por mudança.
