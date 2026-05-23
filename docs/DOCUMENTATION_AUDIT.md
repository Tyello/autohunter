# AutoHunter — Auditoria de documentação

Atualizado em: 2026-05-22.

Objetivo: indicar quais documentos devem ser tratados como vivos, quais são históricos e quais podem virar candidatos a remoção/arquivamento após validação.

Esta auditoria não apaga arquivos automaticamente. Ela cria um mapa seguro para reduzir ruído de onboarding de humanos e LLMs.

## 1. Docs vivos oficiais

Estes documentos devem permanecer e ser mantidos atualizados:

| Documento | Papel |
|---|---|
| `README.md` | Entrada principal do repo; explica Garagem Alvo vs AutoHunter, estado atual e aponta leituras. |
| `AGENTS.md` | Mapa mental curto para LLMs/agentes. |
| `docs/USER_FLOWS.md` | Fluxos atuais de usuário, admin, produto e UX Telegram. |
| `docs/PROJECT_GUIDELINE.md` | Visão viva de produto/runtime. |
| `docs/ARCHITECTURE.md` | Arquitetura atual, camadas, fluxos e contratos operacionais. |
| `docs/LLM_CONTEXT.md` | Guia de contexto para qualquer LLM entender o projeto rapidamente. |
| `docs/ROADMAP.md` | Roadmap oficial consolidado e priorizado. |
| `docs/LAUNCH_PLAN.md` | Plano de lançamento, beta, founders, aquisição e lacunas go-to-market. |
| `docs/AUCTION_RUNTIME.md` | Fonte viva da frente de leilões. |
| `docs/OPERATIONS_RUNBOOK.md` | Operação diária e triagem. |
| `docs/BACKUP_RESTORE.md` | Backup/restore mínimo. |
| `docs/LEGACY_INVENTORY.md` | Inventário de legado e compatibilidade. |
| `docs/V1_TO_V2_MIGRATION.md` | Estado real e trilha técnica de migração V1→V2 de sources. |

## 2. Docs úteis, mas específicos

Manter se ainda ajudarem operação, QA ou produto. Não precisam ser lidos por todo LLM antes de mexer no projeto.

Exemplos de categorias:

- checklists de lançamento;
- runbooks de deploy;
- docs de UX de fluxo concluído;
- documentos de troubleshooting específico;
- documentação de comandos admin específicos;
- notas de validação de migrations ou backup;
- relatórios de dual-run/paridade por source.

Recomendação: manter, mas linkar a partir dos docs vivos somente quando forem realmente necessários.

## 3. Docs históricos

Candidatos a mover para `docs/archive/` ou renomear com prefixo `archive_`, se existirem no repo:

- `docs/PATCH_*.md`
- `docs/diagnostico_handoff_*.md`
- `docs/projeto.md`
- documentos antigos que descrevem leilões como POC exclusivamente admin-only;
- documentos que descrevem AutoHunter como nome público final, se não mencionarem Garagem Alvo;
- documentos que tratam FastAPI/web como jornada principal do usuário final;
- documentos que assumem sources ou planos antigos sem refletir `source_configs`/DB-driven runtime.

Esses documentos podem ser preservados como histórico, mas não devem competir com os docs vivos.

Observação: `docs/UX_IMPROVEMENTS.md` está encerrado e deve ser lido como registro histórico do bloco UX já concluído, não como roadmap ativo.

## 4. Docs potencialmente depreciados/removíveis

Um documento pode ser removido ou arquivado quando cair em pelo menos um caso abaixo:

1. Repete conteúdo dos docs vivos com informação pior ou antiga.
2. Contém instruções operacionais que contradizem o runtime atual.
3. Fala de comandos que não existem mais e não é claramente histórico.
4. Usa nomes antigos de produto em contexto user-facing sem explicar Garagem Alvo.
5. Descreve leilões sem os gates atuais de opt-in/source/categoria/dry-run.
6. Descreve setup que pula Alembic, Supabase/Postgres ou DB-driven configs.
7. Foi criado como handoff temporário de PR e não serve mais para operação.
8. Trata WebMotors como erro de proxy simples, ignorando a decisão atual de bloqueio anti-bot/fingerprint e source despriorizada.
9. Trata Premium como billing automático sem webhook/ativação automática implementada.

