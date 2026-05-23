# AutoHunter / Garagem Alvo — Roadmap

Atualizado em: 2026-05-22

## 1. Visão do produto

AutoHunter / Garagem Alvo é um bot Telegram-first para monitoramento inteligente de anúncios de carros usados, focado em público entusiasta automotivo.

Não é marketplace genérico.
Não é loja.
Não é concessionária.
Não é dashboard web-first.

O foco é ajudar usuários a encontrar:

- carros especiais;
- versões raras;
- configurações específicas;
- boas bases para projeto;
- carros com potencial de preparação;
- oportunidades interessantes para quem sabe o que procura.

Exemplos de interesse:

- Civic Si;
- Golf GTI;
- Jetta GLI;
- Audi A5;
- Subaru WRX;
- carros manuais;
- carros raros;
- combinações específicas de cor/cidade/versão.

Canal principal:

- Telegram.

Superfícies principais:

- bot para usuário final;
- comandos admin privados;
- notificações de oportunidades.

## 2. Estado atual consolidado

Concluído/estabilizado:

- Score vNext.
- Mensagem vNext.
- Source Health Gate.
- Contract enforcement/qualidade do NormalizedAd.
- Auditoria completa das sources.
- Controle de anúncios inativos cross-source.
- Diagnóstico admin de sources.
- Admin Deploy via Telegram.
- Logotipo/imagem da marca.
- UX guiada com `/start` e `/menu`.
- Criação guiada de wishlist/busca.
- Filtros implícitos e guiados por preço, ano, km, cidade e estado.
- Suporte core para filtros avançados como cor, source, vendedor, carroceria e portas.
- Primeira varredura agendada imediatamente ao criar wishlist.
- Busca manual/pontual com `/buscar` e fluxo conversacional.
- Botão `⭐ Rastrear` em alertas/resultados quando aplicável.
- Tracking de anúncios por wishlist com limite de slots.
- Alertas de queda de preço/status para tracking quando plano/settings permitem.
- `/plan` com uso de limites e `/upgrade` com copy comercial.
- Digest semanal básico.
- Backup/restore mínimo.
- `browser_block_resources` configurável por source.
- Warmup Webmotors mensurável.
- `curl_cffi` experimental para Webmotors.
- Classificação blocked/error corrigida para Webmotors.
- Webmotors formalizada como `operational_role=deprioritized`.
- Sources `deprioritized` fora da saúde crítica global.
- TurboClass habilitada por default como source HTTP/feed experimental.
- Inventário automático V1/V2 de sources.
- Dual-run report inicial para Mercado Livre.

## 3. Decisão operacional — Webmotors

Webmotors está:

- tecnicamente implementada;
- diagnosticável via admin;
- disponível para execução manual;
- despriorizada operacionalmente.

Testes feitos:

- browser direto;
- assets liberados;
- warmup básico;
- warmup com comportamento leve;
- `curl_cffi`;
- classificação blocked/error;
- health global com `operational_role`.

Resultados:

- bloqueio HTTP 200;
- `provider=perimeterx`;
- `Access to this page has been denied`;
- `Pressione e segure`;
- `curl_cffi_fallback_reason=challenge`.

Decisão:

- manter código;
- manter execução manual;
- `default_enabled=false` para seed novo;
- `operational_role=deprioritized`;
- não considerar falha crítica global;
- não priorizar novas tentativas anti-bot agora.

POCs futuras possíveis, mas fora do roadmap imediato:

- Patchright;
- sessão assistida/manual;
- browser persistente não-headless;
- proxy residencial/mobile;
- `storage_state` manual.

## 4. Roadmap priorizado

### P1 — Lançamento: pagamento e ativação Premium sem gargalo manual

**Objetivo:** remover o maior bloqueador comercial antes de beta/público.

**Estado atual:** `/upgrade` e links Mercado Pago existem, mas ativação Premium ainda depende de validação/admin manual.

**Escopo recomendado:**

- Opção principal: Mercado Pago webhook com ativação automática de Premium.
- Fallback aceitável: comprovante no Telegram com botão admin de aprovação em 1 clique.
- Reusar serviço interno de ativação Premium.
- Registrar auditoria e notificar usuário/admin.

