# Garagem Alvo / AutoHunter — Guia de contexto para LLMs

Atualizado em: 2026-05-22.

Este documento existe para orientar qualquer LLM, agente ou pessoa técnica que precise entender o projeto sem depender de memória informal de conversas anteriores.

## 1. Identidade do projeto

- **Garagem Alvo** é a marca pública.
- **AutoHunter** é o nome técnico do runtime, repositório e código interno.
- O produto é **Telegram-first**.
- O público principal são entusiastas automotivos buscando oportunidades específicas: carros especiais, versões raras, configurações desejadas, boas bases de projeto e, em piloto controlado, oportunidades de leilão.

O projeto não é marketplace, loja, concessionária, dashboard web-first ou scraper genérico.

## 2. Fonte de verdade

Ordem de confiança:

1. Código atual e migrations.
2. Estado operacional em banco: `source_configs`, `source_states` e `AppKV`.
3. Docs vivos: `README.md`, `AGENTS.md`, `docs/USER_FLOWS.md`, `docs/PROJECT_GUIDELINE.md`, `docs/ARCHITECTURE.md`, `docs/AUCTION_RUNTIME.md`, `docs/OPERATIONS_RUNBOOK.md`.
4. Runbooks e inventários específicos.
5. Documentos históricos somente como contexto.

Quando houver divergência, o código atual vence. Para operação efetiva de sources, o banco vence defaults: `source_configs`, `source_states` e `AppKV` determinam o estado real.

## 3. Modelo mental obrigatório

Classificados:

```text
wishlist -> scheduler tick -> scrape_jobs -> worker http/browser -> scrape -> normalize -> ingest -> dedupe -> matching -> notifications -> Telegram sender
```

Leilões:

```text
wishlist include_auctions -> auction_lots -> source_configs/user_eligible/categorias -> matching/gates -> dry-run/samples/preview -> envio controlado
```

Jornada de usuário:

```text
/start ou /menu -> criar busca -> filtros/revisão -> monitoramento recorrente -> alerta -> abrir anúncio ou rastrear -> plano/upgrade se bater limite
```

A API/FastAPI é auxiliar. Não trate `/listings` ou `/admin/health` como jornada principal do produto.

## 4. Principais diretórios

- `app/bot/`: bot Telegram, handlers, renderers, comandos, UX pública/admin.
- `app/scheduler/`: APScheduler, ticks, filas, workers, sender, monitor, digest e jobs auxiliares.
- `app/services/`: regras de negócio e coordenação operacional.
- `app/sources/`: plugins e registry de sources tradicionais.
- `app/sources/auctions/`: sources/parsers de leilão.
- `app/scrapers/`: scrapers tradicionais, v2/unified e bridges legadas.
- `app/models/`: modelos SQLAlchemy.
- `alembic/`: migrations. Deve ter head único.
- `docs/`: documentação viva e histórica.
- `config/raspberry-pi/`: operação/deploy em Raspberry Pi.
- `tests/`: contratos de regressão e validação.

## 5. Arquivos que um LLM deve ler primeiro

1. `README.md`
2. `AGENTS.md`
3. `docs/USER_FLOWS.md`
4. `docs/PROJECT_GUIDELINE.md`
5. `docs/ARCHITECTURE.md`
6. `docs/AUCTION_RUNTIME.md`
7. `docs/OPERATIONS_RUNBOOK.md`
8. `docs/LEGACY_INVENTORY.md`
9. Código central:
   - `app/bot/run.py`
   - `app/bot/handlers_core.py`
   - `app/bot/handlers.py`
   - `app/scheduler/run.py`
   - `app/services/source_execution_service.py`
   - `app/sources/builtins.py`
   - `app/services/auction_source_config_service.py`
   - `app/sources/auctions/registry.py`

## 6. Decisões já tomadas

- Telegram é a superfície principal.
- FastAPI é auxiliar/operacional/integrativa.
- Garagem Alvo é a marca pública; AutoHunter permanece como runtime interno.
- Configuração de sources é DB-driven.
- `.env` é fallback/kill switch/bootstrap, não painel operacional.
- Não fazer big-bang rewrite.
- Não remover legado sem validação concreta.
- Não aumentar agressivamente browser/Playwright; o runtime deve respeitar Raspberry Pi 4 4GB.
- Leilões estão em piloto controlado, com `VIP Leilões` como caminho user-facing principal e sources experimentais fora do usuário final.
- Leilão precisa sempre deixar claro: lance não é preço final.
- WebMotors está tecnicamente implementada, mas despriorizada operacionalmente por bloqueio anti-bot/fingerprint.
- V1/V2 de scrapers é trilha técnica incremental, não flip global.

## 7. Estado funcional atual, em alto nível

Já existem:

- bot Telegram com comandos públicos e admin;
- `/start` e `/menu` com UX guiada;
- criação/listagem/gestão de buscas/wishlists;
- filtros implícitos e guiados por busca;
- busca manual/pontual (`/buscar` e menu);
- tracking de até 3 slots por wishlist, respeitando limites de plano;
- alertas de queda de preço/status quando permitido por plano/settings;
- plano Free/Premium com limites, `/plan`, `/upgrade` e ativação operacional/admin;
- scheduler recorrente;
- fila persistente `scrape_jobs`;
- workers HTTP/browser;
- source execution service com backoff e telemetry;
- dedupe, matching e fila de notificações;
- sender Telegram;
- source health/admin diagnostics;
- fontes tradicionais via plugins;
- v1/v2/dual-run de sources em trilha técnica;
- frente de leilões com opt-in por busca, sources controladas, dry-run, samples, readiness, digest e piloto manual controlado;
- backup/restore mínimo documentado;
- digest semanal básico.

