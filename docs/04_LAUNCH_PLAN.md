# Launch Plan — Garagem Alvo

Atualizado em: 2026-05-25.  
Estado confrontado com a `main` após a entrada de `/admin metrics`.

> Produto funcional, UX base melhorada, operação técnica mais madura.  
> Lacuna atual: pagamento/ativação Premium, teste de carga, beta real e comunicação honesta de cobertura.

---

## O que está pronto para beta controlado

- Bot com onboarding guiado, `/start`, `/menu`, filtros, busca manual e rastreamento.
- Alertas com score, contexto, recência e contexto de preço quando disponível.
- Plano Free/Premium com limites, `/plan` e `/upgrade`.
- Scheduler, filas persistentes, workers e sender.
- `/admin metrics` v1 para acompanhamento de usuários, buscas, alertas, backlog, conversão e sources 7d.
- Backup/restore operacional.
- Admin deploy via Telegram.
- Source health/admin diagnostics.
- FIPE import/coverage operacional, com carga real ainda dependente de operação.
- Dedupe cross-source preparado com feature flag, shadow observável e live OFF por padrão.
- Leilões em piloto controlado, com opt-in por busca e gates admin.

---

## O que bloqueia lançamento público amplo

### BL-01 — Pagamento sem intervenção manual

**Status:** aberto.  
**Prioridade:** P0 comercial.

Ver `02_FLUXO.md::FLOW-01` e `06_SUBSCRIPTION.md` para implementação completa.

**Caminho principal:** webhook Mercado Pago.

**Fallback aceitável para beta:** aprovação admin em 1 clique, sem comando manual digitado.

**Critério mínimo para público desconhecido:** usuário paga e recebe Premium sem depender de conversa manual com o operador.

---

### BL-02 — Teste de carga em Raspberry Pi real

**Status:** aberto.  
**Prioridade:** P0 operacional.

O código já recebeu correções de eficiência, pool, sender, backup e cleanup, mas precisa de validação operacional com carga representativa.

Cenário mínimo:

```bash
# Criar base sintética controlada
python scripts/load_test_seed.py --users 50 --wishlists-per-user 2

# Monitorar por 24h no host real
watch -n 300 "free -h && ps aux | grep playwright | wc -l && psql -c 'SELECT status, count(*) FROM scrape_jobs GROUP BY status;'"
```

Critérios:

- RAM estável, sem crescimento indefinido.
- `scrape_jobs` drena, sem acúmulo progressivo.
- Sender sem atraso maior que 5 minutos.
- Sem processo Playwright zumbi após 24h.
- `/admin health` e `/admin metrics` coerentes durante a janela.

---

### BL-03 — Beta real com acompanhamento

**Status:** aberto.

`/admin metrics` já existe, então a lacuna não é mais ferramenta básica de acompanhamento. A lacuna agora é rodar beta real e usar as métricas.

Métricas mínimas a acompanhar:

- novos usuários 7d;
- usuários com busca ativa;
- usuários que receberam alerta 7d;
- buscas criadas 7d;
- backlog;
- Free/Premium;
- sources que geram alerta.

---

## Itens que eram bloqueadores e foram fechados

### `/admin metrics` v1

**Status:** concluído na `main`.

Evidência:

```text
app/bot/admin_handlers_metrics.py
app/bot/handlers_admin.py

tests/test_admin_metrics_command.py
```

Não reabrir como requisito de lançamento. Evoluções de métricas devem ser incrementais.

---

## Cronograma revisado

```text
Semana 0 — Pré-beta técnico
├── BL-01: pagamento webhook ou aprovação 1-clique
├── BL-02: teste de carga 50 usuários/24h no Raspberry real
├── revisar copy pós-criação de busca
├── validar /admin health e /admin metrics durante carga
└── preparar lista fechada de beta users

Semana 1 — Beta fechado (30–50 pessoas)
├── grupos de nicho: Civic Si, Golf GTI, WRX, BMW/Audi específicos
├── convite honesto: beta gratuito e cobertura limitada
├── acompanhar /admin metrics diariamente
├── acompanhar /admin health e filas
└── corrigir críticos de UX/operação

Semana 2 — Valor recorrente
├── UX-01: digest semanal v2
├── FLOW-04: trial 7 dias, se fizer sentido para o beta
├── primeiros posts de achados reais
└── contato com canais automotivos pequenos/médios

Semana 3 — Founders
├── lote limitado de Founders para beta
├── preço de lançamento controlado
├── ativação por fluxo já fechado
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
- [ ] Backlog de notificações não cresce de forma contínua.

---

## Comunicação de cobertura honesta

Não prometer WebMotors como fonte estável.

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

**Pagamento/ativação Premium sem comando manual.**

Ordem recomendada:

1. Aprovação admin em 1 clique para beta.
2. Webhook Mercado Pago para escala.
3. Auditoria de ativações no metadata da subscription.
4. Avisos de expiração Premium.
