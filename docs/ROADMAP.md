# AutoHunter / Garagem Alvo — Roadmap

Atualizado em: 2026-05-22

## 1. Visão do produto

AutoHunter / Garagem Alvo é um bot Telegram-first para monitoramento inteligente de anúncios de carros usados, focado em público entusiasta automotivo.

Não é marketplace genérico.
Não é loja.
Não é concessionária.

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
- Paridade v1/v2.
- Source Health Gate.
- Mensagem vNext.
- Logotipo/imagem da marca.
- Contract enforcement/qualidade do NormalizedAd.
- Primeira execução imediata ao criar wishlist.
- Auditoria completa das sources.
- Controle de anúncios inativos cross-source.
- Diagnóstico admin de sources.
- `browser_block_resources` configurável por source.
- Warmup Webmotors mensurável.
- `curl_cffi` experimental para Webmotors.
- Classificação blocked/error corrigida para Webmotors.
- Webmotors formalizada como `operational_role=deprioritized`.
- Sources `deprioritized` fora da saúde crítica global.
- Admin Deploy via Telegram concluído e removido do roadmap.
- WebMotors erro de proxy removido como item; agora tratado como bloqueio anti-bot/fingerprint.

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

### P1 — Wishlist: filtros por cor, cidade e estado

**Objetivo:** permitir que o usuário refine uma wishlist por cor, cidade e UF.

**Por que é prioridade:** entrega valor direto para o usuário final e reduz ruído.

**Escopo:**

- persistir campos opcionais na wishlist;
- ajustar fluxo guiado Telegram;
- ajustar edição/listagem de wishlist;
- aplicar filtros no matching;
- normalizar cor/cidade/UF vindas das sources;
- exibir filtros ativos no resumo;
- manter comportamento atual quando filtros estiverem vazios.

**Critério de aceite:**

- usuário cria wishlist com cor/cidade/UF;
- usuário edita filtros;
- matching respeita filtros preenchidos;
- filtros vazios não quebram comportamento existente;
- testes cobrem filtros preenchidos e ausentes.

### P2 — Rastrear até 3 anúncios por wishlist

**Objetivo:** permitir que o usuário monitore até 3 anúncios específicos por wishlist.

**Escopo:**

- adicionar/listar/remover rastreados;
- respeitar limite de 3;
- melhorar mensagens para limite, duplicidade, slot vazio e anúncio indisponível;
- preservar controle do que já foi notificado;
- tratar anúncio órfão/inativo com mensagem clara.

**Critério de aceite:**

- até 3 anúncios rastreados por wishlist;
- tentativa do quarto anúncio retorna mensagem clara;
- usuário consegue remover e liberar slot;
- listagem mostra status dos rastreados.

### P3 — Backup e recuperação de users/wishlists

**Objetivo:** criar rotina segura de backup/restore dos dados críticos.

**Dados prioritários:**

- users;
- wishlists;
- filtros;
- tracked listings;
- preferências/plano;
- histórico mínimo de notificações, se fizer sentido.

**Escopo:**

- script de export;
- script de restore controlado;
- documentação operacional;
- avaliar se `car_listings` entra no backup ou se basta histórico enxuto.

**Critério de aceite:**

- backup versionado por data/hora;
- restore documentado;
- dados críticos recuperáveis;
- sem exposição de tokens/segredos.

### P4 — Testes de regressão por source com fixtures reais

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

### P5 — Unificação de anúncios equivalentes cross-source

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

### P6 — Histórico de notificação e retenção

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

### P7 — Admin UX incremental

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

### P8 — Segurança admin

**Objetivo:** garantir que somente o chat admin autorizado tenha acesso a comandos administrativos.

**Escopo:**

- revisar gate de admin chat;
- testar comandos sensíveis;
- garantir deploy/restart/source config protegidos.

**Critério de aceite:**

- comandos admin rejeitados fora do chat permitido;
- testes cobrem permissões.

### P9 — Growth/branding

**Objetivo:** preparar comunicação inicial do Garagem Alvo.

**Escopo:**

- bio curta do bot;
- mensagem de boas-vindas mais comercial;
- exemplos de uso;
- textos para canal/grupo;
- posts futuros Instagram/X com carros encontrados.

**Critério de aceite:**

- usuário entende proposta em poucos segundos;
- linguagem alinhada ao público entusiasta;
- separação clara Free/Premium, se aplicável.

## 5. Fora do roadmap imediato

- Webmotors avançada/Patchright.
- Facebook Marketplace com autenticação de usuário final.
- Browser persistente não-headless.
- Proxy residencial/mobile pago.
- Dashboard web completo.
- ML/IA avançada.
- API pública.
- Monetização avançada.
- Multi-categoria fora de carros.

Esses itens só entram após decisão explícita.

## 6. Ordem recomendada de execução

1. Wishlist — filtros por cor, cidade e estado.
2. Rastrear até 3 anúncios por wishlist.
3. Backup/recuperação.
4. Fixtures reais por source.
5. Equivalência cross-source em modo diagnóstico.
6. Histórico/retenção.
7. Admin UX.
8. Segurança admin.
9. Growth/branding.
10. Webmotors POC avançada somente com decisão explícita.

## 7. Referências

- `README.md`
- `docs/LLM_CONTEXT.md`
- `docs/ARCHITECTURE.md`
- `docs/PROJECT_GUIDELINE.md`
- `docs/AUCTION_RUNTIME.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/DOCUMENTATION_AUDIT.md`
- `docs/LEGACY_INVENTORY.md`
