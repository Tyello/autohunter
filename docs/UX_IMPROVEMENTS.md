# Garagem Alvo — Melhorias de UX
> Baseado em análise do código real dos handlers, renderers e formatters.
> Organizado por impacto no usuário, do mais crítico ao incremental.

---

## Status de execução

Última atualização: 2026-05-22

### Concluído

- [x] 5.2 — Texto de upgrade orientado à dor
  - Implementado no PR #284.
  - O /upgrade agora comunica melhor a dor de perder boas oportunidades, sem alterar planos, preços ou pagamento.

- [x] 1.1 — Botão CTA no `/start`
  - Implementado no PR #260.
  - `/start` agora mostra CTA contextual para criar primeira busca ou ver buscas existentes.

- [x] 3.1 — Lista de buscas compacta
  - Implementado no PR #260.
  - `render_user_wishlists` passou a exibir 1 linha por busca com status, filtros, rastreados e alertas do dia.

- [x] 6.2 — Tela vazia de anúncios rastreados
  - Implementado no PR #260.
  - Quando todos os slots estão vazios, o bot mostra orientação clara para usar `⭐ Rastrear`.

- [x] 1.2 — Resultado imediato após criar busca
  - Implementado no PR #266.
  - O bot exibe o status da primeira varredura agendada via fila, sem scraping síncrono no callback.

- [x] 2.1 — Badge de recência com fallback para `created_at`
  - Implementado no PR #267.
  - Quando há data confiável de publicação, o bot mostra recência assertiva; quando só há `created_at`, mostra fallback conservador como 🆕 Novo ou 🕐 Recente.

- [x] 2.3 — Contexto mínimo garantido em todo alerta
  - Implementado no PR #269.
  - O formatter agora tenta mostrar motivo, critério ou busca em todo alerta normal, inclusive quando score é zero ou ausente.

- [x] 3.3 — Limite diário com contexto e CTA suave
  - Implementado no PR #272.
  - O aviso de limite diário agora explica o limite, contextualiza oportunidades não enviadas quando essa informação existe e conduz para Premium sem tom punitivo.

- [x] 5.1 — Barra de progresso no /plan
  - Implementado no PR #273.
  - A tela /plan agora mostra uso visual de buscas salvas e anúncios rastreados, facilitando entender proximidade dos limites.

- [x] 3.2 — "Buscar agora" inicia fluxo conversacional
  - Implementado no PR #276.
  - O botão "Buscar agora" agora pergunta o que o usuário procura e reutiliza o fluxo de /buscar para enviar os resultados.

- [x] 6.3 — Botões de sugestão nos filtros
  - Implementado no PR #278.
  - Filtros comuns como preço, ano e KM agora oferecem botões de sugestão, mantendo digitação livre para casos específicos.

- [x] 2.4 — Label de score humanizado
  - Implementado no PR #279.
  - Alertas com score agora mostram uma etiqueta curta como "Excelente oportunidade", "Forte oportunidade" ou "Boa compatibilidade", sem alterar o cálculo do score.

- [x] 1.3 — Contexto de ausência no /start
  - Implementado no PR #280.
  - Usuários que já têm buscas agora veem resumo de buscas ativas e contexto recente ao voltar pelo /start.

- [x] 6.1 — Detectar comando durante sessão aberta
  - Implementado no PR #282.
  - Comandos globais como /menu, /start e /buscar agora avisam quando existe uma ação em andamento e permitem continuar ou descartar com segurança.

- [x] 6.4 — Horário de renovação do limite diário
  - Implementado no PR #286.
  - O aviso de limite diário agora informa quando o limite renova, usando o timezone configurado.

- [x] 4.2 — Contexto histórico em queda de preço rastreado
  - Implementado no PR #288.
  - Alertas de queda de preço agora mostram contexto histórico quando disponível, como preço inicial, queda total e tempo de rastreamento.

- [x] 2.2 — Contexto de mercado quando `market_stats` está vazio
  - Implementado no PR #290.
  - Alertas com preço agora mostram contexto conservador quando não há base de mercado suficiente, sem inventar comparação.


### Próximo pacote recomendado

