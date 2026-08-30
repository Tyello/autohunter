# PR5 — Handlers do bot: fluxo "buscar agora" novo (facetas → refinar → top-10 → zero-resultado)

`[spec-kit: T3 — 9pts: arquivos=2 (1 arquivo novo de handlers + wiring em app/bot/handlers.py), decisões=2 (UX de drill-down, ponto de entrada), risco=2 (toca fluxo de bot, mas via novo comando isolado — não altera /buscar em produção nesta PR), novidade=2 (subsistema conversacional novo), verif=1 (testável com mocks de update/context do PTB)]`

Ref: `docs/DESIGN_BUSCAR_AGORA.md` seção 6, PR5. Depende de PR3 (`specs/017`, aprovado — `app/services/facet_search_service.py`). **Não depende de PR2** (índices são otimização) **nem de PR4** (liveness checker, bloqueado em dados empíricos do usuário).

**Decisão do usuário (via AskUserQuestion) sobre a transição de conversa (seção 1.2 do design doc):** opção (b) — helper compartilhado. Especificamente: **reaproveitar as FUNÇÕES de callback já existentes do fluxo de criar wishlist (`cb_menu_create_wishlist`, `_show_create_wishlist_summary_screen`, `build_draft_filter_groups`) importando-as para dentro da NOVA `ConversationHandler` desta PR, sem modificar `app/bot/handlers.py`'s `menu_create_wishlist_conversation()` existente.** Isso evita duplicar lógica de renderização E evita qualquer edição no `ConversationHandler` de produção já em uso — o reentry funciona porque a busca-facetada absorve o resto do fluxo de criação usando os mesmos handlers, dentro da SUA PRÓPRIA `ConversationHandler`.

## Objetivo
Nova `ConversationHandler` que implementa o fluxo de 5 passos: usuário digita um termo → sistema mostra contagens por faceta (via `compute_facet_counts`) → usuário refina clicando numa faceta/bucket → sistema mostra top-10 anúncios que batem → se zero resultado com filtro válido, oferece criar alerta pré-preenchido (reentry no fluxo de wishlist).

**Ponto de entrada desta PR: comando novo `/buscar_agora`** (não o `/buscar` de produção). Isso isola o fluxo novo para validação sem risco ao `/buscar` já em uso — o cutover (substituir `/buscar` por este fluxo) é o PR6, explicitamente separado, com sua própria decisão de produto já registrada ("Só banco, sem fallback").

## Não-objetivos
- Não altera `/buscar`, `cmd_buscar`, `quick_search_conversation`, `start_manual_search_flow` ou `manual_search()` — tudo isso é tocado só no PR6.
- Não modifica `menu_create_wishlist_conversation()` nem qualquer função dentro dela — só as reaproveita por import.
- Não busca anúncios reais via scrape ao vivo — só lê do banco (`facet_search_service` + uma query de listagem simples).
- Não implementa liveness check (PR4) — os resultados exibidos são os que já estão no banco, sem verificação de "anúncio ainda existe".

## Decisões tomadas
- **Arquivo novo**: `app/bot/handlers_buscar_agora.py` — conversation handler completa isolada, sem misturar com `handlers_core.py`/`handlers.py` além dos imports necessários.
- **Estados da conversa** (constantes `int`, sequenciais, não colidem com as de `handlers_core.py` — usar um range alto, ex. `9000+`, para evitar colisão acidental):
  - `BUSCAR_AGORA_TERM` — aguardando o texto do termo de busca.
  - `BUSCAR_AGORA_FACETS` — mostrando contagens por faceta, aguardando clique numa faceta/bucket ou "ver os 10 primeiros".
  - `MENU_CREATE_WISHLIST_QUERY` — **reaproveitado literalmente** (mesmo valor da constante já definida em `handlers_core.py`, importado de lá, não redefinido) para o passo de reentry — os handlers desse estado são os MESMOS objetos de `handlers_core.py` (`cb_menu_create_wishlist` etc.), então o valor de retorno deles (que já é `MENU_CREATE_WISHLIST_QUERY` ou `ConversationHandler.END`) funciona sem adaptação.
