# ADR-0002: Escopo da adoção de async

**Status:** Proposed
**Date:** 2026-06-29
**Deciders:** Marcelo (dono do produto / dev único)

## Context

O projeto usa `ThreadPoolExecutor` (pools separados http/browser/sender no
APScheduler) para concorrência. A questão não é "async sim ou não" em abstrato, e
sim **onde** async paga e onde é custo sem retorno. Esta ADR existe para travar o
escopo antes de escrever qualquer código async — async + SQLAlchemy mal escopado é
uma fonte clássica de complexidade que não se paga.

Forças em jogo:
- **Pi 4, 4GB:** cada thread carrega stack próprio + (no padrão atual) uma conexão
  segurada. Dá pra subir algumas dezenas de fetches concorrentes antes de RAM e
  troca de contexto doerem.
- **DB remoto (Supabase):** toda query é round-trip de rede (~dezenas de ms). Uma
  thread bloqueada numa query é uma thread parada sem fazer nada útil.
- **Mix de scraping:** parte das fontes é HTTP/JSON; parte exige Playwright
  (browser). São naturezas de I/O diferentes.
- **`python-telegram-bot` já é async** — parte do ecossistema já está pavimentada.

Fato técnico central: **async só acelera I/O que espera de forma cooperativa.**
Um fetch HTTP libera o event loop enquanto a rede responde → centenas cabem numa
thread só, cada um com KB de estado. Já um render de browser via Playwright é
trabalho fora do processo Python; async **não** o torna mais rápido — no máximo
evita que ele bloqueie o resto enquanto espera.

## Decision

Adotar async de forma **escopada ao caminho HTTP-first de scraping**, e **não**
reescrever o caminho de browser nem (por ora) a camada de acesso ao banco.

Concretamente, o escopo APROVADO desta decisão:
- Migrar fetches HTTP de fontes (e seus parses I/O-bound) para um cliente async
  (httpx/aiohttp), permitindo dezenas/centenas de buscas canônicas concorrentes
  numa única thread.
- Manter o caminho Playwright como está (threads/pool de browser dedicado).
- Manter o acesso ao banco **síncrono por ora** — a migração para DB async é uma
  decisão separada (ver "A revisitar").

O que esta ADR **NÃO** aprova ainda: reescrever SQLAlchemy para async. Isso fica
explicitamente fora de escopo até haver evidência de que o bloqueio em queries ao
Supabase é gargalo medido, não suposto.

## Options Considered

### Option A: Async só no caminho HTTP de scraping (proposta)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Média — isolada ao cliente HTTP e aos scrapers HTTP |
| Cost | Baixo |
| Scalability | Alta no eixo que importa (concorrência de fetch I/O-bound) |
| Risk | Baixo — não toca DB nem browser |

**Pros:** ataca exatamente o I/O que async acelera; RAM por fetch despenca vs.
thread; não desestabiliza o que já funciona; reversível e isolável.
**Cons:** ganho limitado pela fração de tráfego que é HTTP (fontes com browser não
se beneficiam); introduz dois modelos de concorrência convivendo (async para HTTP,
threads para browser) — exige fronteira clara.

### Option B: Async end-to-end (HTTP + DB + orquestração)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Alta — SQLAlchemy async, sessões async, propagação por toda a stack |
| Cost | Alto |
| Scalability | Teoricamente a maior |
| Risk | Alto — async + ORM é fonte conhecida de bugs sutis |

**Pros:** sobrepõe também os round-trips ao Supabase; um único modelo de
concorrência.
**Cons:** custo de migração desproporcional para dev único; risco de regressão
alto; o ganho de DB async só importa se as queries forem comprovadamente o
gargalo — hoje não há essa medição. Otimização especulativa.

### Option C: Manter threads (status quo)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Nenhuma |
| Cost | Nenhum |
| Scalability | Limitada pela RAM por thread no Pi |

**Pros:** zero trabalho; modelo único e já entendido.
**Cons:** teto de concorrência de fetch baixo no Pi; threads bloqueadas em rede
desperdiçam RAM. Não aproveita que scraping é I/O-bound.

## Trade-off Analysis

O eixo é **ganho de I/O concorrente vs. custo/risco de migração**. A Opção B
maximiza o ganho teórico mas concentra risco e custo justo na camada (ORM) onde
async é mais traiçoeiro e onde **não há evidência** de gargalo — seria otimização
especulativa. A Opção A captura o ganho real e mensurável (concorrência de fetch
HTTP, que é onde o sistema realmente espera) com risco contido, ao preço de
conviver com dois modelos de concorrência.

A convivência de modelos (async para HTTP, threads para browser) é aceitável
porque a fronteira é natural: o caminho de browser já é isolado num pool dedicado
e roda como serviço remoto. Não há entrelaçamento que force unificar os dois.

Recomendação: **Opção A**. O DB async (parte da Opção B) só deve ser revisitado se
e quando profiling mostrar que o bloqueio em queries ao Supabase domina o tempo de
tick.

## Consequences

**Fica mais fácil:**
- Subir concorrência de fetch HTTP sem estourar RAM no Pi.
- Sobrepor a latência de fontes lentas (esperar várias ao mesmo tempo).
- Combina diretamente com a dedup de buscas (ADR-0001): raspar N buscas canônicas
  HTTP concorrentemente numa thread só.

**Fica mais difícil:**
- Conviver com dois modelos de concorrência exige uma fronteira de código clara
  entre o mundo async (HTTP) e o síncrono (DB, browser) — risco de "async leak".
- Pontes async↔sync (rodar corrotina a partir de código sync e vice-versa) exigem
  cuidado para não bloquear o event loop nem criar loops aninhados.

**A revisitar:**
- **DB async:** somente após profiling que comprove que round-trips ao Supabase
  são o gargalo dominante do tick. Até lá, fora de escopo.
- Se a fração de tráfego HTTP crescer muito (ex.: Webmotors mobile API der certo —
  ver spike), o ganho da Opção A aumenta proporcionalmente, reforçando a decisão.

## Action Items

1. [ ] (Quando for implementar) Definir a fronteira async↔sync: onde o event loop
       de scraping HTTP encontra o código síncrono de ingestão/DB.
2. [ ] Escolher cliente (httpx async é o caminho natural; já cobre HTTP/2).
3. [ ] Migrar 1 fonte HTTP como piloto e medir RAM + throughput vs. a versão thread.
4. [ ] Só então estender às demais fontes HTTP.
5. [ ] NÃO tocar SQLAlchemy/DB nesta fase. Registrar o profiling que justificaria
       revisitar isso.

> Esta ADR é decisão de escopo. Nenhum código async deve ser escrito antes de o
> piloto (item 3) validar o ganho no hardware real.