## 5. Procedimento seguro para remover/arquivar docs

Antes de apagar:

```bash
# procurar links internos
rg "NOME_DO_ARQUIVO|titulo ou trecho importante" README.md AGENTS.md docs app tests

# procurar referências amplas
rg "PATCH_|diagnostico_handoff|projeto.md|launch_plan" .
```

Critérios:

- se houver link a partir de README/AGENTS/docs vivos, atualizar link primeiro;
- se houver conteúdo único ainda válido, migrar trecho para doc vivo antes de arquivar;
- se for apenas histórico de PR, mover para `docs/archive/` ou apagar após confirmação;
- se afetar operação real, não remover sem validação no ambiente.

## 6. Recomendação prática de organização

Estrutura recomendada dos docs vivos principais:

```text
docs/
  ARCHITECTURE.md
  AUCTION_RUNTIME.md
  BACKUP_RESTORE.md
  DOCUMENTATION_AUDIT.md
  LAUNCH_PLAN.md
  LEGACY_INVENTORY.md
  LLM_CONTEXT.md
  OPERATIONS_RUNBOOK.md
  PROJECT_GUIDELINE.md
  ROADMAP.md
  USER_FLOWS.md
  V1_TO_V2_MIGRATION.md
  archive/
    ...histórico opcional...
```

## 7. Estado da auditoria atual

Durante esta revisão, os seguintes pontos foram observados:

- `README.md`, `AGENTS.md`, `docs/PROJECT_GUIDELINE.md`, `docs/ARCHITECTURE.md` e `docs/LLM_CONTEXT.md` foram alinhados com o estado atual de produto, arquitetura, fluxos e lacunas.
- `docs/USER_FLOWS.md` foi criado como fonte dedicada para os fluxos atuais de usuário/admin.
- `docs/ROADMAP.md` foi atualizado para remover itens já concluídos do roadmap ativo e priorizar lançamento, métricas, carga, digest e operação beta.
- `docs/LAUNCH_PLAN.md` foi revisado para refletir que a lacuna atual é go-to-market/operação comercial, não inexistência do produto.
- `docs/OPERATIONS_RUNBOOK.md` foi atualizado com lacunas de métricas, Premium manual, teste de carga e postura atual sobre WebMotors/TurboClass.
- `docs/UX_IMPROVEMENTS.md` está corretamente marcado como bloco UX concluído.
- `docs/V1_TO_V2_MIGRATION.md` já reflete a trilha técnica recente de inventário e dual-run inicial.

## 8. Candidatos citados para revisão manual

A existência e conteúdo de cada arquivo deve ser confirmada antes de remover. A recomendação é procurar por estes padrões:

```text
docs/PATCH_*.md
docs/diagnostico_handoff_*.md
docs/projeto.md
docs/launch_plan.md
```

Ação recomendada:

- se forem handoffs temporários: mover para `docs/archive/` ou remover;
- se tiverem decisões ainda válidas: migrar para `PROJECT_GUIDELINE.md`, `ARCHITECTURE.md`, `USER_FLOWS.md`, `AUCTION_RUNTIME.md`, `ROADMAP.md`, `LAUNCH_PLAN.md` ou `OPERATIONS_RUNBOOK.md`;
- se conflitarem com runtime atual: arquivar com aviso ou remover.

## 9. Como manter docs vivos daqui em diante

Atualizar documentação viva quando mudar qualquer um destes pontos:

- fluxo do usuário no Telegram;
- limites/plano Free/Premium;
- billing/ativação Premium;
- estado operacional de WebMotors ou outras sources primárias;
- gates de leilões;
- scheduler/filas/sender;
- V1→V2 de sources;
- roadmap ativo;
- plano de lançamento.

Regra simples: se uma nova LLM poderia errar por ler o doc antigo, atualize o doc na mesma PR.