- **Entry point**: `CommandHandler("buscar_agora", cmd_buscar_agora)` → pede o termo (ou aceita `/buscar_agora <termo>` direto, mesmo padrão de `cmd_buscar` que já aceita args).
- **Passo 1 (termo → facetas)**: chama `facet_search_service.compute_facet_counts(db, term)`. Guarda `term` em `context.user_data["buscar_agora_term"]`.
  - Se `__total__.count == 0`: pula direto para o passo de zero-resultado (abaixo), sem mostrar tela de facetas vazia.
  - Senão: renderiza um teclado inline com até 8 botões (uma linha por faceta com resultado não-vazio, rótulo = nome da faceta + top-1 bucket + contagem, ex. "📍 Estado: SP (42)"), mais um botão fixo "Ver os 10 primeiros" e um "Cancelar". `callback_data` por botão: `BAG:FACET:<facet>:<bucket>` (bucket urlencoded/truncado se necessário) para aplicar aquele filtro extra, ou `BAG:TOP10` para pular direto à listagem.
- **Passo 2 (refinar)**: ao clicar `BAG:FACET:<facet>:<bucket>`, adiciona esse filtro (campo+valor exato, operador `eq` para categóricos, ou intervalo do bucket para numéricos — reconstruído a partir do MESMO mapeamento de buckets de `facet_search_service`) à lista de filtros acumulados em `context.user_data["buscar_agora_extra_filters"]`, e re-roda `compute_facet_counts` com o termo + filtros acumulados, re-renderizando a tela de facetas (permite refinar mais de uma vez). Máximo de 3 refinamentos empilhados nesta v1 (evita explosão de combinações raras sem estoque); ao atingir o limite, o botão de facetas adicionais é omitido e só resta "Ver os 10 primeiros"/"Cancelar".
- **Passo 3 (top-10)**: ao clicar `BAG:TOP10`, roda uma query de listagem simples reaproveitando `facet_search_service.build_search_conditions(term)` + os filtros acumulados do passo 2, mais o predicado `status != 'inativo'`, `ORDER BY created_at DESC LIMIT 10`. Renderiza cada resultado como já é feito em `start_manual_search_flow` (reaproveitar o formatter de card de anúncio existente — localizar a função de formatação usada lá e importá-la, não duplicar). Fim da conversa (`ConversationHandler.END`) após mostrar os 10.
- **Passo 4 (zero-resultado → reentry)**: se em qualquer ponto o total for 0:
  - Popula exatamente os `user_data` keys que `menu_create_wishlist_on_text`/`_show_create_wishlist_summary_screen` esperam: `context.user_data["menu_create_wishlist_query"] = term`, `context.user_data["menu_create_wishlist_draft_filters"] = build_draft_filter_groups(filtros_acumulados)` (filtros acumulados = os extraídos de `build_search_conditions` + os de refinamento manual, todos como objetos com `.field/.operator/.value` — se o filtro de refinamento por faceta categórica não tiver essa forma, construir um objeto/namedtuple leve compatível), `context.user_data["menu_create_wishlist_include_auctions"] = False` (default seguro).
  - Chama `_show_create_wishlist_summary_screen(update, context)` (importado de `handlers_core.py`) e retorna o valor que ela retorna (`MENU_CREATE_WISHLIST_QUERY`).
  - A partir daqui, os handlers do estado `MENU_CREATE_WISHLIST_QUERY` na `ConversationHandler` desta PR **são literalmente os mesmos objetos de função** de `menu_create_wishlist_conversation()` em `handlers.py` (`cb_menu_create_wishlist` para os callbacks `CWL:*`, e o `MessageHandler` de texto se houver edição de query nessa tela — checar o que `menu_create_wishlist_conversation()` registra para esse estado e replicar a mesma lista de handlers, por import, na nova conversa).
