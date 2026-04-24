# Fragile Sources Strategy (Playwright / anti-bot)

Data: 2026-04-24.
Base: `app/sources/builtins.py` + comportamento de health/backoff no runtime.

## Objetivo
Não aumentar agressividade de scraping. Melhorar controle operacional e previsibilidade.

## Matriz por source

| source | fetch_mode | force_browser default | fallback browser | risco esperado | estratégia recomendada |
|---|---:|---:|---:|---|---|
| mercadolivre | http | não | sim | médio (ondas anti-bot pontuais) | **monitorar** |
| olx | http | não | sim | médio/alto (bloqueio intermitente) | **monitorar** |
| chavesnamao | browser | sim | sim | médio (variação regional/SSR) | **browser-first** |
| webmotors | browser | sim | sim | alto (challenge HTTP 200/anti-bot) | **browser-first** |
| gogarage | browser | sim | sim | alto (JS-heavy) | **browser-first** |
| icarros | browser | sim | sim | alto (JS-heavy + anti-bot) | **monitorar** |
| mobiauto | browser | sim | sim | alto (JS-heavy + anti-bot) | **monitorar** |
| kavak | browser | sim | não explícito | médio/alto | **monitorar** |
| facebook_marketplace | browser | sim | não explícito | alto (restrições e sessão) | **experimental** |
| turboclass | http | não | sim | baixo/médio | **estável** |
| turboclass_vendidos | http | não | sim | baixo/médio | **reduzir cadência** |

## Diretriz operacional
- `blocked/challenge/parser/network` devem ser tratados como categorias explícitas no health/admin.
- Priorizar ação operacional: backoff, warmup de browser, sessão/cookies, ajuste de cadência.
- Não usar retry agressivo para “furar” proteção anti-bot.

## Próximos passos seguros
1. Revisar cadência de sources de alto risco para evitar fila cronicamente saturada.
2. Operar com alertas por recorrência (não por evento isolado).
3. Manter estratégia dual/v1/v2 observável antes de consolidar adaptadores.

