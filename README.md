# Garagem Alvo

Garagem Alvo é a marca pública do produto. AutoHunter é o nome interno/técnico do runtime e deste repositório.

Garagem Alvo é uma plataforma **Telegram-first** para entusiastas monitorarem oportunidades automotivas: anúncios tradicionais, carros especiais, versões raras, boas bases de projeto e, no piloto atual, oportunidades em leilão com opt-in por busca.

> Produto principal hoje: bot no Telegram + runtime contínuo (scheduler, filas, workers, matching e envio de notificações).
>
> A API FastAPI existe como superfície **auxiliar/operacional/integrativa** (healthchecks, listagem simples e fluxos auxiliares), não como jornada principal do usuário final.

## O que o produto é hoje

- Usuário final cria e gerencia buscas/wishlists pelo Telegram.
- O sistema roda continuamente para monitorar fontes e encontrar oportunidades novas.
- Listings tradicionais são normalizados, deduplicados, avaliados por matching e enviados por Telegram.
- Leilões existem em piloto controlado: o usuário escolhe por busca se aceita leilões, mas sources, categorias, scheduler e limites são controlados por admin.
- Há trilha operacional: source configs, backoff, monitoramento admin, health, readiness, samples e digest.

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

## Leitura recomendada

- [`AGENTS.md`](AGENTS.md) — mapa mental curto para pessoas técnicas e IAs.
- [`docs/LLM_CONTEXT.md`](docs/LLM_CONTEXT.md) — guia de contexto para qualquer LLM entender o projeto sem memória informal.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — documentação da arquitetura atual, camadas, fluxos e contratos operacionais.
- [`docs/PROJECT_GUIDELINE.md`](docs/PROJECT_GUIDELINE.md) — documentação viva do runtime atual.
- [`docs/AUCTION_RUNTIME.md`](docs/AUCTION_RUNTIME.md) — guia operacional específico de leilões.
- [`docs/OPERATIONS_RUNBOOK.md`](docs/OPERATIONS_RUNBOOK.md) — runbook operacional curto.
- [`docs/DOCUMENTATION_AUDIT.md`](docs/DOCUMENTATION_AUDIT.md) — auditoria de docs vivos, históricos e candidatos a arquivamento/remoção.
- [`docs/LEGACY_INVENTORY.md`](docs/LEGACY_INVENTORY.md) — inventário de legado/compatibilidade e risco de remoção.
- [`docs/BACKUP_RESTORE.md`](docs/BACKUP_RESTORE.md) — backup/restore operacional mínimo.
