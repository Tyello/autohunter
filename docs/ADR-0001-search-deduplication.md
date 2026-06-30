# ADR-0001: Deduplicação de buscas via chave canônica

**Status:** Proposed
**Date:** 2026-06-29
**Deciders:** Marcelo (dono do produto / dev único)

## Context

O custo de scraping hoje cresce, na prática, junto com o número de **wishlists**, não com o número de **buscas distintas**. No nicho do Garagem Alvo isso é caro: dez usuários caçando "Civic Si" geram dez wishlists que, na prática, disparam a mesma raspagem (`source` + `search_url` equivalentes). Cada raspagem redundante gasta o recurso mais escasso do sistema — CPU/RAM do Pi 4 e, no caso de fontes com browser, uma sessão de Playwright — além de aumentar a superfície de detecção anti-bot por repetir requisições idênticas.

Forças em jogo:
- **Hardware fixo:** um Pi 4 (4GB). Scraping com browser é o componente mais faminto de RAM.
- **DB remoto (Supabase):** cada query é round-trip de rede; menos raspagens = menos ingestão = menos round-trips.
- **Modelo de assinatura:** se o custo escala com usuários, a margem cai a cada novo assinante; se escala com buscas distintas, novos usuários em nichos populares são quase de graça.

Estado atual do código (relevante para a decisão):
- `app/scheduler/jobs.py::scrape_ingest_match` já tem **dois modos**:
  1. **Run por wishlist** (`wishlist is not None`): scrapeia o `search_url` daquela wishlist e casa contra ela. **É aqui que a duplicação acontece.**
  2. **Run por source, wishlist-agnóstico** (`wishlist is None`): scrapeia a fonte e casa contra **todas** as wishlists ativas via índice invertido (`match_listings_for_active_wishlists` + `WishlistToken`). **Este caminho já é dedup-friendly por natureza** — uma raspagem, fan-out para N wishlists.
- Já existe `source_url_cursors` com chave `(source, url)` — ou seja, uma chave canônica implícita de busca **já existe** no sistema.

A decisão não é "construir dedup do zero", e sim: **eliminar o caminho duplicativo, promovendo a chave canônica de busca a cidadão de primeira classe** e roteando todas as wishlists através de raspagens únicas com fan-out.

## Decision

Introduzir uma **chave canônica de busca** `CanonicalSearch(source, search_key)` derivada de cada wishlist ativa. A cada tick:

1. Normalizar todas as wishlists ativas para seu conjunto de `(source, search_key)`.
2. Deduplicar para o **conjunto único** de buscas canônicas.
3. Scrapear cada busca canônica **uma vez**.
4. Fazer **fan-out** dos resultados para todas as wishlists inscritas, reusando o índice invertido (`match_listings_for_active_wishlists`) que já existe e que o refactor recente já deixou eficiente.

Isso desacopla o custo de scraping do número de usuários — o sistema passa a escalar pelo número de **buscas distintas**.

## Options Considered

### Option A: Promover chave canônica + fan-out (proposta)
Camada de normalização `wishlist → (source, search_key)`, dedup do conjunto, uma raspagem por chave, fan-out via token index. O caminho por-wishlist é aposentado para o fluxo de tick recorrente (pode ser mantido só para "buscar agora" sob demanda do usuário).

| Dimension | Assessment |
|-----------|------------|
| Complexity | Média — exige função de canonicalização determinística e confiável |
| Cost | Baixo de implementar; alto retorno em CPU/RAM economizada |
| Scalability | Excelente — custo passa a escalar por busca distinta, não por usuário |
| Team familiarity | Alta — reusa `WishlistToken`, `source_url_cursors` e o matcher escalável já existentes |

**Pros:**
- Custo de scraping desacoplado do número de usuários.
- Reduz pegada anti-bot (menos requisições idênticas repetidas).
- Reaproveita máquinas já existentes (token index, cursores, matcher em batch).
- Caminho `wishlist is None` já existe e já valida o padrão de fan-out.

