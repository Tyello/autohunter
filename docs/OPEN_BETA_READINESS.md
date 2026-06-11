# Garagem Alvo / AutoHunter — Prontidão para beta aberto

Atualizado em: 2026-06-10.

Este documento consolida o que já existe no repositório para preparar o Garagem Alvo para beta aberto e o que ainda precisa ser resolvido antes de ampliar o acesso público.

A fonte de verdade continua sendo o código atual, as migrations e o estado operacional no banco (`source_configs`, `source_states`, `AppKV`). Este arquivo é um mapa de decisão para lançamento, não substitui `docs/LAUNCH_PLAN.md` nem `docs/ROADMAP.md`.

## 1. Objetivo do lançamento

Sair de MVP/uso controlado para um beta aberto gradual, mantendo foco em:

- confiabilidade do bot Telegram;
- onboarding simples;
- alertas úteis e sem duplicidade;
- operação barata;
- fontes monitoráveis;
- pagamento/ativação Premium sem gargalo manual frágil;
- comunicação honesta sobre cobertura e limitações.

## 2. O que já está documentado no repositório

| Informação | Status | Onde está |
|---|---:|---|
| Identidade pública Garagem Alvo e runtime AutoHunter | Coberto | `README.md`, `docs/LLM_CONTEXT.md`, `docs/ROADMAP.md` |
| Produto Telegram-first | Coberto | `README.md`, `docs/ARCHITECTURE.md`, `docs/USER_FLOWS.md` |
| Público entusiasta automotivo | Coberto | `README.md`, `docs/LLM_CONTEXT.md`, `docs/ROADMAP.md` |
| Fluxo técnico principal | Coberto | `README.md`, `docs/ARCHITECTURE.md`, `docs/LLM_CONTEXT.md` |
| Bot, scheduler, workers, sources, ingestão, dedupe, matching e sender | Coberto | `docs/ARCHITECTURE.md` |
| Leilões em piloto controlado | Coberto | `README.md`, `docs/AUCTION_RUNTIME.md`, `docs/ARCHITECTURE.md` |
| Source health, backoff e diagnóstico admin | Coberto | `docs/ARCHITECTURE.md`, `docs/OPERATIONS_RUNBOOK.md` |
| Roadmap de produto e tecnologia | Coberto | `docs/ROADMAP.md` |
| Plano de lançamento | Coberto | `docs/LAUNCH_PLAN.md` |
| Backup/restore | Coberto | `docs/BACKUP_RESTORE.md` |
| Contexto para LLMs/agentes | Coberto | `AGENTS.md`, `docs/LLM_CONTEXT.md`, `docs/AI_SKILLS.md` |
| Inventário de legado | Coberto | `docs/LEGACY_INVENTORY.md` |
| Migração V1/V2 de sources | Coberto | `docs/V1_TO_V2_MIGRATION.md` |
| Variáveis de ambiente e configuração operacional | Agora coberto | `docs/ENVIRONMENT.md` |
| Limitações conhecidas para beta aberto | Agora coberto | `docs/KNOWN_LIMITATIONS.md` |

## 3. Prontidão atual por frente

| Frente | Prontidão | Observação |
|---|---:|---|
| Produto Telegram-first | Alta para beta | `/start`, `/menu`, busca, wishlist, tracking, plano e upgrade já são tratados como jornada principal. |
| Runtime técnico | Média/alta | Scheduler, filas, workers, source execution, dedupe, matching e sender já existem, mas precisam de validação de carga antes de abertura maior. |
| Observabilidade admin | Alta para beta técnico | Existem health/source diagnostics/admin metrics, mas a operação de beta precisa rotina disciplinada. |
| Fontes tradicionais | Média | Algumas fontes são úteis; outras têm bloqueios ou papel despriorizado. Não prometer cobertura ampla sem evidência. |
| Leilões | Controlada | Deve continuar em piloto, com gates e comunicação obrigatória de que lance não é preço final. |
| Pagamento Premium | Baixa para público amplo | O fluxo ainda depende de webhook Mercado Pago ou aprovação admin em 1 clique para não virar gargalo. |
| Carga/infra barata | Pendente | Falta teste controlado com 30–50 usuários/50 wishlists ativas por 24h. |
| Jurídico/comunicação | Pendente | Falta política simples de privacidade, termos mínimos e copy pública honesta sobre fontes e scraping. |

