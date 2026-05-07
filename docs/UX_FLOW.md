# AutoHunter — Fluxo de Experiência do Sistema

## 1. Visão geral do produto
AutoHunter é um produto Telegram-first ...

## 2. Princípios de UX
- Telegram-first.
- /menu como caminho principal.
- Comandos rápidos como fallback.
- Upgrade apenas em momentos de limite/intenção.
- /start não vende plano.
- Filtros antes da primeira busca.
- Botões nunca podem ficar sem resposta.

## 3. Mapa macro de navegação
/start
└── /menu
    ├── Criar wishlist
    │   ├── informar carro
    │   ├── criar agora
    │   └── adicionar filtros antes de criar
    ├── Minhas wishlists
    │   ├── remover wishlist
    │   ├── rastreados
    │   └── voltar
    ├── Rastreados
    ├── Buscar anúncio
    ├── Upgrade Premium, somente Free
    └── Ajuda

## 4. /start
Usuário sem wishlist e com wishlist: direciona para /menu, sem venda de plano.

## 5. /menu principal
Menu Free com Upgrade Premium; menu Premium sem Upgrade.

## 6. Criar wishlist
Fluxo guiado por passos, com cancelamento e sessão expirada.

## 7. Filtros no fluxo de criação
Preço, ano, KM, cidade e estado com exemplos e substituição.

## 8. Minhas wishlists
Lista com filtros amigáveis, rastreados, notificações, remover e voltar.

## 9. Remover wishlist
Lista, escolha, confirmação, sucesso e erros.

## 10. Rastreados
Entrada via menu principal e via Minhas wishlists; slots por plano.

## 11. /buscar
Busca manual com resposta imediata e processamento em background.

## 12. /plan
Mostra Free, Premium, vencido, uso real, validade e CTA só para Free.

## 13. /upgrade
Comando e botão no menu Free, planos mensal/anual, links manuais Mercado Pago, fallback sem links e pagamento manual sem webhook.

## 14. CTAs Premium
Aparece em /menu Free, /plan Free e limites. Não aparece em /start nem para Premium.

## 15. Ativação Premium manual
Pendente/futuro próximo: paga no link, envia comprovante, admin ativa validade.

## 16. /help
Texto atual orienta comandos e fluxo guiado; melhorar simplificação futura.

## 17. Comandos avançados
/wishlist, /wishlist_add, /wishlist_remove, /wishlist_filter_add, /wishlist_filter_list, /wishlist_track_list, /admin...

## 18. Estados de erro globais
sessão expirada, callback antigo, sem wishlist, limite atingido, erro genérico, pagamento não configurado, permissão negada.

## 19. Checklist para especialista UX
Inclui perguntas sobre nomenclatura, filtros, timing de upgrade, clareza do Premium e excesso de comandos/botões.

## 20. Lacunas conhecidas
pagamento manual; sem webhook; ativação manual Premium; expiração automática ainda parcial; /buscar em background em memória.
