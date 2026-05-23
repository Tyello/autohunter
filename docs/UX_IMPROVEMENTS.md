# Garagem Alvo — Roadmap de UX concluído

> Registro consolidado da frente de melhorias de UX executada entre os PRs #260 e #290.
> Este documento passa a ser histórico/estado final do bloco, não uma lista ativa de execução.

---

## Status de execução

Última atualização: 2026-05-22  
Status geral: ✅ Bloco UX concluído

A frente atual de UX foi concluída. Todos os itens mapeados neste documento foram implementados ou endereçados. Novas melhorias de produto devem entrar em novo roadmap/bloco, para evitar empilhar ajustes incrementais neste arquivo.

### Concluído

- [x] 1.1 — Botão CTA no `/start` — PR #260
- [x] 1.2 — Resultado imediato após criar busca — PR #266
- [x] 1.3 — Contexto de ausência no `/start` — PR #280
- [x] 2.1 — Badge de recência com fallback para `created_at` — PR #267
- [x] 2.2 — Contexto de mercado quando `market_stats` está vazio — PR #290
- [x] 2.3 — Contexto mínimo garantido em todo alerta — PR #269
- [x] 2.4 — Label de score humanizado — PR #279
- [x] 3.1 — Lista de buscas compacta — PR #260
- [x] 3.2 — “Buscar agora” inicia fluxo conversacional — PR #276
- [x] 3.3 — Limite diário com contexto e CTA suave — PR #272
- [x] 4.1 — Botão rastrear nos resultados de `/buscar` — PR #264
- [x] 4.2 — Contexto histórico em queda de preço rastreado — PR #288
- [x] 5.1 — Barra de progresso no `/plan` — PR #273
- [x] 5.2 — Texto de upgrade orientado à dor — PR #284
- [x] 6.1 — Detectar comando durante sessão aberta — PR #282
- [x] 6.2 — Tela vazia de anúncios rastreados — PR #260
- [x] 6.3 — Botões de sugestão nos filtros — PR #278
- [x] 6.4 — Horário de renovação do limite diário — PR #286

### Encaminhamento

Este roadmap está encerrado.

Próximas frentes recomendadas devem ser abertas em documentos próprios, por exemplo:

1. **Operação e confiabilidade**
   - scheduler
   - sources
   - alertas admin
   - estabilidade 24/7
   - WebMotors/anti-bot

2. **Produto e monetização**
   - ativação Premium
   - trial
   - conversão Free → Premium
   - métricas de upgrade
   - fluxo de pagamento/validação

3. **Inteligência de ofertas**
   - score
   - FIPE
   - market stats
   - histórico de preço
   - deduplicação cross-source

4. **Growth e distribuição**
   - posts para Instagram/X
   - canal público Telegram
   - conteúdo automático com achados
   - criativos de divulgação

---

## Registro consolidado das entregas

### 1.1 Botão CTA no `/start` — ✅ Concluído no PR #260
**Resultado entregue:** CTA contextual no `/start` para criar primeira busca ou abrir buscas existentes.  
**Impacto esperado:** reduz fricção de onboarding e aumenta ativação inicial.

### 1.2 Resultado imediato após criar busca — ✅ Concluído no PR #266
**Resultado entregue:** feedback imediato da primeira varredura agendada via fila, sem scraping síncrono no callback.  
**Impacto esperado:** aumenta confiança de que a busca foi criada e está ativa.

### 1.3 Contexto de ausência no `/start` — ✅ Concluído no PR #280
**Resultado entregue:** `/start` passou a refletir contexto recente para quem já possui buscas ativas.  
**Impacto esperado:** reforça percepção de valor para usuários que retornam após ausência.

### 2.1 Badge de recência com fallback para `created_at` — ✅ Concluído no PR #267
**Resultado entregue:** recência exibe sinal temporal confiável quando possível e fallback conservador quando necessário.  
**Impacto esperado:** melhora leitura de urgência sem induzir precisão falsa.

### 2.2 Contexto de mercado quando `market_stats` está vazio — ✅ Concluído no PR #290
**Resultado entregue:** alertas de preço ganharam fallback de contexto quando não há base estatística robusta.  
**Impacto esperado:** evita alertas “secos” e mantém utilidade mesmo em cenários de baixa cobertura.

### 2.3 Contexto mínimo garantido em todo alerta — ✅ Concluído no PR #269
**Resultado entregue:** todo alerta passou a carregar contexto mínimo (motivo/critério/busca) inclusive em casos de score ausente ou baixo.  
**Impacto esperado:** melhora compreensão do “por que recebi isso?”.

### 2.4 Label de score humanizado — ✅ Concluído no PR #279
**Resultado entregue:** score passou a ser comunicado com rótulos curtos e humanos.  
**Impacto esperado:** leitura mais rápida de prioridade sem depender de interpretação técnica.

### 3.1 Lista de buscas compacta — ✅ Concluído no PR #260
**Resultado entregue:** listagem de buscas consolidada com informações essenciais em formato mais enxuto.  
**Impacto esperado:** melhora escaneabilidade e gestão diária das buscas.

### 3.2 “Buscar agora” inicia fluxo conversacional — ✅ Concluído no PR #276
**Resultado entregue:** ação “Buscar agora” foi integrada ao fluxo conversacional de busca manual.  
**Impacto esperado:** reduz ambiguidades e melhora conclusão da intenção do usuário.

### 3.3 Limite diário com contexto e CTA suave — ✅ Concluído no PR #272
**Resultado entregue:** mensagem de limite diário passou a explicar contexto e direcionar upgrade de forma não punitiva.  
**Impacto esperado:** preserva experiência e reduz frustração em momento sensível.

