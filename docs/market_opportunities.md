# AutoHunter — Oportunidades de mercado (entusiastas)

## 1) Dor real (o que o público compra)

Entusiasta não está “comprando um carro”. Está comprando:

- **Chance**: pegar o anúncio antes que o mercado reaja
- **Tempo**: menos horas caçando em vários sites
- **Confiança**: evitar cilada e preço fora da realidade

O MVP do AutoHunter ataca a dor mais valiosa: **velocidade + cobertura**.

## 2) Segmentos com melhor fit

1) **JDM / importados populares** (Civic Si, Integra, WRX, Lancer, 350Z)
2) **Hot hatches** (Golf GTI, 206/207/208 GT, Punto T-Jet, DS3)
3) **Clássicos 1985–2005** (Kadett GS/GSi, Escort XR3, Opala, Chevette preparado)
4) **Modelos com baixa liquidez mas alta paixão** (raros que somem rápido)

O padrão que mais paga: gente que já olha anúncio todo dia.

## 3) Diferenciais (moat) que cabem no produto

- **Matching semântico por wishlist** (seu código já começou isso): evita falsos positivos e aumenta confiança
- **Deal Score** (já tem FIPE + score simples): destacar “abaixo de FIPE” e “raridade”
- **Rarity Score**: quantos anúncios daquela wishlist aparecem por semana/mês
- **Alertas com contexto**: “apareceu 1 anúncio novo em 3 dias” / “preço 18% abaixo da média recente”

Esses itens viram assinatura (não é só scraping).

## 4) Loop de crescimento (sem ads)

- Alertas bons viram print no grupo → usuários novos
- “Melhores achados da semana” (1x/semana) vira conteúdo e retenção
- Convite por código para beta: exclusividade + controle de carga

## 5) Parcerias que monetizam sem virar marketplace

- **Vistoria e cautelar** (cupom + afiliado)
- **Despachante** (documentação de transferência)
- **Mecânica especializada** (inspeção pré-compra)
- **Crédito/seguro** (lead qualificado quando usuário clica “quero negociar”)

No começo: foque em 1 parceiro por vertical (para não virar catálogo).

## 6) Riscos e como mitigar

- **Bloqueios por fonte**: trate como “fonte degradada” (backoff + fallback) e não como quebra do produto
- **Custos de infra**: seu Pi 3 é ótimo, mas OLX/anti-bot tende a exigir um worker remoto
- **Qualidade do dado**: título/ano/km incompletos → roadmap de enrichment com page-fetch limitado e cache

## 7) Oportunidades de roadmap que aumentam conversão

- Filtros por ano/km/cidade (mesmo simples já muda o jogo)
- “Negociação rápida”: botão para abrir WhatsApp com mensagem pronta (copy inteligente)
- “Watchlist tags”: ex.: “EK9”, “K20”, “AP1” para entusiastas hardcore