Revisar roadmap UX e encerrar bloco atual.
- motivo: com o item 2.2 concluído, os itens atuais estão resolvidos ou endereçados. O próximo passo é uma revisão final da documentação e definição de um novo bloco, em vez de empilhar ajustes incrementais.

---

## Como ler este documento

Cada item tem:
- **O problema** — o que acontece hoje
- **O que fazer** — implementação específica com localização no código
- **Impacto** — por que isso importa para conversão e retenção

---

## Bloco 1 — Primeiros passos (afeta todo novo usuário)

### 1.1 `/start` sem botão de ação — ✅ Concluído no PR #260

> Status: concluído no PR #260. O texto abaixo fica mantido como histórico da motivação e da solução proposta.

**O problema hoje:**
```
👋 Bem-vindo ao Garagem Alvo
...
Para começar: toque em /menu e depois em ➕ Criar busca.
```
O usuário precisa fechar a mensagem, digitar `/menu`, esperar o menu carregar, e então tocar em "Criar busca". São 3 passos extras onde cada um tem chance de abandono.

**O que fazer** — `renderers.py::render_start_text` + `handlers_core.py::cmd_start`:

```python
# cmd_start — adicionar reply_markup direto no /start
async def cmd_start(update, context):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(...)
        w = list_wishlists(db, user.id)

    if not w:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Criar minha primeira busca",
                                 callback_data="MENU:CREATE_WISHLIST")
        ]])
    else:
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎯 Ver minhas buscas",
                                 callback_data="MENU:WISHLISTS")
        ]])

    await reply_text(update, render_start_text(len(w)), reply_markup=markup)
```

**Impacto:** Remove 3 passos da jornada de onboarding. O usuário novo toca em 1 botão e já está criando busca.

---

### 1.2 Silêncio após criar busca — ✅ Concluído no PR #266

> Status: concluído no PR #266. A implementação real não executa scraping síncrono no callback; ela mostra o status da primeira varredura agendada via fila.

**O problema hoje:**
Usuário cria busca → recebe "✅ Busca criada" → espera. Pode esperar 5 minutos ou 2 horas dependendo do scheduler. Sem feedback, a pergunta óbvia é "funcionou?".

**O que foi feito** — `handlers_core.py`, após confirmar criação da wishlist:

```python
# O callback mantém execução rápida:
# - cria a wishlist
# - agenda primeira varredura via trigger_initial_run_for_wishlist(...)
# - renderiza feedback com base em initial_run_summary (triggered/failed/skipped)
# - sem scraping síncrono no callback
```

**Impacto:** Resolve o maior gap de confiança do produto. Usuário sabe que o bot funcionou.

---

### 1.3 Retorno após ausência — sem contexto do que aconteceu — ✅ Concluído no PR #280

**O problema hoje:**
Usuário some por 3 dias e manda `/start`. Recebe:
```
👋 Garagem Alvo
Seu monitoramento já está ativo.
Use /menu para ver suas buscas...
```
Nenhum sinal do que aconteceu durante a ausência.

**O que fazer** — `handlers_core.py::cmd_start`, adicionar resumo contextual:

```python
async def cmd_start(update, context):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(...)
        w = list_wishlists(db, user.id)
        if w:
            # Alertas enviados nos últimos 7 dias
            recent = count_notifications_sent_last_n_days(db, user.id, days=7)
            # Anúncios monitorados ativamente
            active_tracked = count_active_tracked_listings(db, user.id)

    if w and recent > 0:
        ctx_line = f"Enviei {recent} alerta(s) para você nos últimos 7 dias."
    elif w:
        ctx_line = "Nenhum alerta esta semana — mercado calmo para suas buscas."
    else:
        ctx_line = None

    text = render_start_text(len(w), context_line=ctx_line)
    await reply_text(update, text, reply_markup=markup)
```

**Impacto:** Usuário que volta sente que o bot estava trabalhando. Aumenta percepção de valor mesmo sem ter aberto o app.

---

## Bloco 2 — Notificação de alerta (o momento mais importante do produto)

### 2.1 Badge de recência invisível para a maioria dos alertas