### 4.1 Botão rastrear nos resultados de `/buscar` — ✅ Concluído no PR #264
**Resultado entregue:** resultados de busca manual passaram a oferecer ação direta de rastreamento.  
**Impacto esperado:** acelera transição de descoberta para acompanhamento contínuo.

### 4.2 Contexto histórico em queda de preço rastreado — ✅ Concluído no PR #288
**Resultado entregue:** alertas de queda de preço incluem histórico resumido quando disponível.  
**Impacto esperado:** facilita decisão com base em trajetória de preço, não apenas valor pontual.

### 5.1 Barra de progresso no `/plan` — ✅ Concluído no PR #273
**Resultado entregue:** `/plan` passou a exibir progresso visual de uso dos limites.  
**Impacto esperado:** melhora previsibilidade do plano e reduz dúvidas sobre consumo.

### 5.2 Texto de upgrade orientado à dor — ✅ Concluído no PR #284
**Resultado entregue:** copy de upgrade foi reescrita para evidenciar perda de oportunidade, sem alterar planos/preços.  
**Impacto esperado:** reforça valor percebido e melhora conversão potencial.

### 6.1 Detectar comando durante sessão aberta — ✅ Concluído no PR #282
**Resultado entregue:** comandos globais passaram a proteger sessão em andamento com opções de continuar ou descartar.  
**Impacto esperado:** reduz perda de contexto e erros de navegação em fluxo conversacional.

### 6.2 Tela vazia de anúncios rastreados — ✅ Concluído no PR #260
**Resultado entregue:** estado vazio de rastreados ganhou orientação prática para próxima ação.  
**Impacto esperado:** reduz becos sem saída e incentiva uso do rastreamento.

### 6.3 Botões de sugestão nos filtros — ✅ Concluído no PR #278
**Resultado entregue:** filtros passaram a oferecer sugestões rápidas sem remover entrada livre.  
**Impacto esperado:** acelera configuração de busca e mantém flexibilidade.

### 6.4 Horário de renovação do limite diário — ✅ Concluído no PR #286
**Resultado entregue:** mensagens de limite passaram a informar horário de renovação com base no timezone configurado.  
**Impacto esperado:** define expectativa temporal clara e reduz ansiedade de uso.

---

## Resumo final

| # | Item | PR | Status | Impacto |
|---|---|---|---|---|
| 1.1 | Botão CTA no `/start` | #260 | ✅ Concluído | Onboarding mais acionável |
| 1.2 | Resultado imediato após criar busca | #266 | ✅ Concluído | Confiança operacional pós-criação |
| 1.3 | Contexto de ausência no `/start` | #280 | ✅ Concluído | Retenção de usuários que retornam |
| 2.1 | Badge de recência com fallback para `created_at` | #267 | ✅ Concluído | Urgência mais legível |
| 2.2 | Contexto de mercado quando `market_stats` está vazio | #290 | ✅ Concluído | Alertas úteis com baixa cobertura de dados |
| 2.3 | Contexto mínimo garantido em todo alerta | #269 | ✅ Concluído | Clareza do motivo do alerta |
| 2.4 | Label de score humanizado | #279 | ✅ Concluído | Priorização mais intuitiva |
| 3.1 | Lista de buscas compacta | #260 | ✅ Concluído | Gestão de buscas mais rápida |
| 3.2 | “Buscar agora” inicia fluxo conversacional | #276 | ✅ Concluído | Melhor conclusão da busca manual |
| 3.3 | Limite diário com contexto e CTA suave | #272 | ✅ Concluído | Menos fricção no limite diário |
| 4.1 | Botão rastrear nos resultados de `/buscar` | #264 | ✅ Concluído | Fecha ciclo descoberta → rastreamento |
| 4.2 | Contexto histórico em queda de preço rastreado | #288 | ✅ Concluído | Decisão melhor em alertas de queda |
| 5.1 | Barra de progresso no `/plan` | #273 | ✅ Concluído | Visibilidade de consumo do plano |
| 5.2 | Texto de upgrade orientado à dor | #284 | ✅ Concluído | Melhor narrativa de valor Premium |
| 6.1 | Detectar comando durante sessão aberta | #282 | ✅ Concluído | Proteção de contexto conversacional |
| 6.2 | Tela vazia de anúncios rastreados | #260 | ✅ Concluído | Estado vazio com orientação útil |
| 6.3 | Botões de sugestão nos filtros | #278 | ✅ Concluído | Entrada de filtros mais rápida |
| 6.4 | Horário de renovação do limite diário | #286 | ✅ Concluído | Expectativa clara de renovação |

## Critério de encerramento

Este bloco pode ser considerado concluído porque:

- o onboarding inicial ficou acionável;
- o retorno do usuário ganhou contexto;
- os alertas passaram a explicar melhor score, preço, recência e motivo;
- a gestão de buscas ficou mais compacta;
- busca manual virou fluxo conversacional;
- rastreamento passou a fechar o ciclo busca → acompanhar → queda de preço;
- plano, limite diário e upgrade ficaram mais claros;
- sessões abertas passaram a ter proteção contra perda de contexto;
- filtros ganharam sugestões sem remover digitação livre.

## Fora deste documento

Não continuar adicionando novos microitens neste arquivo.

Novas melhorias devem ir para roadmaps próprios, especialmente:

- confiabilidade operacional;
- novas sources;
- inteligência de mercado/FIPE;
- premium/pagamento;
- growth e conteúdo;
- painel/admin;
- observabilidade.