## 4. Bloqueadores antes de abertura pública ampla

### P0 — não abrir público amplo sem resolver

1. **Pagamento/ativação Premium sem operação manual frágil**
   - Caminho ideal: Mercado Pago webhook.
   - Fallback aceitável para beta: comprovante no Telegram + aprovação admin em 1 clique.

2. **Teste de carga mínimo**
   - Simular 30–50 usuários com buscas ativas por 24h.
   - Verificar RAM, CPU, `scrape_jobs`, sender, browser/processos e crescimento de disco.

3. **Política simples de privacidade e termos mínimos**
   - Explicar quais dados são guardados: chat_id, username quando disponível, buscas, filtros, interações operacionais e dados de assinatura.
   - Explicar que fontes externas podem mudar, bloquear ou remover anúncios.
   - Explicar que o bot não garante compra, reserva, disponibilidade ou preço final.

### P1 — resolver antes de crescimento

1. **Copy pública honesta de cobertura**
   - Evitar prometer “monitoramos todos os grandes portais”.
   - Preferir: “monitoramos fontes automotivas em expansão; cobertura pode variar por modelo, cidade e fonte”.

2. **Rotina operacional de beta**
   - Acompanhar usuários que entraram, criaram busca, receberam alerta, rastrearam anúncio, bateram limite ou pediram upgrade.

3. **Fixtures/testes por source principal**
   - Reduzir regressões silenciosas de scraping/parsing.

4. **Segurança admin**
   - Garantir que comandos sensíveis só respondem ao admin autorizado.

## 5. Checklist de beta aberto controlado

Antes de convidar usuários fora do círculo próximo:

- [ ] `.env` revisado contra `docs/ENVIRONMENT.md`.
- [ ] Banco com migrations aplicadas e `alembic heads` sem conflito.
- [ ] `source_configs` conferido para fontes user-facing.
- [ ] Sources experimentais/despriorizadas fora da promessa pública.
- [ ] `/start`, `/menu`, `/buscar`, criação de busca, tracking, `/plan` e `/upgrade` testados ponta a ponta.
- [ ] `/admin health`, `/admin sources` e `/admin metrics` funcionando no chat admin.
- [ ] Sender drenando notificações sem atraso crescente.
- [ ] Limite diário de alertas validado.
- [ ] Backup/restore validado pelo menos uma vez.
- [ ] Teste de carga curto executado e registrado.
- [ ] Política de privacidade e termos mínimos publicados ou enviados no onboarding.
- [ ] Copy pública alinhada com as limitações reais.

## 6. Prompt curto para Claude/Codex usar este material

```text
Leia primeiro:
- README.md
- AGENTS.md
- docs/README.md
- docs/LLM_CONTEXT.md
- docs/ARCHITECTURE.md
- docs/USER_FLOWS.md
- docs/LAUNCH_PLAN.md
- docs/ROADMAP.md
- docs/OPEN_BETA_READINESS.md
- docs/ENVIRONMENT.md
- docs/KNOWN_LIMITATIONS.md

Objetivo: avaliar se o Garagem Alvo/AutoHunter está pronto para beta aberto controlado.

Não reescreva arquitetura. Priorize P0/P1 de lançamento:
1. pagamento/ativação Premium;
2. teste de carga;
3. segurança admin;
4. docs de privacidade/termos;
5. validação de fluxo Telegram ponta a ponta;
6. fontes user-facing e comunicação honesta de cobertura.

Classifique qualquer achado como P0, P1, P2 ou P3 e proponha mudanças pequenas, testáveis e reversíveis.
```
