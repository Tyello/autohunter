# Garagem Alvo / AutoHunter — Roadmap e próximos passos de leilões

Atualizado em: 2026-05-21

Este documento consolida o estado atual da frente de leilões, os próximos passos operacionais e o roadmap já mapeado para o AutoHunter/Garagem Alvo.

## 1. Objetivo da frente de leilões

A frente de leilões complementa o monitoramento tradicional de anúncios com oportunidades em leilão, inicialmente de forma controlada e segura.

Uma wishlist pode receber oportunidades de leilão quando:

- a busca tiver `include_auctions=true`;
- a source estiver habilitada;
- a source estiver `user_eligible=true`;
- o tipo do lote for permitido para usuário, hoje principalmente `car`;
- o lote for recente;
- o lote tiver URL, ano e lance compatível;
- o score textual passar o mínimo;
- o alerta não for duplicado;
- os limites por usuário/dia forem respeitados.

Regra de comunicação: lance de leilão não é preço final. Toda mensagem user-facing deve lembrar o usuário de conferir edital, taxas/comissão, documentação e vistoria.

---

## 2. Estado atual das sources de leilão

### 2.1 VIP Leilões — `vip_auctions`

Status atual:

- `production_ready`;
- `enabled=true`;
- `user_eligible=true`;
- categorias user-facing: `car`;
- única source elegível para usuário final neste momento;
- dry-run e envio manual real já suportados;
- scheduler automático real segue desligado por configuração `dry_run=true`.

Estado operacional validado:

- captura veículos reais;
- possui carros recentes;
- possui lance atual;
- possui ano;
- possui URL;
- possui imagem em parte relevante dos lotes;
- `readiness` reconhece VIP como pronta quando os dados estão recentes;
- quando os dados ficam stale, readiness bloqueia corretamente por `dados_car_insuficientes`, não por erro de configuração.

Resultado saudável esperado:

```text
/admin auctions run vip --limit 20 --enrich
/admin auctions quality vip
/admin auctions readiness
```

```text
Qualidade dados car: sim
Pronta user-facing car: sim
Motivo user-facing: ok
sources prontas piloto car: vip_auctions
```

Pendências:

- não possui `auction_end_at`;
- localização ainda não é preenchida;
- manter acompanhamento da qualidade por ciclos;
- validar match real após melhoria de scoring textual com busca `L200 Triton`.

### 2.2 Win Leilões — `win_auctions`

Status atual:

- `experimental_functional_vehicle`;
- `enabled=true`;
- `user_eligible=false`;
- não user-facing;
- funcional como source experimental de veículos.

Evolução já concluída:

- listagem de veículos descoberta em `/lotes/veiculo?tipo=veiculo&categoria_id=8`;
- listagem inicialmente parecia JS/app-like, mas foi possível extrair URLs `/item/<id>/detalhes`;
- detalhe direto funciona;
- parser classifica corretamente veículos como `car`;
- corrigido bug em que Hilux virava `real_estate`;
- corrigida extração de ano;
- corrigida localização inválida como `CAOA CHERY / CE`;
- status padrão atualizado de `functional_non_car` para `experimental_functional_vehicle`;
- source segue bloqueada para usuário final.

Exemplo validado:

```text
/admin auctions inspect win --url https://www.winleiloes.com.br/item/4042/detalhes?page=1
```

Resultado esperado:

```text
item_type: car
year: 2016
initial_bid: 66500.00
```

Estado de qualidade atual:

- captura carros reais;
- possui lance inicial;
- possui ano;
- possui imagem;
- possui início/data de leilão em parte dos lotes;
- possui status/live em parte dos lotes;
- possui current_bid em parte dos lotes;
- não possui encerramento;
- continua experimental.

Motivo de bloqueio user-facing esperado:

```text
experimental/status=experimental_functional_vehicle/user_eligible=false/sem_encerramento
```

Pendências:

- melhorar extração de `auction_end_at`, se existir;
- confirmar significado de `Data do Leilão`;
- melhorar current_bid quando houver sinal real;
- melhorar localização quando houver bloco confiável;
- manter fora do usuário até decisão explícita.

