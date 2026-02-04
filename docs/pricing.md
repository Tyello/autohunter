# AutoHunter — Planos e preços (proposta)

> Objetivo: cobrar pouco, mas entregar valor real: **encontrar o anúncio certo antes de todo mundo**.

## Princípios

- **Gratuito como porta de entrada** (prova de valor em 1–2 dias)
- **Entusiasta paga por velocidade + volume**
- **Preço simples** (3 tiers) + desconto anual
- **Sem spam**: limites explícitos e previsíveis

## Tiers

### Free — R$ 0

Para provar o valor.

- 1 wishlist
- 5 alertas/dia
- Fontes: Mercado Livre + Chaves na Mão
- Intervalos mínimos: ML 15 min, Chaves 60 min
- FIPE + score simples

Ideal para quem quer “dar uma olhada” e sentir o bot.

### Enthusiast — R$ 9,90 / mês

Para quem acompanha o mercado todo dia.

- 3 wishlists
- 30 alertas/dia
- Fontes: Mercado Livre + Chaves na Mão + Webmotors + GoGarage
- Intervalos mínimos: ML 10 min, Chaves 60 min, Webmotors 180 min, GoGarage 180 min
- Filtros por fonte e faixa de preço (gte/lte)
- Prioridade de envio (fila)

Ponto de equilíbrio: barato o suficiente para “pagar sem pensar”, mas já muda o jogo.

### Pro — R$ 19,90 / mês

Para quem caça oportunidade de verdade.

- 10 wishlists
- 150 alertas/dia
- Todas as fontes (inclui OLX quando disponível)
- Intervalos mínimos: ML 5–10 min, OLX 30–60 min, demais conforme estabilidade
- Modo silencioso (não notificar de madrugada)
- Filtros avançados sugeridos para roadmap: ano mínimo, km máximo, cidade/UF

Preço pensado para o “hardcore”: economiza 1–2 horas/semana e aumenta chance de pegar raridade.

### Founders (lote limitado) — R$ 149 / ano

Lote de lançamento para beta fechado (ex.: primeiras 200 pessoas).

- Equivale a ~R$ 12,42/mês
- Garante preço travado por 24 meses
- Canal direto (grupo) + votação do roadmap

## Upgrades e descontos

- **Anual**: 2 meses grátis (pague 10, leve 12)
- **Add-on (futuro)**: “Alertas instantâneos” (prioridade + mais intervalos) por +R$ 4,90/m

## Regras de fair use

- Backoff/cooldown por fonte para evitar ban e manter o serviço vivo.
- Se uma fonte bloquear, o plano não “some”: o bot continua nas demais fontes.
