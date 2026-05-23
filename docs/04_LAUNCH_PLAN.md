# Launch Plan — Garagem Alvo
> Estado atual: produto funcional, UX melhorada, sources estáveis (ML + OLX + Chaves na Mão).
> Lacuna: pagamento, métricas e operação beta.

---

## O que está pronto para lançar

- Bot com onboarding guiado, `/start`, `/menu`, filtros, busca manual, rastreamento
- Alertas com score, contexto, recência e badge de preço
- Plano Free/Premium com limites, `/plan`, `/upgrade`
- Scheduler, filas, workers, sender estáveis
- Sources: ML, OLX, Chaves na Mão funcionais
- Backup/restore operacional
- Admin deploy via Telegram

---

## O que bloqueia o lançamento público

### BL-01 — Pagamento sem intervenção manual (P0)

Ver `02_FLUXO.md::FLOW-01` para implementação completa.

**Prazo máximo:** antes de abrir para qualquer usuário que não seja beta pessoal.

**Fallback aceitável para beta:** aprovação admin em 1 clique (sem digitar comando).

---

### BL-02 — `/admin metrics` inexistente (P0)

Sem métricas, o beta não tem como ser acompanhado. Não dá para saber se alguém recebeu alerta, se está convertendo, se o sender está atrasado.

**Implementar:** ver `01_UX.md::UX-04`

**Prazo:** semana 0 (antes do beta).

---

### BL-03 — Teste de carga não foi feito (P0)

O código tem as correções de N+1 e pool. Mas nunca foi validado com 50 usuários simultâneos por 24h no RPi real.

**Script de simulação:**

```bash
# Criar 50 usuários fictícios com wishlist ativa
python scripts/load_test_seed.py --users 50 --wishlists-per-user 2

# Monitorar por 24h
watch -n 300 "free -h && ps aux | grep playwright | wc -l && psql -c 'SELECT status, count(*) FROM scrape_jobs GROUP BY status;'"
```

**Critérios de aprovação:**
- RAM estável (não cresce indefinidamente)
- `scrape_jobs` drena (não acumula)
- Sender sem atraso > 5 minutos
- Nenhum processo Playwright zumbi após 24h

---

## Cronograma

```
Semana 0 — Pré-beta técnico
├── ARCH-04: max_overflow no pool (1 linha)
├── ARCH-05: confirmar/criar index sent_at
├── ARCH-07/08: ajustar batch e playwright no .env
├── BL-02: /admin metrics v1
├── BL-01: pagamento (webhook ou 1-clique)
└── BL-03: teste de carga 50 usuários/24h

Semana 1 — Beta fechado (30–50 pessoas)
├── Grupos de Telegram de nicho: Civic, Golf GTI, WRX, Opala
├── Mensagem: "30 vagas para beta fechado gratuito"
├── Acompanhar manualmente: quem criou busca, quem recebeu alerta
└── Corrigir críticos de UX/operação que aparecerem

Semana 2 — Valor recorrente
├── UX-01: digest semanal v2
├── FLOW-04: trial 7 dias para novos usuários
├── Primeiros 3 posts de achados (Instagram/X)
└── Contato com 1 canal automotivo de nicho (5k–20k seguidores)

Semana 3 — Founders
├── Anunciar lote de 20 Founders nos grupos de beta
├── Preço: R$ 149/ano (travado 24 meses)
├── Ativar fluxo de pagamento com os Founders como primeiro teste real
└── Monitorar conversão

Semana 4 — Abertura gradual
├── Entrada controlada (+50 usuários/semana)
├── Monitorar RAM/fila/sender sob carga real
├── Growth orgânico com conteúdo
└── Revisão do roadmap pós-beta
```

---

## Critérios de sucesso (30 dias pós-lançamento)

- [ ] 100 usuários com pelo menos 1 busca ativa
- [ ] 15% conversão Free → pago (Founders + mensal)
- [ ] Retenção 7 dias > 60%
- [ ] Sender sem atraso > 5min em horário de pico
- [ ] Nenhuma notificação duplicada em massa
- [ ] 3 relatos espontâneos de "achei o carro pelo bot"
- [ ] 20 usuários usaram tracking ou abriram anúncio via alerta

---

## Comunicação de cobertura honesta

Não prometer Webmotors. Copy correta para divulgação:

```
O Garagem Alvo monitora Mercado Livre, OLX e Chaves na Mão.
Webmotors está em integração por bloqueio anti-bot.
Novas fontes chegam ao longo do beta.
```