> Status: concluído no PR #267. Quando a fonte informa data confiável de publicação, o bot mostra recência assertiva; quando só há `created_at`, mostra fallback conservador como 🆕 Novo ou 🕐 Recente.

**O problema hoje:**
`build_recency_badge` só mostra "⏱️ Há 2h" quando `published_at_reliable=True` nos `extras` do listing. A maioria das fontes não seta esse flag. Resultado: o badge temporal — que é um dos argumentos mais fortes do produto ("chegou antes de todo mundo") — aparece em uma fração dos alertas.

**O que fazer** — `telegram_formatter.py::build_recency_badge`:

```python
def build_recency_badge(ad: Any) -> str | None:
    extras = getattr(ad, "extras", None) or {}
    
    candidates = [
        getattr(ad, "published_at", None),
        extras.get("published_at") if isinstance(extras, dict) else None,
        getattr(ad, "created_at", None),  # fallback: quando o sistema viu
    ]
    
    dt = None
    is_reliable = bool(
        extras.get("published_at_reliable") or
        extras.get("is_fresh_reliable") or
        extras.get("published_at")  # se a fonte enviou a data, confiar
    )
    
    for c in candidates:
        dt = _parse_datetime(c)
        if dt:
            break
    
    if not dt:
        return None

    # Se só temos created_at (quando o sistema viu), usar com label diferente
    if not is_reliable:
        # Usar created_at como "visto há X" — menos preciso mas útil
        now = datetime.now(timezone.utc)
        diff = now - dt
        hours = int(diff.total_seconds() // 3600)
        if hours < 2:
            return "🆕 Novo"       # recém ingerido
        if hours < 6:
            return "🕐 Recente"   # sem afirmar hora exata
        return None               # mais de 6h: não vale mostrar

    # Com data confiável: mostrar hora exata
    # ... lógica existente ...
```

**Impacto:** Badge temporal passa a aparecer na maioria dos alertas. É o argumento central do produto ("antes de todo mundo") e estava invisível.

---

### 2.2 Contexto de mercado ausente quando `market_stats` está vazio — ✅ Concluído no PR #290

**O problema hoje:**
`build_badges` tenta mostrar `💰 18% abaixo da média` via `delta_vs_median_pct` do `score_breakdown`. Mas se `market_stats_cohorts` não tem dados para aquele make/model/year, o badge não aparece. Não há fallback.

**O que fazer** — enriquecer o badge de preço com contexto relativo mesmo sem stats de mercado:

```python
def build_price_context_badge(ad: Any, score_breakdown: dict) -> str | None:
    # Opção 1: delta vs mediana (quando temos market_stats)
    delta_pct = score_breakdown.get("delta_vs_median_pct")
    if delta_pct is not None:
        return _delta_badge_text(delta_pct)

    # Opção 2: delta vs FIPE (quando temos fipe_price no breakdown)
    fipe_delta = score_breakdown.get("delta_vs_fipe_pct")
    if fipe_delta is not None:
        if fipe_delta < -10:
            return f"💰 {abs(fipe_delta):.0f}% abaixo da FIPE"
        if fipe_delta > 10:
            return f"📈 {fipe_delta:.0f}% acima da FIPE"

    # Opção 3: preço absoluto como referência (sem comparação)
    # Não adicionar badge — melhor nada que dado errado
    return None
```

E alimentar `market_stats_cohorts` continuamente: toda ingestão de listing com `make + model + year + price` deve atualizar as estatísticas. Hoje isso provavelmente não acontece automaticamente.

---

### 2.3 "Por que você recebeu" invisível para matches de score baixo — ✅ Concluído no PR #269

**O problema hoje:**
```python
if score_i > 0 and (main_reason or matched_filters):
    lines.append("Por que você recebeu (resumo):")
```
Se `score_i == 0` ou `reasons` estiver vazio, o usuário não sabe por que recebeu o alerta. Para buscas sem score calculado, toda a seção de contexto desaparece.

**O que fazer** — sempre mostrar pelo menos o critério que foi atingido:

```python
# Sempre mostrar pelo menos a query que gerou o alerta
query = getattr(ad, "wishlist_query", None)
matched_filters = _compact_filters(ad)

# Bloco de contexto mínimo garantido
context_lines = []

if main_reason:
    context_lines.append(f"• {main_reason}")
elif query:
    context_lines.append(f"• Busca: {query}")

for ftxt in matched_filters:
    context_lines.append(f"• Filtro: {ftxt}")

if context_lines:
    lines.append("─────────────────")
    lines.extend(context_lines)
```

---

### 2.4 Score aparece como número cru — ✅ Concluído no PR #279

**O problema hoje:**
`🔥 73/100 — Honda Civic Si 2018` aparece no topo da notificação. O usuário não sabe o que é 73, o que significa em relação a 50, nem o que influenciou.

**O que fazer** — adicionar legenda compacta condicional:

```python
# build_score_label — nova função
def _score_label(score_i: int) -> str:
    if score_i >= 85:
        return "🔥 Excelente match"
    if score_i >= 70:
        return "✅ Bom match"
    if score_i >= 55:
        return "👍 Match razoável"
    return ""

# Em format_ad_message:
label = _score_label(score_i)
if label and score_i > 0:
    line1 = f"{label} ({score_i}/100) — {title}"
else:
    line1 = title
```

Assim o usuário entende instantaneamente: "Excelente match (87/100)" comunica muito mais que "🔥 87/100".

---

## Bloco 3 — Gestão de buscas (uso diário)

### 3.1 Lista de buscas é muro de texto — ✅ Concluído no PR #260

> Status: concluído no PR #260. O texto abaixo fica mantido como histórico da motivação e da solução proposta.

**O problema hoje:**
Cada busca na lista ocupa 7 linhas de texto (query, status, leilões, filtros, rastreados, alertas, linha em branco). Com 3 buscas, é uma mensagem de 21 linhas antes de qualquer botão.

**O que fazer** — formato compacto por busca:

```python
# render_user_wishlists — formato card por busca
def render_user_wishlists(wishlists) -> str:
    lines = ["🎯 Minhas buscas\n"]
    for item in wishlists:
        status_icon = "✅" if item.get("is_active") else "⏸️"
        filters = item.get("filters", [])
        filter_summary = f" • {len(filters)} filtro(s)" if filters else ""
        tracked = item.get("tracked_count", 0)
        tracked_summary = f" • {tracked} rastreado(s)" if tracked else ""
        alerts_today = item.get("notifications_24h_count", 0)
        alerts_summary = f" • {alerts_today} alerta(s) hoje" if alerts_today else ""

        lines.append(
            f"{status_icon} {item['index']}. {item['query']}"
            f"{filter_summary}{tracked_summary}{alerts_summary}"
        )
    lines.append("\nEscolha uma busca para gerenciar:")
    return "\n".join(lines)
```

Resultado: cada busca vira 1 linha. Com 3 buscas = 4 linhas totais. Scannable.

---

### 3.2 "Buscar agora" abre instrução de texto, não uma busca — ✅ Concluído no PR #276

**O problema hoje:**
Botão "🔎 Buscar agora" no menu principal abre:
```
Essa é uma busca pontual. Eu procuro uma vez e não salvo monitoramento.
Exemplo: /buscar civic si até 120000 sp
Para receber alertas todos os dias, use ➕ Criar busca.
```
O usuário foi no menu, tocou no botão, e recebeu uma instrução de como digitar um comando. Não há nada de interativo.

**O que fazer** — iniciar estado conversacional direto:

```python
# cb_menu handler para MENU:SEARCH
if data == "MENU:SEARCH":
    context.user_data["session"] = {"type": "quick_search"}
    await _safe_edit_or_send(
        update,
        "🔎 Busca rápida\n\nO que você procura? (ex: civic si, golf gti, wrx 2020)",
    )
    return
# Próxima mensagem do usuário é processada como termo de busca
```

---

### 3.3 Atingiu o limite diário — mensagem sem saída — ✅ Concluído no PR #272

**O problema hoje:**
```
⚠️ Você atingiu seu limite de 5 alertas hoje.
Amanhã libera de novo.
Para aumentar o limite, use /upgrade
```
É uma parede. O usuário não sabe o que não recebeu, e a menção ao `/upgrade` parece punição.

