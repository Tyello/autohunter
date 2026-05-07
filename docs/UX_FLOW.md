# AutoHunter — Fluxo de Experiência do Sistema

## 1. Visão geral do produto
AutoHunter é um produto **Telegram-first** para pessoas que querem monitorar carros usados sem ficar repetindo busca manual ao longo do dia.

- **Público principal**: comprador pessoa física, normalmente comparando opções de carro por faixa de preço/ano/KM.
- **Canal principal**: Telegram (comandos + teclado inline).
- **Objetivo do usuário**: cadastrar buscas persistentes (buscas), receber anúncios e notificações, e opcionalmente rastrear anúncios específicos.
- **Wishlist (busca persistente)**: intenção de compra salva que roda continuamente no backend.
- **Busca manual (`/buscar`)**: consulta pontual “agora”, sem persistência.
- **Filtro**: regra de refinamento (preço, ano, KM, cidade, estado etc.) aplicada à busca.
- **Rastreado**: anúncio específico marcado para acompanhamento (preço/status).
- **Notificação**: mensagem enviada quando há match de busca/rastreio.

## 2. Princípios de UX
1. **Telegram-first**: UX principal depende de mensagens e callbacks, não de web app.
2. **`/menu` como hub principal**: descoberta de funcionalidades por botões.
3. **Comando rápido como fallback**: usuários avançados podem usar `/busca_*`, `/buscar` etc.
4. **Upgrade no momento de intenção/limite**: não vender no `/start`.
5. **Primeira experiência orientada por criação de busca**.
6. **Filtros antes da execução completa quando fizer sentido**.
7. **Botão nunca sem feedback**: todo callback deve responder (`q.answer`) e editar/enviar texto de forma segura.

## 3. Mapa macro de navegação
```text
/start
└── /menu
    ├── Criar busca
    │   ├── informar carro
    │   ├── criar agora
    │   └── adicionar filtros antes de criar
    ├── Minhas buscas
    │   ├── remover busca
    │   ├── rastreados
    │   └── voltar
    ├── Rastreados
    ├── Buscar agora
    ├── Upgrade Premium, somente Free
    └── Ajuda
```

## 4. /start
### Entrada do usuário
- Usuário envia `/start`.

### Cenário A: usuário sem busca
- **Texto**: boas-vindas + orientação para abrir `/menu` e criar primeira busca.
- **Botões**: normalmente CTA para `/menu` (ou instrução textual quando botões não disponíveis).
- **Próximo passo esperado**: entrar em “➕ Criar busca”.

### Cenário B: usuário com busca
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
1. ➕ Criar busca
2. 🎯 Minhas buscas
3. ⭐ Rastreados
4. 🔎 Buscar agora
5. 🚀 Upgrade Premium
6. ❓ Ajuda

### Menu Premium (sem Upgrade)
Mesmos botões, exceto “🚀 Upgrade Premium”.

### Ação de cada botão
- **Criar busca**: inicia fluxo guiado de criação.
- **Minhas buscas**: lista buscas e ações por contexto.
- **Rastreados**: visão agregada dos anúncios rastreados.
- **Buscar agora**: orienta uso de `/buscar` para consulta pontual.
- **Upgrade Premium**: abre oferta mensal/anual (somente Free).
- **Ajuda**: mostra comandos e conceitos.

### Estados de erro
- Callback antigo/inválido: “Opção inválida. Use /menu novamente.”
- Edit falhar: fallback para enviar nova mensagem.

## 6. Criar busca (fluxo guiado)
### Entrada
- Clique em “➕ Criar busca”.

### Passo 1 — texto inicial
- Bot pede texto da busca (ex.: `civic si`, `corolla 2018`).

### Passo 2 — interpretação da busca
- **Busca simples**: salva query sem diretivas.
- **Busca com filtros implícitos**: detecta termos como “até 90k”, “a partir de 2018” e prepara filtros.

### Passo 3 — decisão
- **Criar agora**: confirma e cria busca imediatamente.
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
- **Concluir e criar**: persiste busca + filtros.

### Estados vazios e erro
- Sem filtro: mostrar “Nenhum filtro adicionado ainda”.
- Sessão expirada/callback antigo: instruir recomeço no `/menu`.

## 8. Minhas buscas
### Entrada
- Botão “🎯 Minhas buscas”.

### Texto esperado
- Lista numerada com query, status, filtros e indicadores de rastreados/notificações.

### Cenários
- **Sem filtros**: exibir “Nenhum filtro”.
- **Com filtros reais**: renderizar labels amigáveis.
- **Muitos filtros**: manter truncamento seguro + clareza.

### Botões
- 🗑️ Remover busca
- ⭐ Rastreados
- ↩️ Voltar

### Erros
- Sem busca: orientar criação (`/busca_add` ou menu).

## 9. Remover busca
1. **Lista**: usuário escolhe item da lista.
2. **Confirmação**: mensagem explícita sobre remoção de vínculos.
3. **Sucesso**: “Busca removida.”
4. **Erro**: busca inexistente/fora da conta.
5. **Voltar**: retorna para “Minhas buscas”.

## 10. Rastreados
### Entrada
- Via menu principal “⭐ Rastreados” ou dentro de “Minhas buscas”.

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
- Não cria busca.
- Não inicia rastreamento automático.

## 12. /plan
### Free
- Exibe plano Free, uso real (`buscas salvas X/2`, `rastreados Y/1`, `5 notificações`).
- Mostra CTA para `/upgrade`.

### Premium vigente
- Exibe “Plano atual: Premium”.
- Exibe validade (`Válido até: DD/MM/YYYY`) quando houver.
- Exibe uso real (`X/10`, `Y/5`, `200 notificações`).
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
- Mensagens de limite de buscas/rastreados/notificações.

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
- `/busca`
- `/busca_add`
- `/busca_remove`
- `/busca_filter_add`
- `/busca_filter_list`
- `/busca_track_list`
- `/admin...` e administrativos correlatos

## 18. Estados globais de erro
- Sessão expirada.
- Callback antigo/inválido.
- Usuário sem busca.
- Limite atingido (buscas/rastreados/notificações).
- Erro genérico de operação.
- Pagamento não configurado.
- Permissão negada (áreas admin).

## 19. Checklist para especialista UX
- “Wishlist” deveria virar “Busca salva” para leigos?
- Usuário entende diferença entre busca manual e busca?
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
