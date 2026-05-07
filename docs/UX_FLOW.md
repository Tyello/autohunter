# AutoHunter — Fluxo de Experiência do Sistema

## 1. Visão geral do produto
AutoHunter é um produto **Telegram-first** para pessoas que querem monitorar carros usados sem ficar repetindo busca manual ao longo do dia.

- **Público principal**: comprador pessoa física, normalmente comparando opções de carro por faixa de preço/ano/KM.
- **Canal principal**: Telegram (comandos + teclado inline).
- **Objetivo do usuário**: cadastrar buscas persistentes (wishlists), receber anúncios e notificações, e opcionalmente rastrear anúncios específicos.
- **Wishlist (busca persistente)**: intenção de compra salva que roda continuamente no backend.
- **Busca manual (`/buscar`)**: consulta pontual “agora”, sem persistência.
- **Filtro**: regra de refinamento (preço, ano, KM, cidade, estado etc.) aplicada à wishlist.
- **Rastreado**: anúncio específico marcado para acompanhamento (preço/status).
- **Notificação**: mensagem enviada quando há match de busca/rastreio.

## 2. Princípios de UX
1. **Telegram-first**: UX principal depende de mensagens e callbacks, não de web app.
2. **`/menu` como hub principal**: descoberta de funcionalidades por botões.
3. **Comando rápido como fallback**: usuários avançados podem usar `/wishlist_*`, `/buscar` etc.
4. **Upgrade no momento de intenção/limite**: não vender no `/start`.
5. **Primeira experiência orientada por criação de wishlist**.
6. **Filtros antes da execução completa quando fizer sentido**.
7. **Botão nunca sem feedback**: todo callback deve responder (`q.answer`) e editar/enviar texto de forma segura.

## 3. Mapa macro de navegação
```text
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
```

## 4. /start
### Entrada do usuário
- Usuário envia `/start`.

### Cenário A: usuário sem wishlist
- **Texto**: boas-vindas + orientação para abrir `/menu` e criar primeira wishlist.
- **Botões**: normalmente CTA para `/menu` (ou instrução textual quando botões não disponíveis).
- **Próximo passo esperado**: entrar em “➕ Criar wishlist”.

### Cenário B: usuário com wishlist
- **Texto**: reforça que já existe monitoramento ativo e indica `/menu` para gerenciamento.
- **Não deve aparecer**: pitch de venda de plano (sem pricing, sem “assine já”).

### Estados de erro e UX
- Se falhar recuperação de sessão/usuário, retornar mensagem genérica com instrução para repetir `/menu`.
- UX: manter mensagem curta; onboarding detalhado vai para `/help`.

## 5. /menu principal
### Entrada
- Comando `/menu` ou retorno por botão “Voltar”.

### Menu Free (com Upgrade)
Botões:
1. ➕ Criar wishlist
2. 🎯 Minhas wishlists
3. ⭐ Rastreados
4. 🔎 Buscar anúncio
5. 🚀 Upgrade Premium
6. ❓ Ajuda

### Menu Premium (sem Upgrade)
Mesmos botões, exceto “🚀 Upgrade Premium”.

### Ação de cada botão
- **Criar wishlist**: inicia fluxo guiado de criação.
- **Minhas wishlists**: lista buscas e ações por contexto.
- **Rastreados**: visão agregada dos anúncios rastreados.
- **Buscar anúncio**: orienta uso de `/buscar` para consulta pontual.
- **Upgrade Premium**: abre oferta mensal/anual (somente Free).
- **Ajuda**: mostra comandos e conceitos.

### Estados de erro
- Callback antigo/inválido: “Opção inválida. Use /menu novamente.”
- Edit falhar: fallback para enviar nova mensagem.

## 6. Criar wishlist (fluxo guiado)
### Entrada
- Clique em “➕ Criar wishlist”.

### Passo 1 — texto inicial
- Bot pede texto da busca (ex.: `civic si`, `corolla 2018`).

### Passo 2 — interpretação da busca
- **Busca simples**: salva query sem diretivas.
- **Busca com filtros implícitos**: detecta termos como “até 90k”, “a partir de 2018” e prepara filtros.

### Passo 3 — decisão
- **Criar agora**: confirma e cria wishlist imediatamente.
- **Adicionar filtros antes de criar**: abre subfluxo de filtros.

### Cancelar
- `/cancelar` ou botão equivalente encerra sessão e limpa rascunho.

### Erros
- Sessão expirada: orientar reabertura pelo `/menu`.
- Entrada inválida: pedir reformulação com exemplos.

## 7. Filtros no fluxo de criação
### Estrutura geral
Para cada filtro, o bot mostra:
- prompt objetivo,
- exemplos aceitos,
- interpretação esperada,
- mensagem de erro amigável.

### Preço
- **Prompt**: “Qual preço? Ex.: até 150000, entre 70000 e 90000”.
- **Interpretação**: `lte`, `gte` ou faixa (`between`).
- **Erro**: valor não numérico → pedir novo valor.

### Ano
- **Prompt**: “Qual ano? Ex.: 2018, até 2021, entre 2017 e 2021”.
- **Interpretação**: `year eq/gte/lte/between`.
- **Erro**: ano fora do padrão (4 dígitos).

### KM
- **Prompt**: “Qual quilometragem? Ex.: até 90000, entre 30000 e 100000”.
- **Interpretação**: normaliza números com/sem separadores.
- **Erro**: valor inválido.

### Cidade
- **Prompt**: “Qual cidade? Ex.: São Paulo”.
- **Interpretação**: `city eq <valor normalizado>`.

### Estado
- **Prompt**: “Qual estado? Ex.: SP ou São Paulo”.
- **Interpretação**: converte para UF quando possível.