**O que fazer** — contexto + CTA suave:

```python
def send_daily_limit_notice_http(user, limit: int, missed_count: int = 0):
    missed_line = (
        f"Encontrei mais {missed_count} anúncio(s) que não foram enviados.\n"
        if missed_count > 0 else ""
    )
    text = (
        f"Você atingiu seu limite de {limit} alertas hoje.\n"
        f"{missed_line}"
        f"Amanhã o limite renova automaticamente.\n\n"
        f"Com o Premium você recebe até 200 alertas por dia por busca."
    )
    # + botão inline "Ver Premium" com callback MENU:UPGRADE
```

**Impacto:** Transforma o limite de parede em contexto. "Encontrei mais 3 que não enviei" cria urgência real para upgrade.

---

## Bloco 4 — Rastreamento de anúncios

### 4.1 Botão "⭐ Rastrear" não aparece em `/buscar` — ✅ Concluído no PR #264

**O problema hoje:**
O botão "⭐ Rastrear" aparece nos alertas automáticos (notificações), mas não nos resultados de `/buscar` (busca manual). Usuário faz busca pontual, vê um anúncio interessante, e não tem como rastrear sem voltar ao menu.

> Status: implementado no `app/bot/handlers.py` (fluxo real de `/buscar`), com callbacks compactos e seguros.
> - 1 wishlist ativa: `TRACK:ADDT:<token>`
> - múltiplas wishlists ativas: `TRACK:CHOOSE:<listing_id>` com escolha e emissão de `TRACK:ADDT:<token>`

**O que fazer** — `app/bot/handlers.py`, adicionar botão rastrear nos resultados de busca:

```python
# Para cada listing nos resultados do /buscar:
buttons = [
    [{"text": "Abrir anúncio", "url": listing.url}]
]
# Se tiver wishlist ativa, oferecer rastreamento
if user_has_active_wishlist and listing.external_id:
    buttons[0].append({
        "text": "⭐ Rastrear",
        "callback_data": f"TRACK:ADD_FROM_SEARCH:{listing.source}:{listing.external_id}"
    })

reply_markup = InlineKeyboardMarkup(buttons)
```

---

### 4.2 Mudança de preço no rastreado sem contexto histórico — ✅ Concluído no PR #288

**O problema hoje:**
O alerta de queda de preço diz "💰 Preço caiu R$ 5.000". Não mostra o histórico: quando começou a rastrear, quantas vezes o preço mudou, se está em tendência de queda.

**O que fazer** — `telegram_formatter.py`, enriquecer alerta de preço rastreado:

```python
def format_price_drop_alert(tracked, listing) -> str:
    drop_pct = abs(tracked.last_price_change_pct or 0)
    drop_abs = abs(tracked.last_price_change_amount or 0)
    
    lines = [
        f"💰 Queda de preço — {listing.title}",
        f"",
        f"Era: {_format_price_brl(tracked.initial_price)}",
        f"Agora: {_format_price_brl(listing.price)}",
        f"Queda: R$ {drop_abs:,.0f} ({drop_pct:.1f}%)",
    ]
    
    # Contexto temporal
    if tracked.created_at:
        days_tracking = (datetime.now() - tracked.created_at).days
        lines.append(f"Rastreando há {days_tracking} dia(s)")
    
    return "\n".join(lines)
```

---

## Bloco 5 — Plano e upgrade

### 5.1 `/plan` mostra números, não progresso — ✅ Concluído no PR #273

**O problema hoje:**
```
Plano: Free
Buscas: 1/2
Alertas hoje: 3/5
```
Números sem visualização. O usuário não sente o limite até bater nele.

**O que fazer** — adicionar barra de progresso simples:

```python
def _progress_bar(current: int, total: int, width: int = 10) -> str:
    filled = round((current / total) * width) if total else 0
    empty = width - filled
    pct = int((current / total) * 100) if total else 0
    return f"{'█' * filled}{'░' * empty} {current}/{total} ({pct}%)"

# Em render_plan_text:
f"Buscas: {_progress_bar(used_wishlists, max_wishlists)}\n"
f"Alertas hoje: {_progress_bar(alerts_today, daily_limit)}\n"
```