- **Termo sujo/sem match** (zero resultado mas SEM nenhum filtro válido extraído, ou seja `build_search_conditions` não conseguiu extrair nada e o termo residual também não bate com nada): **não oferece alerta** — mostra mensagem de orientação genérica ("Não encontrei nada com esse termo. Tente ser mais específico, ex: civic 2019 até 80000 sp") e encerra a conversa. Distinção: "zero resultado com filtro válido" (oferece alerta) vs "termo sujo sem filtro nenhum extraído" (só orienta) é decidida por `len(filtros_acumulados_ou_extraidos) > 0`.
- **Cancelamento**: `/cancelar`, `/cancel`, e um botão `BAG:CANCEL` em toda tela — mesmo padrão de `quick_search_cancel`.

## Arquivos e mudanças
1. **Novo** `app/bot/handlers_buscar_agora.py`:
   - Constantes de estado (`BUSCAR_AGORA_TERM`, `BUSCAR_AGORA_FACETS`), import de `MENU_CREATE_WISHLIST_QUERY` de `handlers_core.py`.
   - `cmd_buscar_agora`, `buscar_agora_on_term`, `cb_buscar_agora_facet`, `cb_buscar_agora_top10`, `buscar_agora_cancel`.
   - `def buscar_agora_conversation() -> ConversationHandler` — monta a `ConversationHandler` com os 3 estados, reaproveitando os handlers de `MENU_CREATE_WISHLIST_QUERY` por import direto (sem redefinir).
2. **`app/bot/handlers.py`** (ou onde a `Application` registra os handlers — localizar o `application.add_handler(quick_search_conversation())` existente e replicar ao lado): adicionar `application.add_handler(buscar_agora_conversation())`. **Única linha tocada em arquivo de produção — mudança aditiva, não remove nem reordena handlers existentes.**
3. **Novo** `tests/test_handlers_buscar_agora.py`.

## Critérios de aceitação (EARS)
- **REQ-001**: QUANDO o usuário envia `/buscar_agora <termo>` com resultado não-zero, O sistema DEVE mostrar um teclado com as facetas de maior contagem.
- **REQ-002**: QUANDO o usuário clica numa faceta/bucket, O sistema DEVE reaplicar `compute_facet_counts` com esse filtro adicional e mostrar a tela atualizada.
- **REQ-003**: QUANDO o usuário clica "Ver os 10 primeiros", O sistema DEVE mostrar até 10 anúncios que satisfazem o termo + filtros acumulados, ordenados por mais recente, e encerrar a conversa.
- **REQ-004**: QUANDO o total é zero E havia ao menos um filtro válido extraído/acumulado, O sistema DEVE oferecer a tela de criar alerta pré-preenchida com esses filtros (reentry via `_show_create_wishlist_summary_screen`).
- **REQ-005**: QUANDO o total é zero E nenhum filtro válido foi extraído/acumulado, O sistema NÃO DEVE oferecer alerta — apenas orientação de refinar o termo.
- **REQ-006**: O sistema NÃO DEVE modificar nenhuma linha de `menu_create_wishlist_conversation()`, `cmd_buscar`, `quick_search_conversation`, ou `start_manual_search_flow`.
- **REQ-007**: Confirmar via alerta pré-preenchido DEVE resultar numa wishlist criada com os mesmos filtros mostrados na tela (mesmo caminho de código de produção, não uma cópia).

## Etapas (ordem de execução, cada uma validada e revisada antes da próxima)

