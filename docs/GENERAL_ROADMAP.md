# Garagem Alvo / AutoHunter — Roadmap geral além de leilões

Atualizado em: 2026-05-21

Escopo: roadmap fora da frente de leilões. A frente de leilões fica documentada separadamente em `docs/AUCTION_ROADMAP.md`.

---

## 1. Estado atual do produto

Garagem Alvo / AutoHunter é um bot Telegram-first de monitoramento inteligente de anúncios de veículos, voltado principalmente para entusiastas automotivos.

O produto permite que o usuário crie buscas/wishlists e receba alertas quando surgirem anúncios compatíveis com seus critérios.

Público principal:

- entusiastas automotivos;
- pessoas buscando carros específicos;
- versões raras;
- configurações desejadas;
- boas bases para projeto;
- carros com potencial de preparação;
- oportunidades difíceis de acompanhar manualmente.

Canal principal:

```text
Telegram
```

Superfícies atuais relevantes:

- bot do usuário final;
- comandos administrativos;
- scheduler;
- sources de anúncios;
- banco com usuários, wishlists, filtros, anúncios e histórico de notificações;
- plano/free/premium;
- deploy/admin via Telegram;
- monitoramento operacional.

---

## 2. Princípios do roadmap

### 2.1 Não reabrir itens já concluídos

Itens já considerados resolvidos não devem voltar para o roadmap, salvo regressão real.

Exemplos:

- Admin Deploy via Telegram concluído;
- controle de anúncios inativos removido/concluído;
- Source Health Gate já tratado;
- Score vNext já tratado;
- paridade v1/v2 já tratada;
- formatter/notificação vNext já tratada;
- melhorias Premium/menu já tratadas quando resolvidas.

### 2.2 Evolução incremental

Evitar reescrever o produto.

Cada PR deve:

- resolver uma dor clara;
- ter teste;
- preservar operação 24/7;
- não quebrar Telegram;
- não alterar múltiplos domínios ao mesmo tempo;
- ter validação operacional simples.

### 2.3 Telegram continua sendo o canal principal

Não criar web app ou painel antes de esgotar ganhos simples via Telegram/admin.

---

# 3. Roadmap priorizado

---

## P0 — Segurança operacional e proteção de dados

Prioridade máxima fora de leilões.

### P0.1 — Garantir admin-only real nos comandos sensíveis

Objetivo: garantir que apenas o chat/admin autorizado tenha acesso aos comandos administrativos.

Comandos sensíveis:

```text
/admin
/admin deploy
/admin sources
/admin auctions
/admin hygiene
/admin notify-run real
/admin runall
/admin status
/admin config
```

Tarefas:

1. Revisar todos os handlers admin.
2. Garantir `is_admin` ou equivalente antes de qualquer ação sensível.
3. Testar usuário não admin chamando comandos.
4. Testar chat errado.
5. Testar callbacks admin, não apenas comandos textuais.
6. Garantir que comandos perigosos não executem ação antes do gate.
7. Adicionar log de tentativa negada, se fizer sentido.

Critérios de aceite:

```text
- usuário não admin não executa comando sensível;
- callback admin também é bloqueado;
- nenhum comando de alteração real roda antes do check;
- testes automatizados cobrem casos negativos.
```

### P0.2 — Backup e recuperação de users/wishlists

Objetivo: evitar perda operacional de usuários, buscas e histórico essencial.

Escopo mínimo:

- `users`;
- `wishlists`;
- filtros de wishlist;
- plano/assinatura;
- histórico mínimo de notificações;
- controle de dedupe/notificações já enviadas.

Avaliar se vale incluir `car_listings` ou alternativa mais enxuta, como histórico mínimo de notificação.

Tarefas:

1. Mapear tabelas críticas.
2. Criar comando/script de backup.
3. Salvar dump em local configurável.
4. Definir retenção.
5. Criar rotina de restore documentada.
6. Testar restore em banco temporário.
7. Documentar no runbook.

Critérios de aceite:

```text
- existe backup executável;
- existe restore testado;
- users/wishlists/filtros são recuperáveis;
- dedupe/notificações essenciais são preservados;
- documentação operacional existe.
```

### P0.3 — Runbook operacional do Raspberry

Objetivo: ter um guia claro para operar o projeto no Raspberry sem depender de memória.

Conteúdo:

