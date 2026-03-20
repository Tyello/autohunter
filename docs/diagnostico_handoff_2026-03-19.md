# AutoHunter — Diagnóstico estratégico/técnico (estado real do código)

Data: 2026-03-19

## Parte A — Diagnóstico estruturado

### 1) O que é o AutoHunter hoje

- **Objetivo real atual**: monitorar anúncios de carros em múltiplas fontes e notificar usuários no Telegram quando anúncios compatíveis com suas wishlists aparecem, com dedupe e controle de envio.  
- **Não é apenas busca manual**: o core é recorrente (scheduler + filas de scrape + fila de notificação) e já possui camadas operacionais de observabilidade, backoff e administração.  
- **Produto em operação**: há fluxos explícitos de admin, monitoramento, preflight de deploy e jobs de manutenção/digest.

### 2) Como funciona hoje (ponta a ponta)

1. **Entrada do usuário** via Telegram (`/start`, `/wishlist`, `/buscar`, etc.).  
2. **Criação de wishlist**: persiste wishlist + filtros derivados da query (ano/preço), reconstrói tokens de matching e dispara **execução inicial imediata** nas fontes permitidas para aquela wishlist.  
3. **Scheduler APScheduler** executa ticks curtos por fonte; cada tick decide se a fonte está habilitada, due, sem backoff e então enfileira job HTTP ou Browser em `scrape_jobs`.  
4. **Workers de fila** (`http_queue_worker`, `browser_queue_worker`) retiram jobs e executam `run_source_for_all_wishlists`.  
5. **Execução por source**: obtém wishlists elegíveis, agrupa por URL, faz scrape (v1/v2/dual), normaliza/adapta para listing, ingere com dedupe e faz matching contra o conjunto atual raspado.  
6. **Notificações**: matching enfileira notificações com dedupe por `(wishlist_id, car_listing_id)`; sender processa pendências com limite diário por usuário, retry/discard e marcação de status.  
7. **Digests semanais**: job semanal compõe resumo por usuário com base em atividade/listings ativos e envia em chunks no Telegram.  
8. **Admin/observabilidade**: logs estruturados, telemetry_events, source_runs, monitor/admin alerts, autopilot de regressão e comandos admin para tunar `source_configs`.

### 3) Público e canal

- **Canal principal**: Telegram (entrada, gestão, notificação e operação/admin).  
- **Público provável atual**: B2C nichado/power users que monitoram mercado de usados de forma contínua e aceitam interface conversacional por comandos.  
- **Perfil secundário explícito**: operador/admin técnico do bot (há comandos e serviço de deploy/admin monitor dedicados).  
- **API Web existe**, mas é superfície auxiliar (health/listings e integração FB Agent), não a jornada principal do produto.

### 4) Correções prioritárias (ainda fazem sentido)

#### P0 — Alta severidade

1. **Desalinhamento entre documentação e runtime atual de fontes**: README ainda descreve subconjunto antigo de fontes, enquanto registry possui conjunto maior (incluindo browser-first e Facebook Marketplace). Isso induz operação/config incorreta.  
2. **Função legada aparentemente fora do fluxo principal** (`queue_notifications_for_new_listings`) permanece no módulo core de jobs e é coberta por testes, mas não é usada no runner oficial atual (matching no result-set atual). Risco de confusão e regressão por manutenção em caminho morto.

#### P1 — Média severidade

3. **Acoplamento de responsabilidades em `source_execution_service`**: esse serviço concentra elegibilidade, scrape dispatch v1/v2/dual, ingestão, matching, health classification, telemetry e controle de estado; manutenção e teste ficam caros.  
4. **Inconsistência de superfície de API/documentação**: `app/main.py` está minimalista e não representa capacidades operacionais reais do sistema, o que pode gerar expectativa errada para integrações externas.

#### P2 — Baixa severidade

5. **Arquivos/configs de Raspberry Pi aparentemente redundantes/legados** (`config/rpi_config.py` e `config/raspberry_pi_config.py`) sem evidência de uso no runtime principal; aumentam ruído cognitivo.