1. **[não sensível]** Criar `app/bot/handlers_buscar_agora.py` com os passos 1-3 (termo → facetas → refinar → top-10), SEM o passo 4 de reentry ainda (esse passo, se não houver filtro/zero resultado, por ora só mostra a mensagem de orientação genérica das duas situações). Formatter de card de anúncio: localizar a função usada em `start_manual_search_flow`/`_run_manual_search_sync` para renderizar cada resultado e reaproveitá-la por import — se não existir uma função isolada (a formatação estiver inline), **escalar** (decisão residual: extrair um helper vs. duplicar por enquanto — não decidir sozinho).
   **Validação**: `tests/test_handlers_buscar_agora.py` cobrindo passos 1-3 com mocks de `Update`/`Context` do PTB e um `db` de fixture com `car_listings` variados.

2. **[sensível]** Adicionar o passo 4 (reentry): popular os `user_data` keys, chamar `_show_create_wishlist_summary_screen`, e wire nos handlers de `MENU_CREATE_WISHLIST_QUERY` reaproveitados por import de `handlers_core.py`/`handlers.py`. Marcado `[sensível]` porque, mesmo sem editar o arquivo de produção, esta etapa cria um SEGUNDO ponto de entrada para as mesmas funções de callback (`cb_menu_create_wishlist` etc.) — precisa de revisão cuidadosa para confirmar que reaproveitar essas funções em um `ConversationHandler` diferente não quebra suposições internas delas (ex. alguma delas assume que só `menu_create_wishlist_conversation()` a chama, ou lê algum estado que só existe se o usuário veio pelo caminho `MENU:CREATE_WISHLIST`).
   **Validação**: teste de integração cobrindo os 3 caminhos do "Plano de teste" abaixo.

3. **[não sensível]** Registrar `buscar_agora_conversation()` na `Application` (uma linha aditiva em `app/bot/handlers.py` ou onde os handlers são registrados).
   **Validação**: `.venv/Scripts/python.exe -c "from app.bot.handlers_buscar_agora import buscar_agora_conversation; buscar_agora_conversation()"` não levanta exceção; suíte completa de testes do bot (`tests/test_handlers*.py`) continua verde.

## Condições de escalação
- Se `menu_create_wishlist_conversation()` (ou os handlers que ela registra para o estado `MENU_CREATE_WISHLIST_QUERY`) tiver mudado de forma incompatível com o descrito aqui (funções renomeadas, assinatura diferente) — ler o arquivo atual e reportar divergência antes de prosseguir.
- Se não existir uma função isolada de formatação de card de anúncio reaproveitável (etapa 1) — escalar, não duplicar por conta própria.
- Se `cb_menu_create_wishlist` ou `_show_create_wishlist_summary_screen` acessarem algum `user_data`/`bot_data` que só faz sentido no fluxo original de `MENU:CREATE_WISHLIST` (ex. algo setado só por `cb_menu` antes de chamar `cb_menu_create_wishlist`) — escalar antes de reaproveitar (etapa 2, é exatamente o risco que a etapa marca como `[sensível]`).

## Plano de teste
`tests/test_handlers_buscar_agora.py`, usando mocks de `telegram.Update`/`telegram.ext.ContextTypes.DEFAULT_TYPE` (checar o padrão de mock já usado em `tests/test_handlers*.py` existentes e seguir o mesmo):
- Termo com estoque → tela de facetas aparece com botões corretos.
- Clique numa faceta → contagens recalculadas com filtro extra.
- Clique "ver os 10 primeiros" → até 10 resultados corretos, ordenados por `created_at DESC`.
- Zero resultado COM filtro válido (ex. termo "civic acima de 500000") → tela de criar alerta aparece, pré-preenchida; confirmar → wishlist criada com os filtros certos (mesmo código de `cb_menu_create_wishlist`).
- Zero resultado SEM filtro válido (termo sujo, ex. "asdkjf") → mensagem de orientação, sem oferecer alerta.
- `/cancelar` em qualquer estado → conversa encerra sem side-effects.
- Comando: `.venv/Scripts/python.exe -m pytest tests/test_handlers_buscar_agora.py -v`.