- onde o projeto fica;
- serviços systemd;
- comandos de restart;
- logs;
- deploy;
- healthcheck;
- backup;
- variáveis de ambiente;
- rollback;
- diagnóstico de armazenamento;
- diagnóstico de scheduler;
- diagnóstico de sources.

Critério de aceite:

```text
docs/RUNBOOK_RASPBERRY.md criado ou atualizado.
```

---

## P1 — Documentação e arquitetura para LLM/Codex

### P1.1 — Documento principal para qualquer LLM entender o projeto

Objetivo: criar uma documentação oficial para abrir novo chat/Codex sem perder contexto.

Arquivo sugerido:

```text
docs/PROJECT_CONTEXT.md
```

Conteúdo:

- visão do produto;
- público-alvo;
- posicionamento;
- arquitetura;
- stack;
- principais fluxos;
- comandos;
- sources;
- scheduler;
- banco;
- entidades principais;
- fluxo de wishlist;
- fluxo de notificação;
- planos/free/premium;
- deploy/admin;
- riscos conhecidos;
- decisões já tomadas;
- o que não reabrir;
- próximos passos.

Critérios de aceite:

```text
- novo chat consegue entender o projeto sem histórico;
- Codex entende onde mexer;
- evita reabrir decisões já tomadas;
- aponta docs complementares.
```

### P1.2 — Documentação da arquitetura atual

Objetivo: documentar a arquitetura real do repositório.

Arquivo sugerido:

```text
docs/ARCHITECTURE.md
```

Conteúdo mínimo:

- visão em camadas;
- bot/handlers;
- services;
- sources;
- models;
- migrations;
- scheduler;
- notificações;
- settings;
- deploy;
- testes;
- pontos de extensão.

Critérios de aceite:

```text
- arquitetura atual documentada;
- responsabilidades por módulo claras;
- pontos frágeis conhecidos registrados.
```

### P1.3 — Auditoria de docs inúteis/depreciadas

Objetivo: reduzir ruído para humanos e LLMs.

Tarefas:

1. Listar documentos em `docs/`.
2. Classificar:
   - atual;
   - parcialmente atual;
   - depreciado;
   - duplicado;
   - mover para archive;
   - deletar.
3. Criar `docs/archive/` se necessário.
4. Atualizar README apontando para docs oficiais.

Critérios de aceite:

```text
- docs antigas não competem com source of truth;
- README aponta para documentos corretos;
- nada importante é apagado sem rastreabilidade.
```

---

## P2 — Evolução de wishlist e filtros

### P2.1 — Filtros por cor, cidade e estado

Objetivo: permitir buscas mais precisas.

Filtros mapeados:

- cor;
- cidade;
- estado.

Regras:

- filtro deve ser opcional;
- deve funcionar para anúncios normais;
- para sources sem dado confiável, não inventar;
- debug deve explicar quando o filtro bloqueou;
- se o campo não existir no anúncio, decidir se bloqueia ou ignora conforme regra explícita.

UX Telegram:

```text
Deseja filtrar por cor?
Deseja filtrar por cidade?
Deseja filtrar por estado?
```

Com opção de pular.

Critérios de aceite:

```text
- usuário cria wishlist com cor/cidade/estado;
- matching respeita filtros;
- debug mostra filtros aplicados;
- testes cobrem match e bloqueio.
```

### P2.2 — Melhorar edição de wishlist

Objetivo: reduzir fricção para editar buscas existentes.

Melhorias:

- editar nome/query;
- editar preço;
- editar ano;
- editar filtros;
- ligar/desligar leilões;
- pausar/ativar wishlist;
- excluir com confirmação;
- mostrar resumo antes de salvar.

Critérios de aceite:

```text
- usuário consegue alterar busca sem recriar;
- fluxo é guiado;
- modo rápido atual continua funcionando.
```

### P2.3 — Debug de wishlist mais acionável

Objetivo: quando uma busca não gera alerta, o admin deve saber o motivo.

Melhorias no debug:

- top candidatos;
- score;
- matched/missing tokens;
- filtros aplicados;
- motivo de rejeição;
- source;
- tipo;
- preço/lance;
- ano;
- data de atualização.

Critério de aceite:

```text
/admin match wishlist <id|index> --debug
```

deve responder claramente se não bateu por filtro de preço, ano, score textual, source não elegível, tipo não permitido ou duplicidade.

---

## P3 — Qualidade de matching e dedupe

### P3.1 — Unificação de anúncios equivalentes cross-source

