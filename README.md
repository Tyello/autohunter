# Garagem Alvo

Garagem Alvo é a marca pública do produto. AutoHunter é o nome interno/técnico do runtime e deste repositório.

Garagem Alvo é uma plataforma **Telegram-first** para entusiastas monitorarem oportunidades automotivas: anúncios tradicionais, carros especiais, versões raras, boas bases de projeto e, no piloto atual, oportunidades em leilão com opt-in por busca.

> Produto principal hoje: bot no Telegram + runtime contínuo (scheduler, filas, workers, matching e envio de notificações).
>
> A API FastAPI existe como superfície **auxiliar/operacional/integrativa** (healthchecks, listagem simples e fluxos auxiliares), não como jornada principal do usuário final.

## Estado atual em uma frase

O produto já opera como bot Telegram com criação/gestão de buscas, filtros, busca manual, tracking de anúncios, alertas, planos Free/Premium, source health/admin, scheduler com filas persistentes e piloto controlado de leilões. O próximo bloco crítico para lançamento público é menos “fazer o produto existir” e mais **fechar operação comercial, métricas, validação de carga e clareza de lançamento**.

## O que o produto é hoje

- Usuário final cria e gerencia buscas/wishlists pelo Telegram.
- O sistema roda continuamente para monitorar fontes e encontrar oportunidades novas.
- Listings tradicionais são normalizados, deduplicados, avaliados por matching e enviados por Telegram.
- Usuário pode fazer busca pontual em `/buscar` ou pelo menu, sem salvar monitoramento.
- Usuário pode rastrear anúncios específicos vinculados às buscas e acompanhar preço/status.
- Leilões existem em piloto controlado: o usuário escolhe por busca se aceita leilões, mas sources, categorias, scheduler e limites são controlados por admin.
- Há trilha operacional: source configs, backoff, monitoramento admin, health, readiness, samples, digest, backup/restore e auditoria.

Fluxo resumido (classified runtime):

`wishlist -> scheduler tick -> scrape_jobs -> workers http/browser -> scrape+normalização+ingestão -> dedupe -> matching -> notifications -> sender Telegram`

Fluxo resumido (auction runtime):

`wishlist com include_auctions -> auction_lots -> source_configs + categorias -> matching -> gates de notificação -> dry-run/samples -> notify controlado`

## Superfícies do sistema

- **Principal (produto):** Telegram (`app/bot/`).
- **Núcleo operacional:** scheduler + workers + serviços (`app/scheduler/`, `app/services/`).
- **Sources tradicionais:** plugins em `app/sources/` e scrapers/adapters relacionados.
- **Sources de leilão:** registry técnico em `app/sources/auctions/` e dados em `auction_lots`.
- **Auxiliar:** API FastAPI (`app/main.py`, `app/web/`).

## Fluxos principais do usuário

Resumo curto:

1. `/start` ou `/menu` para entrar no bot.
2. `➕ Criar busca` para informar o carro, revisar filtros e ativar monitoramento.
3. `🎯 Minhas buscas` para pausar, reativar, remover ou ajustar filtros.
4. `🔎 Buscar agora` ou `/buscar` para uma busca pontual sem salvar.
5. `⭐ Rastrear` em um anúncio para acompanhar preço/status.
6. `/plan` e `/upgrade` para ver limites e iniciar upgrade.
7. Opt-in de leilões por busca, com aviso obrigatório de que lance não é preço final.

Fluxos detalhados: [`docs/USER_FLOWS.md`](docs/USER_FLOWS.md).

## Configuração operacional

O estado efetivo de operação é runtime/DB-driven:

- `source_configs`: habilita/desabilita sources, cadência, backoff, proxy/browser flags, `source_type`, `user_eligible`, `status` e `extra`.
- `source_states`: saúde/backoff/últimos estados das sources tradicionais.
- `AppKV`: configurações runtime de notificações de leilão e amostras de dry-run.
- `.env`: fallback seguro, bootstrapping e kill switches; não deve ser a única superfície operacional para knobs de produto.

## Leilões no estado atual

- Usuário final decide apenas **se aceita leilões por busca** (`include_auctions=true|false`).
- Admin decide quais sources de leilão são elegíveis e quais categorias podem chegar ao usuário.
- No piloto, apenas `car` fica permitido por padrão; motos, caminhões/pesados, imóveis e outros ficam bloqueados para notificação.
- Notificações automáticas reais de leilão continuam protegidas: `dry_run=false` não é liberado via comando admin nesta fase.
- O caminho operacional recomendado é validar com `/admin auctions readiness`, `/admin auctions notify-status` e `/admin auctions notify-samples`.

## Situação comercial atual

- Planos Free/Premium existem no produto.
- `/plan` mostra uso e limites.
- `/upgrade` apresenta oferta Premium e links configuráveis do Mercado Pago.
- A ativação Premium ainda é operacional/manual pelo admin após validação de pagamento/comprovante.
- Para lançamento público, o principal bloqueador comercial é automatizar pagamento via webhook ou criar aprovação manual de 1 clique no Telegram.

## Leitura recomendada

- [`AGENTS.md`](AGENTS.md) — mapa mental curto para pessoas técnicas e IAs.
- [`docs/LLM_CONTEXT.md`](docs/LLM_CONTEXT.md) — guia de contexto para qualquer LLM entender o projeto sem memória informal.
- [`docs/USER_FLOWS.md`](docs/USER_FLOWS.md) — fluxos atuais de usuário, admin e produto.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — documentação da arquitetura atual, camadas, fluxos e contratos operacionais.
- [`docs/PROJECT_GUIDELINE.md`](docs/PROJECT_GUIDELINE.md) — documentação viva do runtime atual.
- [`docs/AUCTION_RUNTIME.md`](docs/AUCTION_RUNTIME.md) — guia operacional específico de leilões.
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md) — runbook operacional curto.
- [`docs/DOCUMENTATION_AUDIT.md`](docs/DOCUMENTATION_AUDIT.md) — auditoria de docs vivos, históricos e candidatos a arquivamento/remoção.
- [`docs/LEGACY_INVENTORY.md`](docs/LEGACY_INVENTORY.md) — inventário de legado/compatibilidade e risco de remoção.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — roadmap oficial consolidado do produto e prioridades de execução.
- [`docs/LAUNCH_PLAN.md`](docs/LAUNCH_PLAN.md) — plano de lançamento e lacunas de go-to-market.
- [`docs/BACKUP_RESTORE.md`](docs/BACKUP_RESTORE.md) — backup/restore operacional mínimo.