## Decisões adicionais pré-Etapa 2 (resolvidas antes do dispatch, evitam escalação)

Investigação direta de `app/bot/handlers_core.py` confirmou:
- Estado `MENU_CREATE_WISHLIST_QUERY` (linha ~1391) registra exatamente 3 handlers: `CallbackQueryHandler(cb_menu_create_wishlist, pattern=r"^(CWL:...)$")`, `MessageHandler(filters.TEXT & ~filters.COMMAND, menu_create_wishlist_on_text)`, `MessageHandler(filters.COMMAND, menu_create_wishlist_cancel)`.
- **Reaproveitamento sem duplicar regex**: em vez de reimportar cada handler e retiplicar o pattern `CWL:...` (risco de desalinhar se `handlers_core.py` mudar), a nova `buscar_agora_conversation()` DEVE obter a lista pronta assim: `_wishlist_query_handlers = menu_create_wishlist_conversation().states[MENU_CREATE_WISHLIST_QUERY]` (calculado uma vez, no nível do módulo, importando `menu_create_wishlist_conversation` de `app.bot.handlers_core`), e usar `MENU_CREATE_WISHLIST_QUERY: _wishlist_query_handlers` diretamente no dict `states={}` da conversa nova. Isso NÃO cria uma segunda instância do `ConversationHandler` de produção nem o registra em lugar nenhum — só lê a lista de handlers já construída dele. Zero duplicação de regex, zero risco de drift.
- **Confirmado sem risco**: `cb_menu`, `_show_create_wishlist_summary_screen` e `menu_create_wishlist_on_text` NÃO dependem de nenhum `user_data`/`bot_data` setado exclusivamente pelo caminho `MENU:CREATE_WISHLIST` — `cb_menu` (linha 464-469) só mostra um texto e retorna o estado, sem popular nada; `_show_create_wishlist_summary_screen` (linha 303) só lê `menu_create_wishlist_query`/`_draft_filters`/`_include_auctions` via `.get(...)` com defaults seguros. Condição de escalação da Etapa 2 sobre esse ponto: **resolvida, não escalar**.
- **Filtros de refinamento por faceta → formato `NormalizedWishlistFilter`-compatível para `build_draft_filter_groups`**: `build_draft_filter_groups` espera objetos com atributos `.field`/`.operator`/`.value` (não dicts). Os filtros acumulados por clique de faceta hoje só existem como condições SQLAlchemy (`context.user_data["buscar_agora_extra_filters"]`), que não têm essa forma. Decisão: criar uma NOVA função `_bucket_to_filter_descriptors(facet: str, bucket: str) -> list` espelhando `_bucket_to_condition`, retornando `types.SimpleNamespace(field=..., operator=..., value=...)` (valores sempre `str`, mesma convenção de `NormalizedWishlistFilter`):
  - Categóricos (`state`, `city`, `color`, `body_type`, `make`, `model`) e `doors`: um único descritor `field=<facet>, operator="eq", value=<bucket>`.
  - `year` (limites já usados em `_year_bucket_expr`, que são **inclusivos** — `<=`): `"< 2010"` → `[(year, lt, "2010")]`; `"2010-2014"` → `[(year, gte, "2010"), (year, lte, "2014")]`; `"2015-2019"` → `[(year, gte, "2015"), (year, lte, "2019")]`; `"2020-2024"` → `[(year, gte, "2020"), (year, lte, "2024")]`; `"2025+"` → `[(year, gte, "2025")]`.
  - `price`/`mileage_km` (limites **exclusivos no topo** — `<`, já corrigido na Etapa 1): `"< 20.000"` → `[(price, lt, "20000")]`; `"20.000-39.999"` → `[(price, gte, "20000"), (price, lt, "40000")]` (e assim por diante para as demais faixas, upper sempre `lt`); `"150.000+"` → `[(price, gte, "150000")]`. Mesmo padrão para `mileage_km` (mesmos nomes de operador, valores sem o sufixo " km").
  - Ao clicar uma faceta em `cb_buscar_agora_facet`, além de acumular em `buscar_agora_extra_filters` (condições SQL, como já faz), acumular também em `context.user_data["buscar_agora_extra_filters_struct"]` (lista de `SimpleNamespace`) usando `_bucket_to_filter_descriptors`.
