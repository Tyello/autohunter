# Launch Plan — Garagem Alvo

Atualizado em: 2026-05-28.  
Estado confrontado com a `main`.

> Documento dono de **lançamento, beta, go-to-market e critérios de sucesso**.  
> Não detalhar aqui implementação de assinatura, plano, UX ou eficiência; apenas apontar para os documentos donos.

---

## Escopo deste documento

Este documento responde: “o que falta para lançar com segurança e medir resultado?”

| Assunto | Documento dono |
|---|---|
| Pagamento, webhook, aprovação 1-clique | `06_SUBSCRIPTION.md` |
| Trial, Founders, limites e preço | `05_PLAN.md` |
| UX/copy/digest | `01_UX.md` |
| Jornada de usuário | `02_FLUXO.md` |
| Carga Raspberry e operação técnica | `08_EFICIENCIA.md` |
| Bugs e validações | `07_BUGS.md` |

---

## Pronto para beta controlado

- Bot Telegram com onboarding, `/start`, `/menu`, filtros, busca manual e tracking.
- Alertas com score, contexto, recência e preço quando disponível.
- Free/Premium com `/plan` e `/upgrade`.
- Scheduler, filas persistentes, workers e sender.
- `/admin metrics` v1.
- Backup/restore operacional.
- Source health/admin diagnostics.
- FIPE import/coverage disponível, com carga real ainda operacional.
- Dedupe cross-source em shadow/live flagado.
- Leilões em piloto controlado.
- Digest semanal v2.
- Copy pós-criação específica.
- Contexto de raridade/frequência nos alertas com amostra mínima.

---

## Bloqueadores de lançamento público amplo

### BL-01 — Pagamento/ativação Premium sem gargalo manual

**Status:** aberto.  
**Documento dono:** `06_SUBSCRIPTION.md`.

Critério de lançamento: usuário paga ou é aprovado pelo fluxo de beta e recebe Premium sem depender de comando manual digitado pelo operador.

---

### BL-02 — Teste de carga em Raspberry Pi real

**Status:** aberto.  
**Documento dono:** `08_EFICIENCIA.md`.

Critério de lançamento: validar 50 usuários / 24h no host real, com RAM, backlog, sender e Playwright estáveis.

---

### BL-03 — Beta real acompanhado por métricas

**Status:** aberto.

`/admin metrics` já existe; a lacuna agora é rodar o beta e acompanhar dados reais.

Métricas mínimas:

- novos usuários 7d;
- usuários com busca ativa;
- usuários que receberam alerta 7d;
- buscas criadas 7d;
- backlog;
- Free/Premium;
- sources que geram alerta.

---

## Itens fechados que não devem voltar como bloqueadores

- `/admin metrics` v1.
- Source health/admin diagnostics.
- Backup health básico.
- Baseline de eficiência documentado.
- Índice de notifications enviado/validado.

---

## Cronograma revisado

```text
Semana 0 — Pré-beta técnico
├── fechar ativação Premium sem comando manual
├── validar carga 50 usuários/24h no Raspberry real
├── validar /admin health e /admin metrics durante carga
└── preparar lista fechada de beta users

Semana 1 — Beta fechado
├── convidar 30–50 pessoas de nichos automotivos
├── comunicar cobertura real sem prometer WebMotors
├── acompanhar /admin metrics diariamente
├── acompanhar /admin health e filas
└── corrigir críticos de UX/operação

Semana 2 — Retenção e valor recorrente
├── decidir trial 7 dias com dados do beta
├── publicar achados reais
└── testar parceria com canais automotivos pequenos/médios

Semana 3 — Founders
├── abrir lote limitado para beta users
├── usar fluxo de pagamento/ativação já fechado
└── medir conversão e suporte manual

Semana 4 — Abertura gradual
├── entrada controlada por lote
├── monitorar RAM/fila/sender
├── growth orgânico com conteúdo
└── revisar roadmap pós-beta com dados reais
```

---

## Critérios de sucesso — 30 dias pós-lançamento controlado

- [ ] 100 usuários com pelo menos 1 busca ativa.
- [ ] 15% de conversão Free → pago ou Founders.
- [ ] Retenção 7 dias acima de 60%.
- [ ] Sender sem atraso maior que 5 minutos em horário de pico.
- [ ] Nenhuma notificação duplicada em massa.
- [ ] 3 relatos espontâneos de valor real.
- [ ] 20 usuários usaram tracking ou abriram anúncio via alerta.
- [ ] Backlog de notificações não cresce continuamente.

---

## Comunicação de cobertura honesta

Copy recomendada:

```text
O Garagem Alvo monitora Mercado Livre, OLX e Chaves na Mão.
WebMotors está em validação por bloqueios anti-bot.
Novas fontes entram aos poucos durante o beta.
```

Evitar:

```text
Monitoramos todos os principais portais.
```

---

## Próxima tarefa recomendada

Fechar **ativação Premium sem comando manual**.

Ordem sugerida:

1. Aprovação admin em 1 clique para beta.
2. Webhook Mercado Pago para escala.
3. Auditoria de ativações.
4. Avisos de expiração Premium.

Detalhes: `06_SUBSCRIPTION.md`.