Objetivo: avaliar se anúncios equivalentes publicados em fontes diferentes devem virar uma única notificação.

Problema: o mesmo carro pode aparecer em mais de uma fonte, ou o mesmo anúncio pode ser republicado.

Risco: colapsar anúncios distintos por engano.

Estratégia: começar como diagnóstico/admin, não como bloqueio automático.

Heurísticas possíveis:

- marca;
- modelo;
- versão;
- ano;
- preço;
- cidade/UF;
- km;
- placa final, quando existir;
- imagem;
- título normalizado;
- URL/source.

Fase 1: comando/admin que diga `possíveis equivalentes encontrados`, sem bloquear envio.

Fase 2: bloquear apenas quando confiança for alta.

Critérios de aceite:

```text
- não colapsa anúncios distintos;
- explica por que considerou equivalente;
- possui testes de falso positivo.
```

### P3.2 — Melhorar score textual geral

Objetivo: aprimorar matching de anúncios normais e leilões sem reduzir score mínimo global.

Diretrizes:

- preservar tokens automotivos curtos importantes;
- evitar substring solta;
- melhorar match de versão;
- tratar modelos compostos;
- não gerar falso positivo.

Exemplos importantes:

```text
Civic Si
Golf GTI
Jetta GLI
BMW X1
Audi A5
L200 Triton
Peugeot 208
C4 Pallas
S10
```

Critérios de aceite:

```text
- melhora casos reais;
- cobre falsos positivos;
- debug explica matched_tokens/missing_tokens.
```

---

## P4 — Sources tradicionais e cobertura

### P4.1 — WebMotors / bloqueio anti-bot

Estado atual: WebMotors sofre bloqueio por challenge/fingerprint PerimeterX.

Sinais conhecidos:

```text
Access to this page has been denied
Pressione e segure para confirmar que você é um humano
HTTP 200 com challenge
```

Decisão já tomada: não tratar mais como erro de proxy.

Caminhos possíveis:

1. sessão assistida;
2. bootstrap manual;
3. storage state persistente;
4. source despriorizada;
5. buscar alternativa menos frágil.

Não fazer:

- bypass agressivo;
- fingir que Playwright puro resolve;
- insistir em retry cego.

Critérios para retomar:

```text
- abordagem estável;
- compatível com Raspberry;
- baixo risco operacional;
- não exige manutenção manual frequente.
```

### P4.2 — Facebook Marketplace / Browse Marketplaces

Contexto mapeado:

```text
https://www.browsemarketplaces.com/
https://github.com/gmoz22/facebook-marketplace-nationwide
```

Problema principal: não há API oficial simples para Marketplace.

Decisão: não colocar usuário em fluxo inseguro ou frágil.

Possíveis caminhos:

- autenticação assistida;
- sessão persistente;
- agente local;
- integração externa;
- avaliar legalidade/termos;
- validar se o ganho compensa complexidade.

Estado: backlog de pesquisa, não P0.

### P4.3 — Fortalecer sources atuais antes de adicionar novas

Objetivo: evitar crescer fontes ruins demais.

Antes de adicionar novas sources:

- quality por source;
- health gate;
- debug;
- métricas de found/inserted/matched/notified;
- erro acionável;
- source isolável;
- teste com fixture real.

---

## P5 — Operação, observabilidade e cockpit admin

### P5.1 — Cockpit admin Telegram

Objetivo: um comando único para visão operacional.

Comando sugerido:

```text
/admin cockpit
```

ou:

```text
/admin status
```

Conteúdo:

- scheduler ativo;
- última execução global;
- status por source;
- erros recentes;
- notificações recentes;
- filas;
- dry-run/leilões;
- uso de disco;
- versão/commit atual;
- último deploy.

Critérios de aceite:

```text
- reduz necessidade de vários comandos;
- mostra próximo passo quando há problema;
- não polui usuário final.
```

### P5.2 — Alertas operacionais

Objetivo: alertar o admin quando algo importante falhar.

Casos:

- source sem execução há mais de X horas;
- scheduler parado;
- erro repetido de source;
- falha de deploy;
- disco baixo;
- banco indisponível;
- Telegram indisponível;
- source production_ready sem dados recentes.

Canal: somente chat admin.

Critérios de aceite:

```text
- alerta é acionável;
- não gera spam;
- tem cooldown;
- tem resumo claro.
```

### P5.3 — Diagnóstico de armazenamento no Raspberry

Contexto: já houve preocupação com armazenamento quase cheio.