**Critério de aceite:**

- usuário paga e Premium é ativado sem digitar comando manual;
- admin consegue auditar evento;
- `/plan` reflete Premium;
- falhas são visíveis e recuperáveis.

### P2 — `/admin metrics` de produto/comercial

**Objetivo:** operar beta e lançamento com números mínimos, sem dashboard web.

**Métricas mínimas:**

- usuários totais e novos nos últimos 7 dias;
- usuários com busca ativa;
- buscas criadas nos últimos 7 dias;
- percentual de usuários que recebeu pelo menos 1 alerta;
- alertas enviados 24h/7d;
- backlog do sender;
- conversão Free → Premium;
- top sources por alertas enviados;
- sinais simples de retenção de 7 dias.

**Critério de aceite:**

- `/admin metrics` responde no Telegram;
- não expõe dados sensíveis desnecessários;
- serve para decisão diária do beta.

### P3 — Teste de carga e prontidão de beta

**Objetivo:** validar o runtime em Raspberry Pi 4 4GB antes de abrir para 30–50 beta users.

**Escopo:**

- simular 50 usuários com wishlist ativa;
- monitorar RAM/CPU/fila/sender;
- verificar se `scrape_jobs` drena;
- verificar atraso máximo do sender;
- verificar Playwright sem processos zumbis;
- documentar resultado.

**Critério de aceite:**

- runbook/script de teste existe;
- resultado documentado;
- gargalos viram tarefas explícitas antes do beta.

### P4 — Digest semanal v2

**Objetivo:** comunicar valor mesmo quando não houve alerta.

**Estado atual:** digest semanal básico existe.

**Escopo:**

- volume monitorado por semana;
- contexto por wishlist;
- anúncios encontrados mas bloqueados por filtro quando possível;
- ausência honesta quando não houve resultado;
- branding público como Garagem Alvo.

**Critério de aceite:**

- usuário entende que o sistema trabalhou;
- digest não inventa dados;
- digest melhora retenção de usuários sem alerta.

### P5 — Operação beta/founders/growth

**Objetivo:** transformar produto funcional em validação real de mercado.

**Escopo:**

- checklist de beta fechado;
- acompanhamento manual dos usuários sem primeiro alerta;
- pacote Founders;
- textos de divulgação;
- rotina de posts com achados;
- parceria pequena em nicho automotivo.

**Critério de aceite:**

- 30–50 beta users acompanháveis;
- 20 Founders possíveis sem operação caótica;
- feedback e conversão medidos.

### P6 — Testes de regressão por source com fixtures reais

**Objetivo:** reduzir regressões de scraping/parsing por mudança de layout.

**Sources prioritárias:**

- Mercado Livre;
- OLX;
- Chaves na Mão;
- iCarros;
- Mobiauto;
- GoGarage se estiver ativa;
- Webmotors apenas como fixture de blocked/challenge.

**Escopo:**

- fixtures sanitizadas;
- testes de parsing;
- testes de normalização;
- testes de imagem/thumb;
- testes de preço, ano, km, cidade/UF.

**Critério de aceite:**

- cada source principal tem fixture;
- parser quebra teste se layout esperado mudar;
- fixtures não contêm dados sensíveis.

### P7 — V1→V2: dual-run e paridade por source

**Objetivo:** migrar tecnicamente sem quebrar ingestão/matching.

**Estado atual:** inventário automático existe e dual-run report inicial suporta Mercado Livre.

**Escopo:**

- expandir dual-run para OLX, iCarros, Chaves na Mão e Mobiauto;
- medir divergência de campos críticos;
- preservar heurísticas do caminho ativo;
- só flipar source após evidência.

**Critério de aceite:**

- relatório mostra paridade aceitável;
- divergências conhecidas viram tarefas;
- nenhuma source crítica muda para v2 sem rollback.

### P8 — Unificação de anúncios equivalentes cross-source

**Objetivo:** avaliar anúncios equivalentes em plataformas diferentes e reduzir duplicidade.

**Escopo inicial:**

