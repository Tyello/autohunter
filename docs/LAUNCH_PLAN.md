# Garagem Alvo — Plano de Lançamento
> Do estado atual ao mar aberto. Três frentes em paralelo: produto, técnica e aquisição.

---

## Contexto de partida

O produto funciona. O pipeline está completo. A cobertura de testes é boa. O que falta não é código novo — é fechar os buracos que impedem um usuário desconhecido de criar conta, receber valor em menos de 5 minutos e confiar o suficiente para pagar.

**Premissa do plano:** lançamento público em 4 semanas. Beta fechado na semana 2. Abertura gradual a partir da semana 4.

---

## Frente 1 — Produto: fechar os bloqueadores de conversão

### 1.1 Onboarding que entrega resultado imediato

**Problema hoje:** usuário cria busca e espera o scheduler rodar. Pode esperar 15–60 minutos sem nenhum feedback. Taxa de abandono nesse intervalo deve ser alta.

**O que fazer:**

Ao criar uma wishlist, disparar uma busca pontual imediata (já existe `trigger_initial_run_for_wishlist` no código) e enviar os primeiros resultados como mensagem de confirmação no mesmo fluxo:

```
✅ Busca criada: "civic si manual"
📡 Monitorando Mercado Livre, OLX, Chaves na Mão

Encontrei 3 anúncios relevantes agora:
→ [lista dos 3 mais recentes]

Você será avisado quando aparecer algo novo.
```

Se não houver resultado imediato, enviar mensagem honesta:
```
Nenhum anúncio encontrado agora para "ek9 b16".
Esse é um carro raro — pode demorar dias ou semanas.
Estou monitorando e você será o primeiro a saber.
```

Isso resolve o problema de "o bot está funcionando?" que todo usuário tem no primeiro dia.

---

### 1.2 Digest semanal ativado por padrão

O código já existe (`weekly_wishlist_digest_job`), mas está `default off`. Ativar para todos os usuários free e premium.

O digest precisa comunicar mesmo quando não houve alerta:

```
📋 Resumo da semana — Garagem Alvo

Suas buscas: civic si manual, golf gti mk7
Monitorei 1.240 anúncios esta semana.
Nenhum bateu com seus critérios.

O mercado de Civic Si teve 2 anúncios novos
em SP esta semana (ambos com preço acima do
seu limite).
```

Esse contexto de "o sistema está vivo e monitorando" é o que retém usuário que ainda não recebeu alerta.

---

### 1.3 Contexto de mercado no alerta

O alerta hoje entrega: título, preço, link. Precisa entregar também o porquê ele é relevante.

**Adicionar ao corpo do alerta:**
- `📉 18% abaixo da média recente` (quando aplicável, via `market_stats_cohorts`)
- `🔍 2ª vez que aparece esse modelo em 30 dias` (via `wishlist_listing_activity`)
- `⚡ Anunciado há 47 minutos` (timestamp relativo)

O campo `score_breakdown` já existe na notificação. É só expor parte dele ao usuário de forma legível.

---

### 1.4 Pagamento funcionando sem intervenção manual

**Bloqueador crítico.** O fluxo atual — comprovante pelo Telegram + ativação manual pelo admin — não escala para 30+ assinantes e passa insegurança.

**O que implementar (ordem de esforço crescente):**

**Opção A (2–3 dias de trabalho):** Mercado Pago com webhook. Cria a assinatura, recebe confirmação automática, ativa o Premium via `/admin premium activate` chamado programaticamente. O Mercado Pago tem SDK Python e webhook simples.

**Opção B (fallback se A atrasar):** Manter fluxo manual mas adicionar bot de confirmação — quando usuário enviar comprovante, o bot identifica o valor e notifica admin com botão de aprovação de 1 clique no Telegram. Reduz o trabalho manual de 5 minutos para 10 segundos.

Não lançar sem uma das duas opções.

---

### 1.5 `/start` com CTA claro e sem pitch prematuro

Hoje o `/start` faz o trabalho certo (não vende no primeiro contato). Mas precisa de uma linha que crie expectativa específica:

```
Garagem Alvo monitora anúncios de carros especiais
e te avisa quando aparece o certo, antes de todo mundo.

👉 /menu para criar sua primeira busca
```

Sem listar features. Sem planos. Só o valor central.

---

## Frente 2 — Técnica: o que precisa fechar antes do lançamento

### 2.1 P0 de performance (ver IMPROVEMENT_PLAN.md)

Em ordem:
1. Eager-load no sender loop — sem isso, 100 usuários = degradação perceptível
2. Index `ix_notifications_user_sent_today`
3. Pool SQLAlchemy explícito
4. `ensure_source_configs` movido para boot

**Prazo:** antes de abrir para beta.

---

### 2.2 Webmotors operacional (ver SOURCES_GUIDE.md)

Webmotors tem volume alto e é a fonte onde entusiasta mais busca carro específico. Sem ela, há gap perceptível na cobertura. O plano de resolução está detalhado no documento de sources.

**Prazo:** semana 1–2. Se não resolver em 2 semanas, comunicar claramente nos canais de divulgação que Webmotors está em integração.