Objetivo: identificar se o projeto gera:

- logs locais;
- fotos;
- XLSX;
- dumps;
- cache;
- SQLite acidental;
- arquivos temporários;
- artefatos sem retenção.

Entrega sugerida:

```text
scripts/storage_audit.py
docs/STORAGE_RUNBOOK.md
```

Critérios de aceite:

```text
- comando read-only de diagnóstico;
- lista maiores diretórios/arquivos;
- aponta origem provável;
- não apaga nada automaticamente.
```

---

## P6 — Planos, monetização e produto

### P6.1 — Revisar limites Free/Premium

Objetivo: garantir que o plano premium tenha valor claro.

Itens possíveis:

- número de wishlists;
- frequência de monitoramento;
- fontes premium;
- filtros avançados;
- tracking de anúncios;
- alertas prioritários;
- leilões como feature premium ou controlada;
- histórico maior.

Critérios de aceite:

```text
- limites documentados;
- bot explica claramente;
- testes de plan_capabilities.
```

### P6.2 — UX de upgrade

Objetivo: melhorar conversão sem ser invasivo.

Itens:

- mensagem clara quando usuário bate limite;
- botão de upgrade;
- explicar benefícios;
- não mostrar upgrade para usuário Premium;
- manter consistência no menu.

---

## P7 — Publicação e crescimento

### P7.1 — Publicações em Instagram/X com carros encontrados

Objetivo: usar achados reais para divulgar o produto.

Ideia: gerar posts com:

- carro encontrado;
- título;
- preço/lance;
- ano;
- fonte;
- imagem;
- resumo;
- CTA para usar o bot.

Fluxo recomendado:

1. sistema sugere post;
2. admin revisa;
3. admin aprova;
4. publicação manual ou semi-automática.

Não fazer inicialmente:

- postar automaticamente sem aprovação;
- publicar dados sensíveis;
- usar imagem quebrada;
- expor usuário/wishlist.

Critérios de aceite:

```text
- comando admin gera sugestão;
- admin aprova;
- conteúdo é revisável;
- não depende de automação externa complexa no P0.
```

### P7.2 — Agente de oportunidade/produto

Objetivo: ter um agente que observe dados do produto e sugira melhorias.

Exemplos:

- buscas que nunca dão match;
- sources com queda de qualidade;
- modelos mais buscados;
- oportunidades de conteúdo;
- filtros mais usados;
- motivos frequentes de rejeição;
- sugestões de roadmap.

Canal: admin Telegram.

Critério: o agente deve propor, não executar automaticamente.

---

## P8 — Web app futuro

### P8.1 — Avaliação de web app

Estado: não é prioridade imediata.

Possível utilidade:

- gerenciar wishlists;
- ver histórico;
- configurar filtros;
- dashboard admin;
- visualizar anúncios;
- controlar planos.

Estrutura mínima:

- autenticação;
- autorização;
- dashboard de buscas;
- listagem de alertas;
- painel admin;
- integração com banco atual;
- deploy seguro;
- HTTPS;
- logs.

Diretriz: só avançar quando o Telegram estiver estável e houver dor real que o bot não resolva bem.

---

## 9. Ordem recomendada de execução

Agora:

1. Validar melhoria de matching textual em produção.
2. Confirmar preview real com `L200 Triton`.
3. Validar envio real manual controlado da VIP.
4. Manter scheduler automático em dry-run.

Depois:

5. Segurança admin completa.
6. Backup/restore.
7. Documentação `PROJECT_CONTEXT.md` e `ARCHITECTURE.md`.
8. Auditoria de docs antigas.
9. Filtros por cor/cidade/estado.
10. Debug de wishlist melhorado.
11. Cockpit admin.
12. Unificação de anúncios equivalentes.
13. WebMotors/sources complexas.
14. Publicação social assistida.

---

## 10. Invariantes gerais

Toda PR futura deve respeitar:

1. Não misturar parser, envio real e scheduler na mesma PR.
2. Não liberar feature sensível sem gate admin.
3. Não quebrar usuário final para melhorar admin.
4. Não apagar dados sem backup/estratégia.
5. Não criar dependência pesada que prejudique Raspberry.
6. Não reabrir decisões concluídas sem motivo.
7. Sempre adicionar teste para o bug corrigido.
8. Sempre preservar compatibilidade do fluxo Telegram.
9. Sempre manter rollback simples.
10. Sempre documentar decisão operacional relevante.
