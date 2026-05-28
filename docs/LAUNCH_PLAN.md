# Garagem Alvo — Plano de Lançamento

> Do produto funcional ao lançamento público controlado. O foco agora não é provar que o bot funciona; é provar ativação, confiança, pagamento, operação e aquisição.

---

## Status atual

Atualizado em: 2026-05-28.

O produto já possui:

- bot Telegram com `/start` e `/menu` guiados;
- criação e gestão de buscas/wishlists;
- filtros implícitos e guiados;
- busca manual/pontual;
- tracking de anúncios;
- alertas com contexto mínimo, score, recência, preço e raridade/frequência quando há amostra confiável;
- plano Free/Premium;
- upgrade com link Mercado Pago configurável;
- ativação Premium manual/admin;
- scheduler, filas persistentes, workers e sender;
- `/admin metrics` de produto/comercial;
- source health/admin;
- digest semanal v2;
- leilões em piloto controlado.

A lacuna de lançamento não é mais “falta produto”. É:

1. ativar Premium sem operação manual frágil;
2. validar carga/estabilidade no Raspberry;
3. operar beta com feedback real usando `/admin metrics`;
4. adquirir os primeiros usuários sem prometer cobertura que ainda não existe.

---

## Premissa revisada

Premissa: lançamento público gradual após um beta fechado curto.

Sequência recomendada:

```text
pré-beta técnico -> beta fechado 30–50 pessoas -> founders -> abertura gradual
```

Não abrir público amplo antes de resolver pagamento/ativação ou, no mínimo, fallback operacional de aprovação em 1 clique.

---

## Frente 1 — Produto e conversão

### 1.1 Onboarding e primeira busca

**Estado atual:** resolvido para beta.

O usuário já consegue criar busca pelo menu/fluxo guiado. A criação agenda primeira varredura imediatamente em fila, sem esperar o scheduler natural.

O fluxo confirma busca monitorada, diferencia varredura em andamento, envio imediato quando houver dado disponível e falha de agendamento sem bloquear a criação.

**Critério de aceite:**

- usuário entende imediatamente que a busca foi criada e que o bot está trabalhando;
- não há scraping síncrono pesado dentro do callback.

---

### 1.2 Digest semanal v2

**Estado atual:** resolvido para beta.

O digest semanal v2 usa marca pública Garagem Alvo, mostra buscas monitoradas, anúncios ativos no radar e copy explícita quando não há anúncio ativo dentro dos critérios.

Exemplo desejado:

```text
📋 Resumo da semana — Garagem Alvo

Suas buscas: civic si manual, golf gti mk7
Monitorei anúncios compatíveis com suas buscas durante a semana.

Civic Si manual:
- 2 anúncios novos em SP
- nenhum entrou no seu limite de preço

Golf GTI MK7:
- sem anúncio novo compatível esta semana

Continuo monitorando e aviso quando aparecer algo bom.
```

---

### 1.3 Alertas com contexto

**Estado atual:** resolvido para beta.

O alerta já entrega score, label humanizado, recência, preço, fonte, motivo/critério, contexto conservador de preço e contexto conservador de raridade/frequência quando há amostra mínima.

**Lacunas possíveis:**

- recorrência do modelo/termo em 30 dias;
- contexto de raridade por wishlist;
- explicação melhor quando a base de mercado é pequena.

**Tarefa recomendada:**

- `LAUNCH-ALERTS-01`: adicionar contexto de recorrência quando houver dado confiável em `wishlist_listing_activity` ou fonte equivalente.

---

### 1.4 Pagamento funcionando sem intervenção manual frágil

**Estado atual:** bloqueador crítico.

O fluxo atual usa link Mercado Pago configurável, mas a ativação Premium ainda é manual/admin após validação.

**Opção A — caminho principal:** Mercado Pago com webhook.

- Criar referência de pagamento vinculada ao usuário/chat_id.
- Receber webhook.
- Validar evento.
- Ativar Premium via serviço interno.
- Notificar usuário.
- Notificar admin.
- Registrar auditoria.

**Opção B — fallback aceitável para beta:** aprovação em 1 clique.

- Usuário envia comprovante.
- Bot notifica admin com botões:
  - aprovar mensal;
  - aprovar anual;
  - recusar.