## 8. Pontos sensíveis

### `source_execution_service.py`

É o coração da execução de classificados. Evite refactor grande. Qualquer alteração deve preservar:

- DB-driven configs;
- backoff;
- source_runs;
- telemetry;
- health classification;
- ingest/matching/notificação;
- activity reconciliation.

### Bot/UX

- Fluxo guiado é preferencial.
- Comandos legados continuam úteis para usuários técnicos e compatibilidade.
- Não capturar callbacks de ConversationHandler com handlers globais.
- Não colocar regra de negócio pesada nos handlers.

### v1/v2/dual-run

Caminhos de adapter v1/v2/dual ainda existem por compatibilidade/migração. Não remover sem evidência. `impl=dual` é configuração persistida em `source_configs.extra`, não flag de `/admin runall`.

### Leilões

Preserve todos os gates:

- opt-in por wishlist;
- source enabled;
- source user_eligible;
- categoria permitida;
- item_type permitido;
- bid disponível;
- score mínimo;
- lote recente;
- dedupe;
- limite diário;
- dry-run como default seguro.

### Facebook Agent/Auth

É integração auxiliar/sensível. Não transformar em core do produto sem decisão explícita. Não remover rotas ou jobs sem medir uso.

### Docs históricos

Podem conter decisões antigas. Não use documentos históricos como fonte de verdade quando divergirem dos docs vivos/código.

## 9. Lacunas atuais importantes

- Billing automático com Mercado Pago/webhook ou aprovação manual em 1 clique.
- `/admin metrics` de produto/comercial.
- Teste de carga mínimo para beta/lançamento.
- Digest semanal mais explicativo quando não houve alerta.
- Operação de beta/founders/growth ainda é frente de lançamento, não núcleo técnico.

## 10. Como classificar recomendações

Ao avaliar o projeto, classifique achados como:

- **Bug real**: comportamento quebrado ou teste falhando.
- **Risco operacional**: algo que pode quebrar produção, gerar ruído, travar fila, consumir disco ou expor usuário indevidamente.
- **Melhoria técnica**: refactor, simplificação ou cobertura de teste sem mudança de produto.
- **Melhoria de produto**: evolução de UX, plano, notificações, fontes ou jornada.
- **Obsolescência provável**: código/doc aparentemente antigo, mas ainda dependente de validação antes de remoção.

## 11. O que não fazer

- Não tratar documentação histórica como verdade atual.
- Não apagar docs/arquivos sem separar histórico vs legado usado.
- Não migrar o produto para web-first.
- Não expor sources técnicas na UX final sem necessidade.
- Não liberar sources experimentais de leilão para usuários finais sem gates.
- Não ativar envio automático real de leilões via scheduler sem PR específica.
- Não inventar valores de leilão: `initial_bid` não é `current_bid`; lance não é preço final.
- Não ignorar limites de Raspberry Pi.
- Não propor arquitetura distribuída pesada sem evidência de gargalo real.
- Não declarar WebMotors como saudável/produção sem evidência real contra PerimeterX.

## 12. Checklist antes de qualquer PR

- Li `AGENTS.md`, `docs/USER_FLOWS.md` e `docs/ARCHITECTURE.md`?
- Identifiquei se a mudança afeta bot, scheduler, source, DB, notificação ou leilão?
- Preservei compatibilidade de comandos existentes?
- A regra de negócio ficou fora do handler?
- A mudança respeita `source_configs`/`source_states`/`AppKV`?
- Há teste específico para o comportamento alterado?
- Rodei ao menos testes focados e `alembic heads` se houver schema/migration?
- Atualizei docs vivos quando o modelo mental mudou?

## 13. Prompt recomendado para novo chat/LLM

Use este contexto ao abrir um novo chat:

```text
Você está avaliando o projeto AutoHunter, runtime interno da marca pública Garagem Alvo.
O produto é Telegram-first para monitoramento recorrente de oportunidades automotivas.
A API FastAPI é auxiliar, não a jornada principal.
Use o código atual como fonte de verdade.
Leia primeiro README.md, AGENTS.md, docs/USER_FLOWS.md, docs/PROJECT_GUIDELINE.md, docs/ARCHITECTURE.md, docs/AUCTION_RUNTIME.md, docs/OPERATIONS_RUNBOOK.md e docs/LEGACY_INVENTORY.md.

Fluxo classificados:
wishlist -> scheduler tick -> scrape_jobs -> workers http/browser -> scrape+normalização+ingestão -> dedupe -> matching -> notifications -> sender Telegram.

Fluxo usuário:
/start ou /menu -> criar busca -> revisar filtros/leilões -> monitoramento -> alerta -> abrir anúncio ou rastrear -> plano/upgrade conforme limite.

Fluxo leilões:
wishlist include_auctions -> auction_lots -> source_configs/user_eligible/categorias -> matching/gates -> dry-run/samples/preview -> envio controlado.

Restrições:
- não fazer big-bang rewrite;
- não remover legado sem validação;
- preservar operação em Raspberry Pi 4 4GB;
- manter regra de negócio fora de handlers;
- tratar source_configs/source_states/AppKV como fonte operacional;
- manter leilões em piloto controlado e dry-run seguro;
- diferenciar bug, risco operacional, melhoria técnica, melhoria de produto e obsolescência provável.

Entregue diagnóstico incremental, com evidências em arquivos, riscos, próximos passos e comandos de validação.
```