### 5) Melhorias e oportunidades reais

#### Produto

- **Consolidar UX Telegram**: há comandos “modo antigo” e “UX nova” convivendo; oportunidade é simplificar jornada e reduzir comandos sobrepostos sem quebrar compatibilidade.  
- **Explorar diferenciação por inteligência de oferta** com o que já existe (score, market stats, digest semanal, atividade por wishlist), priorizando explicabilidade no texto enviado.

#### Operacional

- **Padronizar documentação operacional em torno de `source_configs` DB-driven** (o código já é DB-driven; documentação ainda mistura eras).  
- **Painel admin enxuto** (mesmo que só via Telegram/API interna) focado em: staleness, backoff ativo, queue depth, falhas por source, tempo desde último sucesso.

#### Técnica

- **Refatoração incremental do runner por source** em sub-etapas (eligibilidade, scrape/adapt, ingest, match, post-run), preservando contratos atuais.  
- **Remoção guiada de código legado** com feature flags e testes de contrato para reduzir caminhos mortos.  
- **Fortalecer fronteira de domínio** entre bot handlers e serviços (handlers ainda carregam parte de orquestração/formatação).

#### Simplificação

- **Reduzir artefatos “PATCH_V*” e docs históricos dispersos** em favor de uma trilha viva curta (arquitetura atual + runbook + troubleshooting).

### 6) Código morto/obsoleto/suspeito

#### Provavelmente morto

- `app/scheduler/jobs.py::queue_notifications_for_new_listings` — sem chamadas no pipeline atual (aparece apenas em testes).  
- `config/rpi_config.py` — sem referências fora do próprio arquivo.  

#### Suspeito de obsolescência

- `config/raspberry_pi_config.py` — parece guia estático antigo, sem evidência de integração no runtime.  
- Documentos `docs/PATCH_V*.md` — parecem registro histórico de patches; úteis para contexto, mas não para operação corrente.

#### Não remover sem confirmar uso

- `fb_agent/*` top-level: apesar de parecer separado, existe integração direta com rotas/websocket e fluxo de pairing no app principal.  
- Scripts de debug/teste em `scripts/`: vários parecem utilitários operacionais pontuais; remover sem inventário pode quebrar runbooks internos.

### 7) Definições pendentes/ambíguas

1. **Posicionamento de produto**: o código mostra forte foco Telegram+B2C, mas também traz elementos de operação técnica avançada (admin deploy, autopilot, FB agent). Falta uma definição explícita de “produto para usuário final” vs “plataforma operável por time técnico”.  
2. **Fronteira entre caminhos legados e oficiais**: coexistem fluxos antigos e novos (comandos, serviços e docs), sem “depreciação oficial” consolidada.  
3. **Escopo da API pública**: FastAPI atual é mínima e não espelha o core; não está claro se API será apenas health/admin interno ou superfície de produto.  
4. **Política de fonte ativa por ambiente**: registry amplo vs defaults/settings/README não completamente alinhados (risco de ambiguidade de rollout).  
5. **Governança de documentação**: muito material histórico útil, mas sem curadoria clara do que é “fonte de verdade vigente”.

### 8) Top 5 prioridades recomendadas

1. **Alinhar documentação oficial ao runtime atual** (fontes, fluxo, operação DB-driven).  
2. **Marcar e tratar explicitamente caminhos legados** (deprecate/remove por etapas, começando por função de fila de notificações não usada no runner principal).  
3. **Extrair submódulos do `source_execution_service`** mantendo comportamento e testes atuais.  
4. **Definir posicionamento de superfície**: Telegram-first oficialmente + papel explícito da API.  
5. **Criar runbook curto de operação** (alertas/admin, backoff, filas, staleness, recovery), apontando para poucas páginas vivas.

---

## Parte B — Prompt pronto para novo chat

