# Documentação — Garagem Alvo / AutoHunter

Atualizado em: 2026-06-09.

Este diretório mantém documentação viva do runtime AutoHunter, produto público Garagem Alvo. A fonte de verdade continua sendo o código atual e o estado operacional em banco (`source_configs`, `source_states`, `AppKV`).

## Leitura principal

| Documento | Papel |
|---|---|
| `../README.md` | Entrada do repositório e estado do produto. |
| `../AGENTS.md` | Mapa mental curto para agentes/LLMs. |
| `LLM_CONTEXT.md` | Contexto completo para novas sessões técnicas. |
| `AI_SKILLS.md` | Skills recomendadas para orientar Codex/Claude/ChatGPT em diagnóstico, TDD, triage, PRD, issues, arquitetura e handoff. |
| `USER_FLOWS.md` | Fluxos atuais de usuário, admin e operação no Telegram. |
| `ARCHITECTURE.md` | Arquitetura, camadas e contratos operacionais. |
| `PROJECT_GUIDELINE.md` | Diretrizes vivas de produto/runtime. |
| `ROADMAP.md` | Prioridades atuais. |
| `LAUNCH_PLAN.md` | Beta, lançamento e critérios comerciais/operacionais. |
| `OPERATIONS_RUNBOOK.md` | Operação diária e troubleshooting. |
| `AUCTION_RUNTIME.md` | Runtime e gates de leilões. |
| `BACKUP_RESTORE.md` | Backup/restore operacional. |
| `LEGACY_INVENTORY.md` | Legado e compatibilidade que não devem ser removidos sem validação. |
| `V1_TO_V2_MIGRATION.md` | Trilha técnica de migração/dual-run de sources. |

## Planos por frente

Os arquivos numerados são donos de frentes específicas e devem ser mantidos curtos:

- `01_UX.md`: UX, copy, digest e alertas user-facing.
- `02_FLUXO.md`: jornadas de usuário e gaps de fluxo.
- `03_ARQUITETURA.md`: refactors e decomposição técnica.
- `04_LAUNCH_PLAN.md`: checklist de beta/lançamento.
- `05_PLAN.md`: limites, Free/Premium, trial/founders.
- `06_SUBSCRIPTION.md`: pagamento, Mercado Pago e ativação Premium.
- `07_BUGS.md`: bugs/validações técnicas ainda relevantes.
- `08_EFICIENCIA.md`: carga, Raspberry, sender, métricas e operação.

## Documentos específicos mantidos

Docs específicos de FIPE, sources, migrations, backup drill, Facebook Agent, Raspberry, dedupe/schema e auditorias técnicas permanecem quando têm comandos, contratos ou evidências úteis para operação ou testes.

## Política de remoção

Documentos temporários, propostas antigas, handoffs, patch notes e roadmaps duplicados devem ser removidos quando já estiverem cobertos por docs vivos. Não mantenha arquivos apenas por histórico se eles competirem com o estado atual.