### 2.3 Mega Leilões — `mega_auctions`

Status atual:

- `experimental`;
- `enabled=true`;
- `user_eligible=false`;
- não user-facing;
- funcional como source experimental parcial.

Evolução já concluída:

- parser passou a priorizar URL semântica:
  - `/veiculos/carros/` => `car`;
  - `/veiculos/motos/` => `motorcycle`;
  - `/veiculos/caminhoes/` => `truck`;
- páginas genéricas como `/leiloes-judiciais` passaram a ser rejeitadas em novas capturas;
- hygiene histórica implementada;
- `Leiloes Judiciais` marcado como `item_type=other`, `status=invalid` e `extras.skip_reason=generic_page`;
- `/admin auctions source mega` oculta inválidos por padrão;
- `/admin auctions source mega --include-invalid` permite auditoria;
- `Direitos Sobre Carro Renault Sandero...` corrigido de `motorcycle` para `car`.

Estado de qualidade atual:

- captura carros reais;
- possui alguns lotes com lance inicial;
- possui alguns lotes com lance atual;
- possui status/live em alguns lotes;
- possui imagem em parte dos lotes;
- possui cidade/UF em parte dos lotes;
- não possui encerramento;
- não user-facing.

Motivo de bloqueio user-facing esperado:

```text
experimental/status=experimental/user_eligible=false/sem_encerramento
```

Pendências:

- descobrir/extrair encerramento;
- melhorar cobertura de imagem;
- melhorar cidade/UF;
- manter hygiene disponível para histórico;
- não liberar para usuário final sem decisão explícita.

### 2.4 Sodré Santoro — `sodre_auctions`

Status atual:

- `blocked/needs_study`;
- bloqueada por 403/Azion em acesso atual;
- não user-facing.

Decisão atual:

- não insistir com regex simples;
- não usar bypass agressivo;
- tratar como estudo específico de endpoint/acesso;
- manter fora do usuário final.

### 2.5 Superbid — `superbid_auctions`

Status atual:

- `needs_study`;
- não user-facing;
- listagem exige JS/event drilldown ou endpoint interno.

Problema conhecido:

- páginas/eventos retornam banners/imagens e não lotes finais;
- precisa estudar drilldown evento -> lotes.

### 2.6 Copart — `copart_auctions`

Status atual:

- `needs_study`;
- não user-facing;
- ainda sem implementação validada.

---

## 3. Comandos operacionais principais

### 3.1 Rodar source manualmente

```text
/admin auctions run vip --limit 20 --enrich
/admin auctions run win --limit 20 --enrich
/admin auctions run mega --limit 20 --enrich
```

Uso:

- validar captura;
- atualizar dados recentes;
- checar se source está viva;
- preparar dry-run de notificações.

### 3.2 Ver qualidade das sources

```text
/admin auctions quality
/admin auctions quality vip
/admin auctions quality win
/admin auctions quality mega
```

Campos importantes:

- `Score`;
- `Atualizados 24h`;
- `Com lance atual`;
- `Com lance inicial`;
- `Com ano`;
- `Com início`;
- `Com encerramento`;
- `Com cidade/UF`;
- `Com imagem`;
- `Open/live`;
- `Car lots`;
- `User allowed lots`;
- `Qualidade dados car`;
- `Pronta user-facing car`;
- `Motivo user-facing`;
- `Warning crítico`.

### 3.3 Ver readiness

```text
/admin auctions readiness
```

Interpretação:

- `sources elegíveis`: sources configuradas para usuário;
- `sources prontas piloto car`: sources que passam todos os gates de envio;
- `lotes car elegíveis recentes com lance`: volume recente pronto para matching;
- `user_facing=sim`: source pode gerar alerta para usuário;
- `user_facing=não`: ver motivo.

Exemplos de motivo:

```text
dados_car_insuficientes/sem_lote_car_recente/sem_lote_car_recente_com_lance
experimental/status=experimental/user_eligible=false/sem_encerramento
experimental/status=experimental_functional_vehicle/user_eligible=false/sem_encerramento
```

