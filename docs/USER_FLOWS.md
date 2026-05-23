# Garagem Alvo — Fluxos atuais de usuário

Atualizado em: 2026-05-22.

Este documento descreve os fluxos de produto hoje, pelo ponto de vista de usuário final, admin e operação. Ele complementa `README.md`, `docs/ARCHITECTURE.md` e `docs/PROJECT_GUIDELINE.md`.

## 1. Princípios de UX atuais

- Telegram é a jornada principal.
- O usuário deve conseguir começar pelo `/start` ou `/menu`.
- O fluxo guiado é o caminho recomendado; comandos legados continuam por compatibilidade.
- A copy pública deve falar **Garagem Alvo**, não AutoHunter.
- O usuário não precisa entender sources, scheduler, jobs, backoff ou scraping.
- Filtros devem reduzir ruído, não transformar a criação de busca em formulário pesado.
- Leilões exigem disclosure claro: **lance não é preço final**.

## 2. Entrada no bot

### `/start`

Cenários:

1. Usuário novo sem buscas:
   - recebe boas-vindas;
   - entende a proposta do Garagem Alvo;
   - CTA principal: criar primeira busca.

2. Usuário com buscas ativas:
   - recebe contexto de monitoramento existente;
   - quando possível, vê contexto recente de alertas nos últimos dias;
   - CTA principal: ver buscas.

3. Usuário com buscas salvas, mas todas pausadas:
   - recebe aviso de que há buscas salvas sem monitoramento ativo;
   - CTA principal: abrir buscas para reativar.

### `/menu`

Menu principal atual:

- `➕ Criar busca`
- `🎯 Minhas buscas`
- `⭐ Anúncios rastreados`
- `🔎 Buscar agora`
- `🚀 Premium` para usuários Free
- `❓ Ajuda`

O botão de upgrade é ocultado para usuário Premium.

## 3. Criar busca monitorada

Caminho recomendado:

```text
/menu -> ➕ Criar busca -> usuário informa carro/termos -> bot detecta filtros implícitos -> tela de revisão -> adicionar filtros ou criar -> primeira varredura agendada
```

Exemplos aceitos:

- `civic si`
- `golf gti manual sp`
- `audi a5 entre 2017 e 2021`
- `corolla até 120000`
- `compass diesel até 180000 em SP`

### Filtros implícitos

O texto da busca pode gerar filtros automaticamente:

- Ano:
  - `entre 2014 e 2020`
  - `2014-2020`
  - `a partir de 2017`
  - `até 2021`
- Preço:
  - `até 120000`
  - `entre 90000 e 130000`
  - `a partir de 80000`

### Filtros guiados disponíveis

No fluxo guiado, o usuário pode adicionar:

- preço/faixa;
- ano/faixa;
- quilometragem;
- cidade;
- estado.

Observação: o core aceita também filtros avançados como `color`, `source`, `seller_type`, `body_type` e `doors`, principalmente via comandos avançados/legados. Se a UX guiada for expandida, esses campos podem virar botões em uma próxima frente.

### Leilões na criação

Na tela de revisão, o usuário pode escolher se a busca aceita oportunidades de leilão.

Quando leilões estão ativados para a busca:

- o usuário faz opt-in por wishlist;
- o admin ainda controla sources/categorias/elegibilidade;
- alertas precisam avisar que lance não é preço final.

### Pós-criação

Ao confirmar:

- wishlist é persistida;
- filtros são persistidos;
- tokens são reconstruídos para matching escalável;
- primeira varredura é agendada via fila, sem scraping síncrono pesado no callback;
- usuário recebe confirmação e feedback da primeira varredura agendada.

Importante: a primeira varredura imediata hoje significa **agendamento imediato em fila**, não garantia de renderizar três anúncios no mesmo callback.

## 4. Gerenciar buscas

Caminho:

```text
/menu -> 🎯 Minhas buscas
```

A tela lista buscas com:

- status ativa/pausada;
- quantidade de filtros;
- quantidade de rastreados;
- alertas enviados hoje quando houver.

Ações:

- ajustar filtros;
- pausar busca;
- reativar busca;
- remover busca;
- ver anúncios rastreados.

### Pausar busca

Pausar mantém a busca salva, mas interrompe novos alertas enquanto estiver pausada. Busca pausada continua ocupando vaga do plano.

### Reativar busca

Reativar volta a permitir alertas quando aparecerem anúncios compatíveis.

### Remover busca

Remoção limpa explicitamente dependências conhecidas:

- filtros;
- atividade de listings;
- tokens;
- anúncios rastreados vinculados.

A remoção não deve exigir que o usuário entenda tabelas internas.

## 5. Ajustar filtros

Caminho:

```text
/menu -> 🎯 Minhas buscas -> ⚙️ Ajustar filtros
```

Ações disponíveis:

- adicionar/ajustar filtro;
- listar filtros;
- remover filtro;
- voltar para Minhas buscas.

Filtros numéricos como preço, ano e quilometragem são substituídos por campo quando ajustados via UX, evitando acumular ranges contraditórios.

## 6. Buscar agora

Caminhos:

```text
/menu -> 🔎 Buscar agora
/buscar <termos>
```

Características:

- busca pontual;
- não salva monitoramento;
- retorna até alguns anúncios quando encontrar;
- permite botão `⭐ Rastrear` nos resultados quando possível;
- recomenda criar busca salva para monitoramento contínuo.

Exemplos:

```text
/buscar civic si até 120000 sp
/buscar golf gti manual
/buscar audi a5 2018
```