```text
Você está assumindo o projeto AutoHunter já em operação.

Contexto confiável (baseado no código atual):
- AutoHunter é um bot/plataforma Telegram para monitorar anúncios de carros usados em múltiplas fontes, com scheduler recorrente, ingestão normalizada, matching por wishlist e envio de notificações.
- O fluxo principal é Telegram-first (comandos de busca/wishlist, alertas e operação admin), não web-first.
- O scheduler roda ticks por source, enfileira jobs em scrape_jobs (HTTP/Browser), workers executam scraping por source, fazem ingest+dedupe, matching e enfileiram notificações.
- Existe sender com controle de limite diário, retries e status de entrega.
- Existe digest semanal de wishlist (job dedicado) e camada de observabilidade/admin (system logs, telemetry, source runs, monitor/autopilot e comandos admin).
- API FastAPI existe, mas é superfície auxiliar (health/listings e integração FB Agent), não a jornada central do usuário final.

Objetivo atual do projeto:
- Maximizar qualidade e confiabilidade da descoberta de oportunidades de compra (usados), com alertas úteis e operação estável de scraping multi-source.

Público/canal provável hoje:
- Usuário final B2C nichado/power user de usados automotivos, atendido principalmente no Telegram.
- Operador/admin técnico também é público real do produto (há fluxos dedicados).

Pontos fortes atuais:
- Pipeline ponta a ponta já consolidado (wishlist -> scrape -> ingest -> match -> notify).
- Arquitetura por plugins de source + source_configs DB-driven.
- Observabilidade operacional e controles de backoff/fila/admin acima do nível “MVP cru”.
- Cobertura de testes robusta incluindo contratos e regressão por source.

Pendências/riscos relevantes:
- Documentação oficial parcialmente desalinhada do runtime atual (fontes e operação).
- Presença de caminhos legados e artefatos possivelmente obsoletos (ex.: função antiga de queue notificação ainda no módulo principal, configs RPi duplicadas/sem uso evidente).
- Serviço de execução por source está denso e com muitas responsabilidades.
- Posicionamento de produto/superfície (Telegram vs API/plataforma) ainda pouco explícito.

Diretriz de trabalho para este chat:
- Não reescrever arquitetura inteira.
- Trabalhar incrementalmente, com baixo acoplamento e compatibilidade com pipeline atual.
- Tratar o código atual como fonte de verdade.
- Ao propor mudanças, separar claramente: bug real, risco operacional, melhoria técnica e melhoria de produto.
- Onde houver incerteza, explicitar e sugerir validação objetiva.

Próximos passos inteligentes sugeridos:
1) Atualizar documentação de runtime (fontes ativas, fluxos e runbook curto).
2) Inventariar/etiquetar caminhos legados com plano de depreciação seguro.
3) Refatorar source_execution_service por etapas sem mudar contrato externo.
4) Definir oficialmente o papel da API (interna vs produto).
5) Melhorar UX Telegram reduzindo sobreposição de comandos antigos/novos.
```

## Evidências usadas (arquivos-chave)

- Entradas e canal Telegram: `app/bot/run.py`, `app/bot/commands.py`, `app/bot/handlers.py`, `app/bot/handlers_core.py`.  
- Scheduler e filas: `app/scheduler/run.py`, `app/scheduler/http_queue_job.py`, `app/scheduler/browser_queue_job.py`, `app/services/scrape_jobs_service.py`.  
- Pipeline por source: `app/services/source_execution_service.py`, `app/scheduler/jobs.py`.  
- Wishlists e execução inicial imediata: `app/services/wishlists_service.py`.  
- Registry/fontes: `app/sources/builtins.py`, `app/sources/registry.py`, `app/sources/types.py`.  
- Notificações e limites: `app/scheduler/jobs_send.py`.  
- Digest semanal: `app/services/weekly_wishlist_digest_service.py`, `app/scheduler/weekly_wishlist_digest_job.py`.  
- Admin deploy: `app/services/admin_deploy_service.py`.  
- API e superfície web auxiliar: `app/main.py`.  
- Itens suspeitos de obsolescência: `config/rpi_config.py`, `config/raspberry_pi_config.py`.