- Aprovação chama o mesmo serviço de ativação Premium.

**Regra de lançamento:** não abrir público amplo sem uma das duas opções.

---

### 1.5 `/start` e `/menu`

**Estado atual:** resolvido o suficiente para beta.

`/start` e `/menu` já criam entrada clara para primeira busca, buscas existentes, busca pontual, tracking e plano.

**Ajuste opcional:** refinar copy da primeira tela para a promessa central:

```text
Garagem Alvo monitora anúncios de carros especiais
e te avisa quando aparece o certo, antes de todo mundo.
```

---

## Frente 2 — Técnica e operação

### 2.1 P0 de performance

**Estado atual:** boa parte resolvida.

Já há evidência de:

- eager/selectin-load no claim de notificações;
- cache de budget por usuário no sender;
- pool SQLAlchemy explícito;
- `ensure_source_configs` no boot do scheduler;
- cache de summaries de wishlist.

**Ainda validar:**

- existência/aplicação real do índice `ix_notifications_user_sent_today`.

**Tarefa recomendada:**

- `LAUNCH-PERF-01`: confirmar migration do índice `ix_notifications_user_sent_today`; se ausente, criar migration e teste/guardrail.

---

### 2.2 WebMotors

**Estado atual:** decisão operacional tomada.

WebMotors está tecnicamente implementada, mas bloqueada por PerimeterX/fingerprint e despriorizada. Não deve bloquear lançamento se outras sources estiverem entregando valor.

**Ação de lançamento:** comunicar cobertura real.

Em vez de prometer “4 sites incluindo WebMotors”, usar copy honesta:

```text
Monitoramos fontes automotivas em expansão. WebMotors está em integração por bloqueio anti-bot e pode não fazer parte do beta inicial.
```

---

### 2.3 Métricas mínimas de produto

**Estado atual:** pendente.

Criar `/admin metrics` para responder:

| Pergunta | Onde buscar |
|---|---|
| Quantos usuários existem? | `users` |
| Quantos usuários criaram busca esta semana? | `wishlists.created_at` |
| Quantos usuários têm busca ativa? | `wishlists.is_active` |
| Qual % recebeu pelo menos 1 alerta? | `notifications WHERE status='sent'` |
| Qual % voltou ao bot em 7 dias? | `telemetry_events` ou `users.updated_at` se confiável |
| Qual a conversão Free → Premium? | `subscriptions` |
| Qual source gera mais alertas enviados? | `notifications JOIN car_listings` |
| Qual o backlog do sender? | `notifications status queued/processing` |

Não precisa dashboard web. Precisa caber no Telegram.

---

### 2.4 Teste de carga mínimo antes do beta

**Estado atual:** pendente.

Simular 50 usuários com wishlist ativa por 24h:

- monitorar RAM do RPi a cada 5 minutos;
- verificar se `scrape_jobs` drena sem travamento;
- verificar se sender mantém cadência sem atraso crescente;
- verificar se Playwright não acumula processos zumbis;
- registrar relatório simples.

Critério prático:

- sender sem atraso crescente;
- fila não cresce indefinidamente;
- RAM não entra em pressão contínua;
- nenhum processo browser acumulado;
- falhas por source ficam isoladas.

---

## Frente 3 — Aquisição e validação

### 3.1 Beta fechado — 30–50 pessoas

**Canal:** grupos de Telegram e WhatsApp de modelos específicos. Não grupos genéricos de carro usado.

Exemplos:

- Civic;
- Golf GTI;
- WRX;
- Opala;
- Jetta GLI;
- Audi/BMW de entusiasta.

Mensagem base:

```text
Criei um bot que monitora anúncios de carros especiais
e avisa no Telegram quando aparece algo compatível.

Estou abrindo 30 vagas para beta fechado gratuito.
Quem quiser testar: @GaragemAlvoBot
```

**Meta:** cada beta user precisa receber valor ou feedback claro nos primeiros 2 dias.

Se não houver alerta, o admin precisa saber:

- busca muito rara;
- filtros muito restritivos;
- source sem cobertura suficiente;
- preço fora da realidade;
- nenhum anúncio novo.

---