### Regra de substituição
- Novo filtro do mesmo grupo substitui/atualiza o anterior do grupo para evitar conflito.

### Navegação
- **Voltar**: retorna à tela de filtros.
- **Concluir e criar**: persiste wishlist + filtros.

### Estados vazios e erro
- Sem filtro: mostrar “Nenhum filtro adicionado ainda”.
- Sessão expirada/callback antigo: instruir recomeço no `/menu`.

## 8. Minhas wishlists
### Entrada
- Botão “🎯 Minhas wishlists”.

### Texto esperado
- Lista numerada com query, status, filtros e indicadores de rastreados/notificações.

### Cenários
- **Sem filtros**: exibir “Nenhum filtro”.
- **Com filtros reais**: renderizar labels amigáveis.
- **Muitos filtros**: manter truncamento seguro + clareza.

### Botões
- 🗑️ Remover wishlist
- ⭐ Rastreados
- ↩️ Voltar

### Erros
- Sem wishlist: orientar criação (`/wishlist_add` ou menu).

## 9. Remover wishlist
1. **Lista**: usuário escolhe item da lista.
2. **Confirmação**: mensagem explícita sobre remoção de vínculos.
3. **Sucesso**: “Wishlist removida.”
4. **Erro**: wishlist inexistente/fora da conta.
5. **Voltar**: retorna para “Minhas wishlists”.

## 10. Rastreados
### Entrada
- Via menu principal “⭐ Rastreados” ou dentro de “Minhas wishlists”.

### Estados
- **Slots vazios**: mostrar placeholders `(vazio)`.
- **Slots preenchidos**: listar anúncio e status básico.

### Regras de plano
- **Free**: limite total menor e sem automação completa.
- **Premium**: mais rastreados totais + automações ativas.

### Limites/erro
- Ao atingir limite, orientar upgrade (quando Free) ou remoção de slot.

## 11. /buscar
### Entrada
- `/buscar <termo>`

### Resposta imediata
- Bot confirma recebimento e informa processamento.

### Resultado
- Lista de anúncios relevantes para aquela execução.

### Sem resultado
- Mensagem neutra, com sugestão de ajustar termo/fonte.

### Erro
- Mensagem genérica sem stacktrace para usuário.

### O que **não** faz
- Não cria wishlist.
- Não inicia rastreamento automático.

## 12. /plan
### Free
- Exibe plano Free, uso real (`wishlists X/2`, `rastreados Y/1`, `5 notificações`).
- Mostra CTA para `/upgrade`.

### Premium vigente
- Exibe “Plano atual: Premium”.
- Exibe validade (`Válido até: DD/MM/YYYY`) quando houver.
- Exibe uso real (`X/10`, `Y/5`, `15 notificações`).
- Exibe “Renovação: manual”.

### Premium vencido
- Deve cair para Free automaticamente (sem expor premium expirado como ativo).

## 13. /upgrade
### Oferta
- Mensal: de R$ 9,99 por R$ 5,99/mês.
- Anual: de R$ 89,99 por R$ 59,99/ano (equivale a R$ 4,99/mês).

### Com links configurados
- Botões:
  - 💳 Assinar Mensal
  - 💳 Assinar Anual

### Sem links configurados
- Exibe fallback: admin ainda precisa configurar links.

### Instrução operacional
- Usuário paga no link e envia comprovante no Telegram.
- Ativação manual por admin.
- **Não existe webhook automático neste MVP**.

## 14. CTAs Premium
### Onde aparece
- `/menu` de usuário Free.
- `/plan` de usuário Free.
- Mensagens de limite de wishlists/rastreados/notificações.

### Onde não aparece
- `/start`.
- Usuário Premium vigente.
- Resultado normal de busca sem contexto de limite.

## 15. Ativação Premium manual
Fluxo desejado (operação):
1. usuário escolhe plano;
2. paga no link;
3. envia comprovante no chat;
4. admin valida e ativa assinatura;
5. define período (`current_period_start/end`);
6. `/plan` passa a refletir validade.

Status: parcialmente implementado (sem webhook e sem autoaprovação).

## 16. /help
- Serve como catálogo de comandos e exemplos.
- Útil para usuário avançado; para iniciante, `/menu` continua principal.
- Oportunidade: reduzir densidade técnica e separar “básico” de “avançado”.

## 17. Comandos avançados (não-main-path)
- `/wishlist`
- `/wishlist_add`
- `/wishlist_remove`
- `/wishlist_filter_add`
- `/wishlist_filter_list`
- `/wishlist_track_list`
- `/admin...` e administrativos correlatos

## 18. Estados globais de erro
- Sessão expirada.
- Callback antigo/inválido.
- Usuário sem wishlist.
- Limite atingido (wishlists/rastreados/notificações).
- Erro genérico de operação.
- Pagamento não configurado.
- Permissão negada (áreas admin).

## 19. Checklist para especialista UX
- “Wishlist” deveria virar “Busca salva” para leigos?
- Usuário entende diferença entre busca manual e wishlist?
- Usuário entende filtros antes da criação?
- O upgrade aparece no timing correto?
- O Free entrega valor sem frustrar cedo demais?
- Premium está claro em benefícios e limites?
- Pagamento manual transmite confiança suficiente?
- Há excesso de comandos visíveis?
- Há excesso de botões por tela?
- Textos têm termos técnicos desnecessários?
- Ações destrutivas têm confirmação clara?

## 20. Lacunas conhecidas
- Pagamento manual (sem webhook Mercado Pago).
- Ativação Premium depende de processo administrativo manual.
- Expiração automática total ainda depende de rotina operacional consistente.
- `/buscar` roda em background e exige robustez de fila/retentativa para ambientes degradados.
- Ainda há espaço para padronizar mensagens de erro em linguagem mais didática.