- modo diagnóstico;
- score de similaridade;
- normalização de título/preço/ano/km/cidade;
- marcar candidatos equivalentes sem colapsar automaticamente.

**Critério de aceite:**

- candidatos equivalentes são identificados;
- não altera notificações automaticamente na primeira fase;
- evita colapsar anúncios distintos por engano.

### P9 — Histórico de notificação e retenção

**Objetivo:** evitar renotificação indevida e controlar crescimento de histórico.

**Escopo:**

- revisar retenção de `car_listings`;
- avaliar `notification_history` enxuto;
- garantir estado de anúncio inativo;
- tratar anúncio reaparecido.

**Critério de aceite:**

- usuário não recebe repetição indevida;
- histórico não cresce sem controle;
- anúncios inativos têm estado claro.

### P10 — Admin UX incremental

**Objetivo:** reduzir dependência de SQL/log no Raspberry.

**Ideias:**

- `/admin source <nome> explain`;
- `/admin source <nome> last`;
- `/admin source <nome> config`;
- `/admin health` mais executivo;
- `/admin runall` com ação recomendada;
- exibição mais compacta de role, health e backoff.

**Critério de aceite:**

- admin entende causa/impacto/próximo passo pelo Telegram;
- mensagens não ficam longas demais;
- não expõe segredos.

### P11 — Segurança admin

**Objetivo:** garantir que somente o chat admin autorizado tenha acesso a comandos administrativos.

**Escopo:**

- revisar gate de admin chat;
- testar comandos sensíveis;
- garantir deploy/restart/source config protegidos.

**Critério de aceite:**

- comandos admin rejeitados fora do chat permitido;
- testes cobrem permissões.

## 4.1 Itens que deixaram de ser roadmap ativo

Os itens abaixo já foram implementados, estabilizados ou absorvidos por frentes maiores:

- filtros guiados por cidade/estado;
- suporte core a filtro de cor;
- tracking de anúncios por wishlist;
- UX de `/start` e `/menu`;
- busca manual conversacional;
- contexto mínimo em alerta;
- contexto conservador de preço;
- texto de upgrade orientado à dor;
- horário de renovação do limite diário;
- Admin Deploy via Telegram;
- erro de proxy WebMotors como item isolado.

## 4.2 Trilha técnica paralela — V1→V2 das sources

- A trilha V1→V2 é **técnica de estabilização**, não um flip imediato de arquitetura.
- Ela **não substitui** as prioridades de lançamento.
- Próxima ação técnica: expandir dual-run controlado para sources principais.
- Webmotors está fora do caminho crítico da migração (source deprioritized, útil como fixture de blocked/challenge).
- Referência: `docs/V1_TO_V2_MIGRATION.md`.

## 5. Fora do roadmap imediato

- Webmotors avançada/Patchright.
- Facebook Marketplace com autenticação de usuário final.
- Browser persistente não-headless.
- Proxy residencial/mobile pago.
- Dashboard web completo.
- ML/IA avançada.
- API pública.
- Monetização avançada além do Premium/Founders inicial.
- Multi-categoria fora de carros.

Esses itens só entram após decisão explícita.

## 6. Ordem recomendada de execução

1. Pagamento/ativação Premium sem gargalo manual.
2. `/admin metrics`.
3. Teste de carga/prontidão beta.
4. Digest semanal v2.
5. Operação beta/founders/growth.
6. Fixtures reais por source.
7. Dual-run/paridade V1→V2 por source.
8. Equivalência cross-source em modo diagnóstico.
9. Histórico/retenção.
10. Admin UX.
11. Segurança admin.
12. Webmotors POC avançada somente com decisão explícita.

## 7. Referências

- `README.md`
- `AGENTS.md`
- `docs/USER_FLOWS.md`
- `docs/LLM_CONTEXT.md`
- `docs/ARCHITECTURE.md`
- `docs/PROJECT_GUIDELINE.md`
- `docs/LAUNCH_PLAN.md`
- `docs/AUCTION_RUNTIME.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/DOCUMENTATION_AUDIT.md`
- `docs/LEGACY_INVENTORY.md`
- `docs/V1_TO_V2_MIGRATION.md`