## 7. Rastrear anúncios

Caminhos:

- botão `⭐ Rastrear` em alerta ou resultado de busca;
- comando avançado `/wishlist_track_add <n> <url|external_id>`.

Comportamento:

- tracking é vinculado a uma wishlist;
- cada wishlist pode ter até 3 slots;
- o plano Free tem limite total menor de rastreados;
- o Premium libera mais rastreados e alertas automáticos de queda/preço/status.

Listagem:

```text
/wishlist_track_list <n>
/menu -> ⭐ Anúncios rastreados
```

A listagem mostra:

- slot;
- título/resumo;
- preço inicial;
- preço atual;
- variação;
- status;
- última vez visto;
- se alertas automáticos estão ativos ou dependem de Premium.

## 8. Plano e upgrade

### `/plan`

Mostra:

- plano atual;
- uso de buscas salvas;
- uso de anúncios rastreados;
- limite diário de alertas;
- validade quando Premium.

### `/upgrade`

Mostra a oferta Premium e links Mercado Pago quando configurados.

Estado atual comercial:

- pagamento usa link Mercado Pago configurável;
- ativação ainda depende de validação/admin manual;
- admin pode ativar Premium por comando;
- webhook automático de pagamento ainda é uma lacuna de lançamento.

Comandos admin relacionados:

```text
/admin premium activate <chat_id> monthly
/admin premium activate <chat_id> annual
/admin premium status <chat_id>
```

## 9. Alertas de classificados

Alertas de anúncios tradicionais usam formatter central e podem incluir:

- score humanizado;
- título;
- preço;
- fonte;
- localização;
- recência;
- quilometragem;
- câmbio quando disponível;
- contexto de preço vs mediana/FIPE quando disponível;
- motivo principal;
- critérios/filtros que explicam o alerta;
- botão para abrir anúncio;
- botão para rastrear.

Contextos de preço são conservadores: quando não há base estatística confiável, o alerta não deve inventar precisão.

## 10. Alertas de queda em anúncio rastreado

Quando tracking automático está habilitado e permitido pelo plano:

- o sistema detecta queda relevante;
- respeita valor mínimo, percentual mínimo e cooldown;
- cria notificação específica;
- alerta mostra histórico resumido quando disponível.

Defaults operacionais atuais:

- queda mínima absoluta: R$ 500;
- queda mínima percentual: 1%;
- cooldown: 24h.

## 11. Digest semanal

O scheduler registra digest semanal para usuários elegíveis.

Características atuais:

- roda em cron semanal;
- considera usuários ativos com chat_id e wishlist ativa;
- lista buscas e anúncios ativos recentes quando houver;
- evita envio duplicado no mesmo dia por chave em AppKV.

Lacuna conhecida para lançamento:

- o digest ainda pode evoluir para comunicar volume monitorado, ausência de alertas, filtros que bloquearam resultados e contexto de mercado por wishlist.

## 12. Leilões

Fluxo de usuário:

```text
criar/editar busca -> ativar leilões nessa busca -> receber apenas oportunidades que passem nos gates operacionais
```

Fluxo admin:

```text
source_configs + categorias + user_eligible + readiness + samples + dry-run -> envio controlado
```

Regras obrigatórias:

- usuário opta por busca (`include_auctions`);
- admin controla source/categoria;
- no piloto, apenas `car` deve chegar ao usuário;
- motos, caminhões/pesados, imóveis e outros ficam bloqueados por padrão;
- envio automático real permanece protegido;
- todo alerta precisa dizer: `Lance não é preço final.`

## 13. Fluxos admin principais

### Saúde e operação

```text
/admin health
/admin health verbose
/admin audit
/admin sources
/admin source <source> status
/admin runall <source>
```

### Sources

Admin pode diagnosticar, habilitar/desabilitar e ajustar sources via comandos dedicados. O estado efetivo mora em `source_configs` e `source_states`.

### Deploy

Admin Deploy via Telegram existe como frente concluída, mas segue comando sensível e deve permanecer protegido por gate de admin.

### Premium

Ativação Premium é manual/admin no estado atual.

### Leilões

```text
/admin auctions readiness
/admin auctions notify-status
/admin auctions notify-samples
/admin auctions notify-run --source vip --limit-wishlists 5
/admin auctions settings
```

## 14. Fluxos legados/compatibilidade

Comandos avançados/legados continuam disponíveis para usuários técnicos e compatibilidade:

```text
/wishlist
/wishlist_add
/wishlist_remove
/wishlist_clear
/wishlist_filter_add
/wishlist_filter_list
/wishlist_filter_remove
/wishlist_track_add
/wishlist_track_list
/wishlist_track_remove
/wishlist_track_alert_on
/wishlist_track_alert_off
```

Eles não devem ser removidos sem validação de uso e atualização de testes.

## 15. Lacunas de UX/produto ainda relevantes

- Pagamento/ativação Premium sem intervenção manual.
- Métricas de produto em `/admin metrics`.
- Digest semanal mais explicativo quando não houve alerta.
- Primeira experiência ainda pode evoluir de “varredura agendada” para “resultados renderizados agora”, se tecnicamente viável sem travar o bot.
- Growth/conteúdo automático com achados ainda é frente separada.

## 16. Não objetivos

- Transformar o produto em web-first.
- Expor detalhes de scraping/sources para usuário comum.
- Liberar leilões de qualquer categoria sem gates.
- Automatizar envio real de leilões sem nova decisão explícita.
- Reescrever o fluxo de bot sem preservar compatibilidade.