Resultado:
```
Buscas:       ████░░░░░░ 2/5 (40%)
Alertas hoje: ██░░░░░░░░ 1/5 (20%)
```

---

### 5.2 Upgrade: lista de features vs motivação real — ✅ Concluído no PR #284

**O problema hoje:**
```
Benefícios:
- até 15 buscas salvas
- até 5 anúncios rastreados no total
- alertas automáticos de preço/status
- até 200 notificações por dia por busca
```
Features como bullet list. Funciona para quem já quer comprar. Não converte quem está em dúvida.

**O que fazer** — texto orientado à dor:

```python
def render_upgrade_text(has_payment_links: bool) -> str:
    return (
        "🚀 Garagem Alvo Premium\n\n"
        "Para quem já perdeu o carro certo porque alguém chegou primeiro.\n\n"
        "Mensal — R$ 5,99/mês\n"
        "• Até 15 buscas (monitorar vários modelos ao mesmo tempo)\n"
        "• Até 200 alertas por busca por dia\n"
        "• Acompanhar até 5 anúncios específicos com alerta de queda de preço\n\n"
        "Anual — R$ 59,99/ano (= R$ 4,99/mês)\n"
        "• Tudo do mensal\n"
        "• Preço travado enquanto a assinatura estiver ativa\n\n"
        "Após pagar, envie o comprovante aqui. Ativação em até 1h.\n"
    )
```

---

## Bloco 6 — Pequenos ajustes de alto impacto

### 6.1 Cancelar criação de busca é invisível — ✅ Concluído no PR #282

**O problema hoje:**
O botão "❌ Cancelar" existe na tela de resumo da criação, mas se o usuário simplesmente parar de responder, a sessão fica aberta indefinidamente. Se mandar `/menu`, pode interromper o fluxo de forma inesperada.

**O que fazer** — detectar comandos durante sessão aberta e perguntar:

```python
# No handler de mensagens de texto:
if context.user_data.get("session") and update.message.text.startswith("/"):
    cmd = update.message.text.split()[0]
    if cmd in ("/menu", "/buscar", "/start"):
        await update.message.reply_text(
            "Você tem uma busca em andamento.\n\n"
            "O que prefere?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Continuar criando", callback_data="CWL:RESUME")],
                [InlineKeyboardButton("Descartar e ir para o menu", callback_data="CWL:CANCEL_GOTO_MENU")],
            ])
        )
        return
```

---

### 6.2 "⭐ Anúncios rastreados" no menu mostra tela vazia sem orientação — ✅ Concluído no PR #260

> Status: concluído no PR #260. O texto abaixo fica mantido como histórico da motivação e da solução proposta.

**O problema hoje:**
Usuário toca em "⭐ Anúncios rastreados" sem ter nenhum rastreado. Vê:
```
Slot 1 — vazio
Slot 2 — vazio
Slot 3 — vazio
```
E um botão "Voltar". Não sabe o que fazer.

**O que fazer:**

```python
# Quando todos os slots estão vazios:
if not any_tracked:
    text = (
        "⭐ Anúncios rastreados\n\n"
        "Você ainda não está acompanhando nenhum anúncio.\n\n"
        "Quando receber um alerta ou fizer uma busca, toque em "
        "⭐ Rastrear para acompanhar o preço e o status daquele anúncio."
    )
```

---

### 6.3 Filtros de busca sem exemplos inline — ✅ Concluído no PR #278

**O problema hoje:**
O fluxo de adicionar filtro pergunta "Qual filtro?" e lista opções (preço, ano, km, cidade, estado). Quando o usuário escolhe "preço", recebe:
```
Qual preço? Ex.: até 150000, entre 70000 e 90000
```
Se digitar errado, recebe mensagem de erro. Não há dica de formatação visível antes de digitar.

**O que fazer** — mostrar exemplos como botões de sugestão:

```python
# Ao perguntar o preço:
await update.message.reply_text(
    "Qual o limite de preço?\n\nDigite um valor ou escolha:",
    reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("até R$ 50.000", callback_data="FILTER:PRICE:lte:50000")],
        [InlineKeyboardButton("até R$ 80.000", callback_data="FILTER:PRICE:lte:80000")],
        [InlineKeyboardButton("até R$ 120.000", callback_data="FILTER:PRICE:lte:120000")],
        [InlineKeyboardButton("Digitar valor", callback_data="FILTER:PRICE:MANUAL")],
    ])
)
```
Usuário pode tocar em um valor comum ou digitar livremente. Elimina 80% dos erros de formatação.

---

### 6.4 Mensagem de limite diário não diz "amanhã que horas" — ✅ Concluído no PR #286

**O problema hoje:**
"Amanhã libera de novo." Mas o usuário não sabe se é à meia-noite, às 6h, ou quando foi o primeiro alerta.

**O que fazer:**

```python
# Calcular quando renova (meia-noite UTC ou horário configurado):
from datetime import datetime, timezone, timedelta
tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).replace(
    hour=0, minute=0, second=0, microsecond=0
)
# Converter para horário do Brasil (UTC-3)
renews_at_brt = tomorrow - timedelta(hours=3)
renews_str = renews_at_brt.strftime("%Hh%M de amanhã")

text = f"Limite atingido ({limit} alertas hoje). Renova às {renews_str}."
```

---

## Resumo de prioridades

| # | Item | Status | Esforço | Impacto |
|---|---|---|---|---|
| 1.1 | Botão CTA no `/start` | ✅ Concluído PR #260 | Baixo | Alto — reduz abandono no onboarding |
| 3.1 | Lista de buscas compacta | ✅ Concluído PR #260 | Baixo | Médio — reduz fricção no uso diário |
| 6.2 | Tela vazia de anúncios rastreados | ✅ Concluído PR #260 | Baixo | Médio — reduz beco sem saída |
| 4.1 | Botão rastrear nos resultados de `/buscar` | ✅ Concluído PR #264 | Médio | Médio — fecha o loop busca → rastreio |
| 1.2 | Resultado imediato após criar busca | ✅ Concluído PR #266 | Médio | Alto — constrói confiança no primeiro uso |
| 2.1 | Badge de recência com fallback para `created_at` | ✅ Concluído PR #267 | Baixo | Alto — o argumento central do produto reaparece |
| 2.3 | Contexto mínimo garantido em todo alerta | ✅ Concluído PR #269 | Baixo | Médio — usuário sempre entende por que recebeu |
| 3.3 | Limite diário com contexto e CTA suave | ✅ Concluído PR #272 | Baixo | Alto para conversão Free → Premium |
| 5.1 | Barra de progresso no `/plan` | ✅ Concluído PR #273 | Baixo | Médio — torna limites mais tangíveis |
| 3.2 | "Buscar agora" inicia fluxo conversacional | ✅ Concluído PR #276 | Médio | Médio — UX consistente com o resto do bot |
| 6.3 | Botões de sugestão nos filtros | ✅ Concluído PR #278 | Médio | Médio — elimina erros de formatação |
| 2.4 | Label de score humanizado | ✅ Concluído PR #279 | Baixo | Baixo — clareza incremental |
| 1.3 | Contexto de ausência no `/start` | ✅ Concluído PR #280 | Médio | Médio — retenção de usuários que voltam |
| 6.1 | Detectar comando durante sessão aberta | ✅ Concluído PR #282 | Médio | Baixo — reduz confusão pontual |
| 5.2 | Texto de upgrade orientado à dor | ✅ Concluído PR #284 | Baixo | Médio — testa mensagem alternativa |
| 6.4 | Horário de renovação do limite diário | ✅ Concluído PR #286 | Baixo | Baixo — reduz dúvida operacional |
| 4.2 | Contexto histórico em queda de preço rastreado | ✅ Concluído PR #288 | Médio | Médio — aumenta valor percebido do rastreamento |
| 2.2 | Contexto de mercado quando `market_stats` está vazio | ✅ Concluído PR #290 | Baixo | Médio — melhora transparência do preço |

---

*Documento criado em 2026-05-21 e atualizado após o PR #260 para refletir o status real das melhorias de UX já implementadas.*
