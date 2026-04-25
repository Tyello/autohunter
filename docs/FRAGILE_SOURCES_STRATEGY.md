# Fragile Sources Strategy (Playwright / anti-bot)

Data: 2026-04-24.
Base: `app/sources/builtins.py` + comportamento de health/backoff no runtime.

## Objetivo
Não aumentar agressividade de scraping. Melhorar controle operacional e previsibilidade.

## Matriz curta (role operacional explícita)

| source | operational_role | motivo curto | expectativa operacional |
|---|---|---|---|
| mercadolivre | primary | fonte core do produto | entra no stale crítico se habilitada |
| olx | primary | fonte core com monitoramento contínuo | entra no stale crítico se habilitada |
| chavesnamao | primary | cobertura core (browser-first por estabilidade) | entra no stale crítico se habilitada |
| webmotors | deprioritized | anti-bot/challenge recorrente | monitorar sem incidente diário |
| gogarage | fragile | JS-heavy com risco operacional recorrente | entra no stale crítico se habilitada |
| icarros | fragile | JS-heavy + bloqueios ocasionais | entra no stale crítico se habilitada |
| mobiauto | fragile | JS-heavy + bloqueios ocasionais | entra no stale crítico se habilitada |
| kavak | experimental | cobertura em validação operacional | experimental, observar manualmente |
| facebook_marketplace | experimental | restrições de sessão/plataforma | experimental, observar manualmente |
| turboclass | experimental | integração recente, default desabilitada | experimental, observar manualmente |
| turboclass_vendidos | auxiliary | feed de vendidos (sem wishlist) | feed auxiliar, não crítico |

## Diretriz operacional
- `blocked/challenge/parser/network` devem ser tratados como categorias explícitas no health/admin.
- Priorizar ação operacional: backoff, warmup de browser, sessão/cookies, ajuste de cadência.
- Não usar retry agressivo para “furar” proteção anti-bot.
- **WebMotors**: tratar como source frágil com bloqueio recorrente (ex.: backoff de 240m). Se as demais sources estiverem saudáveis, isso **não é incidente crítico diário**.
- Ação padrão para WebMotors: monitorar + backoff + manter despriorizada.
- Investigar retomada só com decisão explícita de produto/operação para torná-la prioritária novamente.
- Não aumentar agressividade e não tentar burlar anti-bot/captcha/challenge.

## Política operacional de sources
- **primary/fragile**: entram no stale crítico quando habilitadas e executáveis.
- **auxiliary/experimental/deprioritized/disabled**: ficam fora do stale crítico por padrão.
- **fallback seguro**: source sem `operational_role` explícita continua classificada por comportamento (compatibilidade legada).

## Próximos passos seguros
1. Revisar cadência de sources de alto risco para evitar fila cronicamente saturada.
2. Operar com alertas por recorrência (não por evento isolado).
3. Manter estratégia dual/v1/v2 observável antes de consolidar adaptadores.
