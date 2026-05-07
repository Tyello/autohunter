# AutoHunter — Fluxo de Experiência do Sistema

## 1. Objetivo da experiência
AutoHunter é Telegram-first para monitorar anúncios recorrentes. Caminho principal via /menu; comandos avançados são fallback.

## 2. Entrada inicial
`/start` apresenta proposta e direciona para `/menu`; não mostra preço nem botão de upgrade.

## 3. Menu principal
Free: inclui 🚀 Upgrade Premium. Premium: não inclui upgrade.

## 4. Criar wishlist
Entrada pelo botão ➕; usuário envia busca, pode adicionar filtros e concluir ou cancelar.

## 5. Filtros no fluxo de criação
Preço, ano, km, cidade e estado; aceita linguagem natural e formatos guiados.

## 6. Minhas wishlists
Mostra buscas, filtros, rastreados e ações de remover/voltar.

## 7. Rastreamento de anúncios
Botão ⭐ Rastrear nos anúncios; Free sem automação e Premium com alertas automáticos.

## 8. Buscar anúncio
`/buscar` responde assíncrono com resultados, vazio ou erro controlado.

## 9. Plano atual
`/plan` Free mostra uso + CTA `/upgrade`; Premium mostra validade e renovação manual.

## 10. Upgrade Premium
Aparece em limites, `/upgrade`, `/plan` Free e menu Free. Traz mensal/anual, links Mercado Pago manuais e instrução de comprovante.

## 11. Ativação manual Premium
Admin ativa manualmente por comando; usuário recebe confirmação e validade; expiração volta para Free.

## 12. Ajuda
`/help` orienta comandos principais e legado compatível.

## 13. Estados de erro e fallback
Callback antigo, sessão expirada, erros genéricos, sem wishlist e limites atingidos retornam mensagens direcionadas.

## 14. Pontos para avaliação UX
Checklist: entendimento de wishlist/busca, timing de upgrade, clareza de valor Free/Premium, termos técnicos, discoverabilidade de ações e renovação/cobrança.
