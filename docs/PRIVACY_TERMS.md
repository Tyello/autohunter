# Privacidade e Termos Mínimos — Garagem Alvo

> **Rascunho técnico — revisar com responsável legal antes de publicar ou enviar a qualquer usuário.**
>
> Este documento cobre o mínimo pedido em `docs/OPEN_BETA_READINESS.md` (seção 4, item "Política simples de privacidade e termos mínimos") para viabilizar beta fechado/aberto. Não é aconselhamento jurídico. Antes de publicar: preencher os campos `[...]`, confirmar enquadramento LGPD com quem responde legalmente pelo produto, e então habilitar a exposição no bot.
>
> A estrutura do lado do bot já existe e está pronta, mas desligada de propósito: comando `/termos` (`app/bot/handlers.py:cmd_termos`) com texto em `app/bot/renderers.py:render_privacy_terms_text`, atrás do kill switch `privacy_terms_command_enabled` (default `False` em `app/core/settings.py`). O comando não aparece no autopreenchimento do Telegram (não está em `app/bot/commands.py`) e não responde nada enquanto o flag estiver desligado. Ao preencher os campos pendentes aqui, atualizar também `render_privacy_terms_text()` antes de ligar o flag.

## 1. Quem opera o Garagem Alvo

Responsável pelo produto: `[NOME DA EMPRESA OU PESSOA RESPONSÁVEL]`.
Contato para dúvidas, suporte ou solicitações sobre dados pessoais: `[EMAIL DE CONTATO]`.

## 2. O que o Garagem Alvo faz

O Garagem Alvo é um bot de Telegram que monitora anúncios de veículos em fontes públicas na internet e avisa o usuário quando encontra um anúncio compatível com as buscas que ele configurou.

## 3. Quais dados guardamos

Guardamos apenas o necessário para o bot funcionar:

- `chat_id` do Telegram (identificador da conversa com o bot);
- nome de usuário do Telegram, quando disponível publicamente;
- as buscas/wishlists criadas (termo de busca, filtros de preço/ano/km/cidade/etc.);
- anúncios rastreados manualmente pelo usuário (`⭐ Rastrear`);
- interações operacionais necessárias para o funcionamento do bot (ex.: qual busca gerou qual alerta, se o usuário abriu um anúncio);
- dados de assinatura/plano (Free ou Premium) e, quando aplicável, referência de pagamento processada pelo Mercado Pago (não guardamos dados de cartão — isso é tratado inteiramente pelo Mercado Pago).

Não coletamos localização em tempo real, contatos do Telegram, nem mensagens fora do fluxo do bot.

## 4. Por quanto tempo guardamos

Dados operacionais de curto prazo (fila interna, logs técnicos, histórico de atividade por anúncio) têm limpeza automática periódica, hoje configurada em `scripts/cleanup_operational_data.py`. Dados de conta, buscas ativas e histórico de assinatura ficam guardados enquanto a conta estiver ativa.

## 5. Como pedir a exclusão dos seus dados

Hoje não existe um comando de autoatendimento para apagar a conta. Para solicitar exclusão dos seus dados, envie uma mensagem para `[EMAIL DE CONTATO]` ou fale com o admin pelo próprio bot. O pedido será processado manualmente em até `[PRAZO EM DIAS]`.

## 6. Limitações importantes sobre os anúncios monitorados

- As fontes monitoradas são sites/portais de terceiros. Eles podem mudar de layout, bloquear acesso automatizado, remover anúncios ou apresentar informação desatualizada a qualquer momento, sem aviso prévio.
- O Garagem Alvo **não garante** disponibilidade, preço final, condição do veículo, existência do vendedor ou possibilidade de compra de nenhum anúncio exibido.
- A cobertura de fontes pode variar por modelo, cidade e período. Não prometemos monitorar "todos os sites" — apenas as fontes ativas no momento (ver `docs/LEGACY_INVENTORY.md`/`source_configs` para o estado real).

## 7. Leilões (piloto controlado)

Quando o usuário ativa a opção de leilões em uma busca, ele reconhece que:

- **lance não é preço final** — pode haver comissão, taxas, edital e condições adicionais definidas pelo leiloeiro;
- o Garagem Alvo apenas avisa sobre lotes compatíveis com a busca; a responsabilidade pela decisão de participar do leilão, ler o edital e vistoriar o veículo é inteiramente do usuário;
- o piloto atual só notifica lotes da categoria `car`.

## 8. Planos e pagamento

- O plano Free tem limites de uso descritos em `/plan` no bot.
- O upgrade para Premium é processado via Mercado Pago; a ativação ocorre automaticamente após confirmação do pagamento (webhook), com fallback manual pelo admin em caso de falha operacional.
- Reembolsos e cancelamentos seguem `[POLÍTICA DE REEMBOLSO A DEFINIR]`.

## 9. Alterações neste documento

Este texto pode mudar conforme o produto evolui. Mudanças relevantes serão comunicadas pelo próprio bot.

---

*Última atualização: 2026-09-18. Consulte `docs/OPEN_BETA_READINESS.md` para o checklist de beta e `docs/LAUNCH_PLAN.md` para o plano de lançamento.*
