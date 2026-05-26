# Fluxo — Melhorias de Jornada do Usuário

Atualizado em: 2026-05-25.  
Estado confrontado com a `main`.

> Documento dono de **jornadas e gaps de fluxo**.  
> Não detalhar aqui implementação de pagamento, regras de plano, arquitetura ou carga operacional.

---

## Escopo deste documento

Este documento responde: “quais jornadas ainda quebram, ficam manuais ou geram silêncio para o usuário?”

Detalhes canônicos ficam assim:

| Assunto | Documento dono |
|---|---|
| Implementação de pagamento/webhook/aprovação | `06_SUBSCRIPTION.md` |
| Trial, Founders e limites | `05_PLAN.md` |
| UX/copy das mensagens | `01_UX.md` |
| Lançamento/beta | `04_LAUNCH_PLAN.md` |
| Eficiência/carga Raspberry | `08_EFICIENCIA.md` |

---

## Estado atual confrontado com a `main`

### Já existe no produto

- Entrada por `/start` e `/menu`.
- Criação e gestão de buscas/wishlists pelo Telegram.
- Filtros implícitos e guiados.
- Busca pontual em `/buscar`/menu.
- Tracking de anúncios por wishlist.
- Plano Free/Premium, `/plan` e `/upgrade`.
- Link Mercado Pago configurável no upgrade.
- Ativação Premium manual/admin.
- Scheduler, filas persistentes, workers e sender.
- `/admin metrics` v1 para acompanhamento operacional básico.

### Ainda não existe como fluxo fechado

- Pagamento/ativação Premium sem ação manual digitada pelo admin.
- Trial automático de 7 dias para usuário novo.
- Avisos user-facing antes da expiração Premium.
- Nudge interativo quando uma busca fica 7 dias sem alerta.
- Diagnóstico automático de busca muito restritiva após primeira varredura sem resultado.

---

## FLOW-01 — Pagamento/ativação ainda manual

**Status:** aberto.  
**Impacto:** bloqueador comercial.

**Fluxo atual:** usuário recebe link Mercado Pago e depende de validação/ativação manual.

**Fluxo desejado:** Premium ativado sem comando manual digitado pelo admin.

Há dois caminhos:

1. webhook Mercado Pago para escala;
2. aprovação admin em 1 clique para beta.

**Detalhamento canônico:** `06_SUBSCRIPTION.md`.

**Critério de fluxo:** usuário paga ou envia comprovante e recebe confirmação clara, sem ficar preso em conversa manual indefinida.

---

## FLOW-02 — Expiração Premium sem comunicação completa

**Status:** aberto.

**Fluxo desejado:**

```text
7 dias antes → aviso de renovação
1 dia antes → aviso final
no dia → downgrade + mensagem clara do que mudou
```

**Detalhamento canônico:** `06_SUBSCRIPTION.md::SUB-03`.

**Critério:** usuário não descobre a expiração apenas quando perde uma capacidade Premium.

---

## FLOW-03 — Busca sem alerta por 7 dias

**Status:** aberto.

**Problema:** busca ativa sem alerta pode parecer bot parado.

**Fluxo desejado:** enviar nudge por wishlist silenciosa com opções:

```text
[🔧 Ajustar filtros] [⏸️ Pausar busca] [Continuar monitorando]
```

**Relação com UX:** o texto final e o digest semanal v2 ficam em `01_UX.md`.

**Critério:** não enviar mais de 1 vez por wishlist por semana.

---

## FLOW-04 — Trial de 7 dias

**Status:** aberto.

**Fluxo desejado:** usuário novo experimenta capacidades Premium por tempo limitado e recebe avisos antes de cair para Free.

**Detalhamento canônico:** `05_PLAN.md::PLAN-01`.

**Critério:** trial tem regra clara de elegibilidade, duração e downgrade.

---

## FLOW-05 — Diagnóstico de busca muito restritiva

**Status:** aberto.

**Problema:** primeira varredura sem resultado não explica se o carro é raro, caro demais ou se os filtros bloquearam tudo.

**Fluxo desejado:** após zero resultado, orientar o usuário com causa provável e opção de relaxar filtros.

**Critério:** primeira varredura sem resultado vira orientação, não silêncio.

---

## Prioridade atual

| # | Item | Status | Documento dono do detalhe |
|---|---|---|---|
| 1 | FLOW-01 — Pagamento/ativação | Aberto | `06_SUBSCRIPTION.md` |
| 2 | FLOW-04 — Trial 7 dias | Aberto | `05_PLAN.md` |
| 3 | FLOW-02 — Expiração com aviso | Aberto | `06_SUBSCRIPTION.md` |
| 4 | FLOW-03 — Nudge busca sem alerta | Aberto | `01_UX.md` + este documento |
| 5 | FLOW-05 — Diagnóstico busca restritiva | Aberto | este documento |

---

## Fora da fila deste documento

- `/admin metrics` v1: concluído.
- Refactor de admin handlers: `03_ARQUITETURA.md`.
- Throughput/Raspberry: `08_EFICIENCIA.md`.
- Bugs e validações técnicas: `07_BUGS.md`.