### 3.4 Ver lotes de uma source

```text
/admin auctions source vip
/admin auctions source win
/admin auctions source mega
```

Mega oculta inválidos por padrão:

```text
/admin auctions source mega
```

Para auditar inválidos históricos:

```text
/admin auctions source mega --include-invalid
```

### 3.5 Debug de match por wishlist

```text
/admin auctions match wishlist <id|index> --debug
```

Uso:

- entender se falhou por filtro;
- entender se falhou por tipo;
- entender se falhou por score;
- ver candidatos recentes e motivo por lote.

Motivos comuns:

```text
filters_not_matched
text_score_zero
score_below_min
item_type_not_allowed
stale_lot
duplicate
ok
```

### 3.6 Rodar notificações em dry-run

```text
/admin auctions notify-run --source vip --limit-wishlists 5
```

Resultado importante:

- `Buscas avaliadas`;
- `Buscas com match`;
- `Prévias`;
- `Score baixo`;
- `Lote antigo`;
- `Tipo bloqueado`;
- `Duplicados ignorados`;
- `Sem match`;
- `Erros`.

### 3.7 Ver amostras de dry-run

```text
/admin auctions notify-samples
```

Quando dry-run rodou, mas não houve match, a mensagem deve deixar claro que a source está operacional e que nenhuma wishlist atual bateu com os lotes recentes.

### 3.8 Envio real manual

Somente quando readiness permitir e apenas para source elegível.

Condição atual:

- VIP pode enviar manualmente quando pronta;
- Win/Mega não podem enviar para usuário;
- automático real segue desligado por `dry_run=true`.

Nunca liberar envio automático real sem validação manual prévia.

---

## 4. Decisões já tomadas

1. VIP é a única source user-facing até nova decisão explícita.
2. Win e Mega podem ter dados bons, mas isso não significa liberação para usuário.
3. Não baixar score mínimo global como workaround.
4. Melhorar matching com semântica automotiva.
5. Não copiar `initial_bid` para `current_bid`.
6. Não inventar `auction_end_at`.
7. Não apagar histórico; hygiene marca e normaliza.
8. Leilão sempre precisa de aviso de risco na mensagem user-facing.
9. Não liberar Win/Mega sem PR explícita de rollout.

---

## 5. Próximos passos imediatos

### 5.1 Validar scoring textual pós-PR de matching

Depois do deploy com a melhoria de scoring textual:

```text
/admin auctions match wishlist 6 --debug
```

Esperado para a busca `L200 Triton`:

```text
L200 TRITON 3.5 G
filtros=ok
score >= 60
motivo=ok
matched_tokens=['l200', 'triton']
missing_tokens=[]
```

Depois:

```text
/admin auctions notify-run --source vip --limit-wishlists 5
/admin auctions notify-samples
```

Esperado:

```text
Buscas com match: 1
Prévias: 1
```

### 5.2 Validar envio real manual controlado

Somente depois de preview correto.

Critérios antes de enviar real:

- readiness ok;
- preview ok;
- dedupe ok;
- mensagem user-facing correta;
- alerta vai para chat correto;
- limite diário respeitado;
- source apenas VIP.

Depois, verificar:

```text
/admin auctions notify-status
```

### 5.3 Manter scheduler automático em dry-run

Estado recomendado:

```text
AUCTION_NOTIFICATIONS_ENABLED=true
AUCTION_NOTIFICATIONS_DRY_RUN=true
```

Objetivo:

- acumular histórico de dry-run;
- validar volume;
- validar dedupe;
- validar no_match/score_below_min;
- evitar alertas reais indevidos.

---

## 6. Roadmap de leilões

### P0 — Fechamento do piloto VIP

Objetivo: validar ponta a ponta com a única source user-facing.

Itens:

1. Validar scoring textual no Raspberry.
2. Confirmar que `L200 Triton` gera preview.
3. Confirmar `notify-samples` com amostra user-facing.
4. Validar envio real manual com 1 alerta controlado.
5. Confirmar dedupe no segundo envio.
6. Confirmar `notify-status` registra envio real manual.
7. Manter automático real desligado.