**Cons:**
- A canonicalização precisa ser **determinística e correta**: duas wishlists só podem colapsar se a raspagem resultante for de fato equivalente. Erro aqui = usuário deixa de receber alerta (falso negativo silencioso).
- Wishlists com filtros muito específicos no `search_url` (faixa de preço/ano embutida na URL) podem não colapsar — a chave canônica precisa separar "o que vai na URL de busca" de "o que é filtro pós-scrape".

### Option B: Cache de resultados por search_url com TTL
Manter o run por-wishlist, mas cachear o resultado de cada `(source, search_url)` por alguns minutos; wishlists subsequentes no mesmo tick com a mesma URL leem do cache.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Baixa |
| Cost | Baixo |
| Scalability | Limitada — ainda itera por wishlist; só evita a rede repetida dentro da janela do TTL |
| Team familiarity | Alta |

**Pros:** mudança pequena, baixo risco, não mexe na lógica de matching.
**Cons:** continua iterando por wishlist (overhead de orquestração escala com usuários); ganho limitado à janela do TTL; não reduz a complexidade arquitetural — só mascara a duplicação.

### Option C: Não fazer nada (manter status quo)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Nenhuma |
| Cost | Cresce linearmente com usuários |
| Scalability | Ruim para o modelo de negócio |

**Pros:** zero trabalho.
**Cons:** custo de scraping cresce com cada assinante; teto de capacidade do Pi chega cedo no beta.

## Trade-off Analysis

O eixo central é **correção da canonicalização vs. ganho de escala**. A Opção A entrega o ganho estrutural completo, mas concentra o risco num único ponto: a função que decide "estas duas wishlists são a mesma busca". Esse risco é gerenciável porque o sistema já separa, conceitualmente, *busca* (o que gera a URL de scraping) de *filtro* (o que é aplicado pós-scrape, via `FilterRule` e o matcher). A chave canônica deve cobrir **apenas** os campos que alteram a URL/resultado da raspagem; tudo que é filtro fino permanece no fan-out por wishlist, onde já funciona.

A Opção B é o "meio-termo seguro", mas não resolve o problema de fundo — o custo de orquestração continua escalando com usuários e a duplicação só é adiada pelo TTL. Serve como mitigação temporária, não como destino.

Recomendação: **Opção A**, com a canonicalização restrita aos campos formadores de URL e validação por baseline (o conjunto de matches por wishlist não pode mudar ao migrar do caminho por-wishlist para o canônico).

## Consequences

**Fica mais fácil:**
- Adicionar usuários em nichos populares sem custo proporcional de scraping.
- Raciocinar sobre carga: "quantas buscas distintas?" em vez de "quantas wishlists?".
- Throttling/agendamento por fonte (uma fila de buscas canônicas, não de wishlists).

**Fica mais difícil:**
- A canonicalização vira código crítico: um bug ali causa falso negativo silencioso (usuário não recebe alerta). Exige teste de equivalência forte.
- Debug de "por que não recebi esse carro?" passa por mais uma camada (busca canônica → fan-out).

**A revisitar:**
- Se/quando houver múltiplos nós, a fila de buscas canônicas é o ponto natural de distribuição de trabalho.
- Wishlists com filtros embutidos na URL (preço/ano) podem exigir uma sub-chave; medir quantas realmente divergem antes de complicar a chave.

## Action Items

1. [ ] Definir a função de canonicalização `canonical_search_key(wishlist) -> (source, search_key)` — apenas campos formadores de URL.
2. [ ] Capturar baseline dourada: conjunto de matches por wishlist no caminho atual.
3. [ ] Construir o conjunto único de buscas canônicas por tick e rotear o scraping por ele.
4. [ ] Fazer fan-out via `match_listings_for_active_wishlists` (já eficiente após o refactor recente).
5. [ ] Validar equivalência (baseline) e medir redução de raspagens/tick.
6. [ ] Decidir o destino do caminho por-wishlist (provável: manter só para "buscar agora" sob demanda).

> Brief de execução detalhado para o Claude Code: ver `docs/TASK_SEARCH_DEDUPLICATION.md`.