---

### 2.3 Métricas mínimas de produto

Você tem `telemetry_events` mas não tem as perguntas respondidas:

| Pergunta | Onde buscar |
|---|---|
| Quantos usuários criaram busca esta semana? | `wishlists.created_at` |
| Qual % recebeu pelo menos 1 alerta? | `notifications WHERE status='sent'` |
| Qual % voltou ao bot em 7 dias? | `telemetry_events` ou `users.updated_at` |
| Qual a conversão Free → Premium? | `subscriptions` |
| Qual source gera mais alertas aprovados? | `notifications JOIN car_listings` |

Não precisa de dashboard bonito. Um comando `/admin metrics` no bot que retorna esses números uma vez por dia já é suficiente para operar.

---

### 2.4 Teste de carga mínimo antes do lançamento

Simular 50 usuários com wishlist ativa por 24h:
- Monitorar RAM do RPi a cada 5 minutos
- Verificar se scrape_jobs drena sem travamento
- Verificar se sender mantém cadência sem atraso crescente
- Verificar se Playwright não acumula processos zumbis

---

## Frente 3 — Aquisição: os primeiros 200 usuários sem gastar

### 3.1 Fase beta fechada (semana 2–3) — 30–50 pessoas

**Canal:** grupos de Telegram e WhatsApp de modelos específicos. Não grupos genéricos de "carro usado" — grupos de fã de Civic, Golf GTI, WRX, Opala.

**Mensagem de entrada:**
```
Criei um bot que monitora anúncios de [modelo]
em 4 sites ao mesmo tempo e avisa na hora.
Tenho 30 vagas para beta fechado, gratuito.
Quem quiser testar: @GaragemAlvoBot
```

**Meta:** 1 alerta relevante para cada usuário beta nos primeiros 2 dias. Isso requer que as buscas dos beta users sejam acompanhadas manualmente na primeira semana.

---

### 3.2 Loop de conteúdo orgânico (a partir da semana 3)

O "achado do dia" é o conteúdo natural do produto:

1. Bot encontra anúncio abaixo do mercado ou raro
2. Você captura o print do alerta
3. Posta no Instagram/TikTok com o contexto: "Esse Civic Si apareceu às 7h32. Às 10h já tinha vendido."

Não precisa de produção elaborada. Print + contexto + resultado. Esse formato ressoa com entusiasta porque é exatamente a dor que ele sente.

**Frequência mínima:** 3 posts por semana nas primeiras 4 semanas.

---

### 3.3 Parceria com 1 canal de conteúdo automotivo

Não precisa ser grande. Um canal de YouTube ou perfil de Instagram com 5.000–20.000 seguidores no nicho (JDM, clássicos, hot hatches) é mais eficaz que um com 500.000 que fala de tudo.

**Proposta:** acesso vitalício Premium + link na bio ou menção em 1 vídeo. Sem dinheiro envolvido no início.

**O que preparar:** um vídeo de 2 minutos mostrando o bot funcionando de verdade — criando busca, recebendo alerta, abrindo o anúncio.

---

### 3.4 Founders: fechar antes do lançamento público

O lote de Founders (R$ 149/ano) é a melhor ferramenta de validação financeira. Vender 20 Founders antes do lançamento público significa:

- R$ 2.980 de receita antecipada
- 20 usuários comprometidos com feedback real
- Prova de que pessoas pagam pelo produto

**Como fazer:** anunciar nos grupos de beta com urgência real ("20 vagas, preço trava por 24 meses"). Não criar urgência falsa — se vender 20, fechar de verdade.

---

## Cronograma

```
Semana 1
├── Correções P0 de performance (IMPROVEMENT_PLAN.md)
├── Início da resolução do Webmotors
├── Implementar onboarding com resultado imediato (1.1)
└── Iniciar pagamento automático (1.4)

Semana 2
├── Pagamento funcional (obrigatório para beta)
├── Digest semanal ativado por padrão
├── Beta fechado: 30–50 pessoas em grupos de nicho
└── Acompanhamento manual das buscas dos beta users

Semana 3
├── Coletar e implementar feedback crítico do beta
├── Contexto de mercado no alerta (1.3)
├── Comando /admin metrics
├── Primeiros posts de conteúdo orgânico
└── Abordagem do parceiro de conteúdo

Semana 4
├── Fechar lote Founders
├── Lançamento público gradual (100 usuários/semana)
└── Monitoramento de RAM/performance sob carga real
```

---

## Critérios para considerar o lançamento bem-sucedido

Após 30 dias do lançamento público:

- [ ] 100 usuários com pelo menos 1 busca ativa
- [ ] 15% de conversão Free → pago (Founders + mensal)
- [ ] Taxa de retenção de 7 dias > 60% (usuário volta ao bot)
- [ ] Sender sem atraso > 5 minutos em horário de pico
- [ ] Nenhum incidente de dados perdidos ou notificação duplicada em massa
- [ ] Pelo menos 3 relatos espontâneos de "achei o carro pelo bot"

---

*Documento criado em 2026-05-21. Revisar métricas e cronograma ao fechar o beta.*