- **Montagem do reentry** (`cb_buscar_agora_create_alert`, nova função, chamada pelo botão descrito abaixo): `parsed = parse_wishlist_query_with_implicit_filters(term)`; `all_filters = list(parsed.filters) + context.user_data.get("buscar_agora_extra_filters_struct", [])`; `context.user_data["menu_create_wishlist_query"] = parsed.cleaned_query` (não o `term` cru — mesma convenção de `menu_create_wishlist_on_text`, linha 1096); `context.user_data["menu_create_wishlist_draft_filters"] = build_draft_filter_groups(all_filters)`; `context.user_data["menu_create_wishlist_include_auctions"] = False`; `return await _show_create_wishlist_summary_screen(update, context)`.
- **Botão de oferta de alerta**: quando o total for 0 E `len(parsed.filters) + len(buscar_agora_extra_filters_struct) > 0` (filtro válido existe), renderizar uma tela com dois botões: `🔔 Criar alerta para essa busca` (`callback_data="BUSCAR_AGORA:CREATE_ALERT"`) e `❌ Cancelar` (`callback_data="BUSCAR_AGORA:CANCEL"`, já tratado por `buscar_agora_cancel` existente). Isso se aplica em DOIS pontos: (a) `buscar_agora_on_term` quando o total já vem zero na primeira consulta (hoje essa função só manda mensagem genérica e encerra — trocar por essa tela quando houver filtro válido, MAS retornar `BUSCAR_AGORA_FACETS`, não encerrar, para que o clique no botão seja capturado); (b) `cb_buscar_agora_facet` quando o recompute após um refinamento zera o total (hoje ela não trata esse caso — adicionar a checagem de total==0 ali e mostrar a mesma tela). Se total==0 SEM filtro válido (nem termo extraiu nada, nem há refinamento acumulado): manter a mensagem genérica atual, sem o botão de alerta, e encerrar a conversa normalmente.
- **Novo handler registrado em `BUSCAR_AGORA_FACETS`**: `CallbackQueryHandler(cb_buscar_agora_create_alert, pattern=r"^BUSCAR_AGORA:CREATE_ALERT$")`.
- **Novo estado no dict `states={}`**: `MENU_CREATE_WISHLIST_QUERY: _wishlist_query_handlers` (ver acima — lista obtida de `menu_create_wishlist_conversation().states[MENU_CREATE_WISHLIST_QUERY]`, não redigitada).

## Desvio de escopo na Etapa 1 (registrado)

O executor da Etapa 1 também registrou `buscar_agora_conversation()` em `app/bot/run.py` (import + `application.add_handler(...)`, aditivo, ao lado do registro de `quick_search_conversation()`), embora essa tarefa fosse formalmente da Etapa 3. Mudança é de fato idêntica ao que a Etapa 3 pediria, é puramente aditiva (não reordena/remove handlers existentes) e não afeta nenhum outro fluxo. Aceito sem retrabalho — Etapa 3 desta spec fica reduzida a apenas confirmar/validar esse registro, não repeti-lo.

## Premissas assumidas
- **PREM-E** (resolvida via AskUserQuestion): reentry usa helper compartilhado (opção b) — reaproveitar funções de callback existentes por import, não duplicar lógica nem tocar a `ConversationHandler` de produção existente.
- **PREM-F** (residual, registrada — não bloqueante): o limite de 3 refinamentos empilhados é um valor de UX razoável, não confirmado com o usuário; ajustável depois sem migração (é só uma constante no código).