### 3.2 Acompanhamento manual dos beta users

Criar rotina operacional simples:

- usuário entrou;
- criou busca;
- recebeu primeiro resultado/alerta;
- abriu anúncio;
- rastreou algum anúncio;
- bateu limite;
- pediu upgrade;
- deu feedback.

Pode começar com planilha/admin manual, mas idealmente vira `/admin metrics` + consultas curtas.

---

### 3.3 Loop de conteúdo orgânico

O “achado do dia” é o conteúdo natural do produto:

1. Bot encontra anúncio abaixo do mercado ou raro.
2. Você captura o print do alerta.
3. Posta no Instagram/X/TikTok com contexto:

```text
Esse Civic Si apareceu cedo.
Quem monitora manualmente provavelmente viu tarde.
O Garagem Alvo avisou assim que entrou na busca.
```

Frequência mínima inicial: 3 posts por semana.

---

### 3.4 Parceria com 1 canal de conteúdo automotivo

Não precisa ser grande. Um canal/perfil de 5.000–20.000 seguidores em nicho automotivo pode ser melhor que perfil genérico enorme.

Proposta inicial:

- acesso Premium gratuito por período definido;
- demonstração real do bot;
- menção/link em bio/post/vídeo.

---

### 3.5 Founders

Lote Founders valida disposição de pagamento.

Antes de vender Founders:

- pagamento/ativação não pode depender de comando manual demorado;
- benefício precisa estar claro;
- limite real de vagas deve ser respeitado.

Exemplo de meta:

- 20 Founders;
- preço anual promocional;
- benefício travado por período definido;
- feedback prioritário.

---

## Cronograma revisado

```text
Semana 0 — Pré-beta técnico
├── Pagamento webhook ou aprovação admin 1 clique
├── Teste de carga 50 usuários/24h
└── Ajustar copy pública de cobertura real das sources

Semana 1 — Beta fechado
├── 30–50 beta users em grupos de nicho
├── Acompanhamento manual dos usuários sem primeiro alerta
├── Correções críticas de UX/operação
└── Coleta estruturada de feedback

Semana 2 — Valor recorrente
├── Primeiros posts de achados
└── Abordagem de 1 parceiro de nicho

Semana 3 — Founders
├── Fechar oferta Founders
├── Ativar fluxo de pagamento/ativação seguro
├── Monitorar conversão Free → Premium
└── Ajustar limites/copy conforme feedback

Semana 4 — Abertura gradual
├── Entrada controlada de novos usuários
├── Monitoramento de RAM/fila/sender
├── Growth orgânico leve
└── Revisão do roadmap pós-beta
```

---

## Critérios para considerar o lançamento bem-sucedido

Após 30 dias do lançamento público:

- [ ] 100 usuários com pelo menos 1 busca ativa.
- [ ] 15% de conversão Free → pago (Founders + mensal/anual).
- [ ] Retenção de 7 dias > 60%.
- [ ] Sender sem atraso > 5 minutos em horário de pico.
- [ ] Nenhum incidente de dados perdidos ou notificação duplicada em massa.
- [ ] Pelo menos 3 relatos espontâneos de “achei o carro pelo bot”.
- [ ] Pelo menos 20 usuários usaram tracking ou abriram anúncio a partir de alerta.
- [ ] Nenhuma promessa pública baseada em source despriorizada/bloqueada.

---

## Tarefas finais de lançamento

### P0

- `LAUNCH-PAY-01`: Mercado Pago webhook ou aprovação admin 1 clique.
- `LAUNCH-LOAD-01`: teste de carga 50 usuários/24h.

### P1

- `LAUNCH-COPY-01`: copy pública honesta sobre cobertura de sources.
- `LAUNCH-BETA-01`: checklist beta fechado.
- `LAUNCH-FOUNDERS-01`: pacote Founders.

### P2

- `LAUNCH-GROWTH-01`: rotina de achados para Instagram/X/TikTok.
- `LAUNCH-PARTNER-01`: abordagem de 1 parceiro de nicho.

---

*Este plano deve ser revisado ao final do beta fechado. O roadmap estrutural fica em `docs/ROADMAP.md`; os fluxos atuais ficam em `docs/USER_FLOWS.md`.*