Critério de conclusão:

```text
VIP gera preview e envio real manual controlado sem erro, sem duplicidade e com mensagem correta.
```

### P1 — UX operacional e diagnóstico

Objetivo: reduzir atrito para operar leilões via Telegram.

Itens:

1. Melhorar `/admin auctions source` com filtros:
   - `--cars`;
   - `--recent`;
   - `--with-bid`;
   - `--source vip`.
2. Melhorar debug de wishlist:
   - mostrar top candidato por score;
   - destacar melhor “por que não bateu”;
   - sugerir query temporária.
3. Adicionar comando de resumo rápido:
   ```text
   /admin auctions cockpit
   ```
4. Melhorar mensagens para `score_below_min`:
   - mostrar score;
   - matched/missing tokens;
   - min_score.
5. Documentar runbook de plantão.

### P2 — Win como candidata futura de piloto

Objetivo: transformar Win de experimental funcional em candidata a piloto, sem liberar automaticamente.

Itens:

1. Melhorar extração de encerramento, se existir.
2. Confirmar significado de `Data do Leilão`.
3. Melhorar current_bid com rótulos confiáveis.
4. Melhorar localização quando houver bloco confiável.
5. Medir estabilidade por vários ciclos.
6. Criar readiness específico: `win_candidate_for_pilot=true/false`.
7. Só depois avaliar `user_eligible=true` em PR separada.

### P3 — Mega como candidata futura de piloto

Objetivo: amadurecer Mega depois da hygiene histórica.

Itens:

1. Melhorar extração de encerramento.
2. Melhorar imagens.
3. Melhorar cidade/UF.
4. Continuar rejeitando páginas genéricas.
5. Rodar hygiene periodicamente em dry-run.
6. Avaliar se Mega deve ter status `experimental_functional_vehicle` quando estabilizar melhor.
7. Só depois avaliar piloto.

### P4 — Estudo de novas sources

#### Sodré

- resolver bloqueio 403/Azion;
- evitar bypass agressivo;
- estudar endpoint público ou alternativa confiável;
- manter fora até prova de estabilidade.

#### Superbid

- estudar event drilldown;
- descobrir endpoint de lotes;
- separar evento de lote;
- evitar persistir banners/eventos como lotes.

#### Copart

- estudar autenticação, termos, endpoints e bloqueios;
- avaliar custo operacional.

### P5 — Automação real controlada

Objetivo: sair de dry-run automático para envio automático real de forma segura.

Pré-condições:

- VIP estável por vários ciclos;
- dedupe validado;
- limite diário validado;
- mensagens user-facing aprovadas;
- preview e envio real manual testados;
- admin consegue pausar rapidamente.

Passos:

1. manter `AUCTION_NOTIFICATIONS_ENABLED=true`;
2. manter `AUCTION_NOTIFICATIONS_DRY_RUN=true` inicialmente;
3. acompanhar por alguns dias;
4. se saudável, testar janela curta com `AUCTION_NOTIFICATIONS_DRY_RUN=false`;
5. manter limite baixo: max por busca = 1, max usuário/dia = 3;
6. monitorar `notify-status`, `notify-samples` e `readiness`.

Rollback:

```text
AUCTION_NOTIFICATIONS_DRY_RUN=true
restart scheduler
```

---

## 7. Roadmap geral do AutoHunter / Garagem Alvo já mapeado

### 7.1 Segurança admin

Objetivo:

- garantir que apenas o chat admin tenha acesso a comandos administrativos;
- comandos `/admin`, deploy, source, notify-run real e hygiene precisam estar protegidos;
- qualquer comando de alteração real deve ter gate admin.

Itens:

- revisar handlers admin;
- testar usuário não admin;
- impedir comandos sensíveis fora do chat admin;
- registrar tentativa negada quando fizer sentido.

### 7.2 Backup e recuperação

Objetivo:

- proteger usuários, wishlists e histórico essencial.

Itens:

1. backup de `users`;
2. backup de `wishlists`;
3. backup de filtros;
4. avaliar backup de `car_listings`;
5. preservar histórico de notificações/dedupe;
6. definir rotina de restore;
7. documentar runbook.

### 7.3 Filtros avançados de wishlist

Itens já mapeados:

- filtro por cor;
- filtro por cidade;
- filtro por estado.

Diretriz:

- filtros devem funcionar para anúncios normais e, quando possível, leilões;
- se uma source não tiver cidade/UF confiável, não deve inventar;
- debug deve explicar quando filtro bloqueou.

### 7.4 Unificação de anúncios equivalentes

Objetivo:

- avaliar se anúncios equivalentes em fontes diferentes devem virar uma única notificação.

Cuidados:

- não colapsar anúncios distintos por engano;
- usar heurística conservadora;
- considerar marca/modelo/ano/preço/localização/URL/source;
- manter auditoria de por que unificou.

### 7.5 WebMotors / bloqueio anti-bot

Estado mapeado:

- source sofre bloqueio por challenge/fingerprint PerimeterX;
- Playwright puro/browser_direct não resolve de forma confiável;
- tratar como investigação de sessão assistida/bootstrap manual/storage state persistente;
- ou decisão explícita de despriorizar.

Diretriz:

- não tratar como “erro de proxy”;
- não investir em bypass agressivo;
- avaliar custo/benefício frente a sources já funcionais.

### 7.6 Documentação de arquitetura

Objetivo:

- manter documentação para qualquer LLM/Codex entender o projeto.

Itens:

1. visão do produto;
2. público-alvo;
3. canal principal: Telegram;
4. arquitetura atual;
5. comandos operacionais;
6. sources;
7. fluxos de wishlist;
8. fluxos de notificação;
9. regras de plano/free/premium;
10. leilões;
11. deploy/admin;
12. riscos conhecidos;
13. decisões já tomadas;
14. documentos antigos/depreciados.

### 7.7 Limpeza de documentação e código legado

Objetivo:

- remover documentos inúteis/depreciados;
- reduzir confusão para Codex/LLM;
- manter source of truth clara.

Critério:

- só remover após confirmar que não é referenciado;
- documentos antigos podem ser movidos para `docs/archive` antes de deletar;
- README principal deve apontar para docs atuais.

### 7.8 Publicação e crescimento

Ideia já discutida:

- usar achados do AutoHunter/Garagem Alvo para publicações em Instagram/X e afins;
- divulgar carros encontrados;
- divulgar funcionalidades;
- reforçar posicionamento como “buscador do entusiasta”.

Possível evolução futura:

- agente que sugere posts com base em achados reais;
- posts com imagem, resumo, preço/lance, link e CTA;
- fluxo admin para aprovar publicação.

---

## 8. Invariantes para próximas PRs

Qualquer PR futura da frente de leilões deve respeitar:

1. Não liberar Win/Mega para usuário final sem pedido explícito.
2. Não desligar `dry_run` automático sem validação.
3. Não baixar `AUCTION_MIN_SCORE` globalmente.
4. Não copiar `initial_bid` para `current_bid`.
5. Não inventar `auction_end_at`.
6. Não apagar histórico de lotes sem comando explícito e seguro.
7. Não mexer em VIP quando o escopo for Win/Mega, salvo teste comprovando não regressão.
8. Não alterar envio real junto com parser.
9. Não misturar melhoria de source com mudança de notificação real.
10. Sempre adicionar teste positivo real, falso positivo perigoso e debug/admin quando aplicável.

---

## 9. Estado final desejado

Curto prazo:

```text
VIP user-facing manual controlado
Win experimental funcional
Mega experimental funcional
Sodré/Superbid/Copart em estudo
Scheduler automático em dry-run
```

Médio prazo:

```text
VIP automático real com limites baixos
Win candidata a piloto
Mega candidata a piloto
diagnóstico admin maduro
matching textual robusto
```

Longo prazo:

```text
múltiplas sources confiáveis
dedupe cross-source
score por oportunidade
alertas seguros e explicáveis
painel/admin cockpit via Telegram
possível expansão para outros tipos de usados
```
