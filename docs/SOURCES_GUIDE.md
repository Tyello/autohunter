# Garagem Alvo — Guia Técnico de Sources

> Fonte de verdade técnica: ver `docs/SOURCES_ARCHITECTURE.md`.
> Estado operacional, estratégia de desbloqueio e como validar cada fonte antes de colocar em produção.

---

## Mapa de sources

| Source | Modo | Papel | Estado atual |
|---|---|---|---|
| `mercadolivre` | HTTP + browser fallback | primary | ⚠️ Em diagnóstico de estratégia de fetch |
| `olx` | HTTP + browser fallback | primary | ⚠️ Intermitente |
| `chavesnamao` | Browser-first | primary | ✅ Estável |
| `webmotors` | Browser-first | deprioritized | 🔴 Bloqueado |
| `gogarage` | Browser-first | fragile | ⚠️ Instável |
| `icarros` | Browser-first | fragile | ⚠️ Instável |
| `mobiauto` | Browser-first | fragile | ⚠️ Instável |
| `kavak` | Browser-first | experimental | 🔬 Em validação |
| `turboclass` | HTTP (feed) | experimental | ✅ Habilitada por default (em validação) |
| `facebook_marketplace` | Browser + sessão manual | experimental | ❌ Fora do piloto |

---

## Diagnóstico rápido por source

Para qualquer source, o ciclo de diagnóstico é sempre o mesmo:

```
/admin source <source> status      → estado atual (backoff, consecutivos, última run)
/admin runall <source>             → forçar execução e ver resultado em tempo real
/admin source <source> last-runs   → histórico das últimas execuções
```

Para sources browser-first, adicionar warmup antes do runall:
```
/admin warmup <source>
/admin runall <source>
```

Notas operacionais rápidas:
- `/admin sources show <source>` agora exibe `extra=` (sanitizado) para facilitar validação de flags DB-driven como `browser_block_resources`.
- Em `webmotors`, quando `/admin runall webmotors` vier `blocked http=200` com diagnóstico PerimeterX (ex.: `Access to this page has been denied` / `Pressione e segure...`), trate como bloqueio anti-bot/fingerprint (não como falha primária de proxy/config local).

### Webmotors — experimento `curl_cffi`

- Desligado por default (`source_configs.extra.webmotors_curl_cffi_enabled=false`).
- Ativar com `source_configs.extra.webmotors_curl_cffi_enabled=true`.
- Objetivo: testar fetch HTTP com fingerprint de browser antes de Playwright.
- Se detectar challenge PerimeterX, o fluxo cai para browser e mantém diagnóstico.
- Não altera `force_browser` automaticamente.
- Instalação opcional no Raspberry (para realmente executar o experimento HTTP):
  - `/opt/autohunter/.venv/bin/pip install curl_cffi`
  - `sudo systemctl restart autohunter-bot autohunter-scheduler`
- Se `curl_cffi` não estiver instalado, a execução cai para Playwright sem quebrar o fluxo.

---


## Webmotors — decisão operacional atual

- Implementada tecnicamente no runtime, com execução manual preservada via `/admin runall webmotors`.
- Bloqueada operacionalmente por PerimeterX/fingerprint na navegação real.
- Testes já executados em produção:
  - browser com assets liberados (`browser_block_resources=false`);
  - warmup completo (storage_state + scroll/mouse/consent/extra_wait);
  - tentativa HTTP com `curl_cffi` (`impersonate=chrome`).
- Resultado consolidado: `status=blocked` com HTTP 200 + challenge (`provider=perimeterx`, `title=Access to this page has been denied`, snippet “Pressione e segure para confirmar que você é um humano”).
- Decisão operacional: manter Webmotors como `operational_role=deprioritized` e `default_enabled=false` por padrão de seed.
- ⚠️ Importante: `default_enabled=false` no plugin afeta apenas seed de novas linhas em `source_configs`. Em ambientes já existentes, desative manualmente:
  - `/admin sources disable webmotors`
  - ou SQL: `UPDATE source_configs SET is_enabled = false WHERE source = 'webmotors';`
- Efeito esperado: não tratar bloqueio da Webmotors como falha crítica global; manter visível como blocked/deprioritized no detalhamento admin.
- Próximas tentativas (ex.: Patchright/sessão assistida) exigem POC isolada e decisão explícita antes de qualquer rollout.

## Sources despriorizadas e saúde global

- Sources com `operational_role=deprioritized` permanecem visíveis no admin (`/admin sources` e `/admin sources show`).
- Bloqueios/erros dessas sources devem aparecer no detalhamento, mas não devem ser tratados como falha crítica global do produto.
- Caso atual: Webmotors permanece bloqueada por PerimeterX/fingerprint e mantida para execução manual/investigação via `/admin runall webmotors`.
- Sources `primary` (e `fragile`, quando explicitamente classificadas como críticas) continuam sendo o principal sinal de saúde operacional global.

## Webmotors — Plano de desbloqueio

### Por que está bloqueado

Webmotors usa **PerimeterX** como camada anti-bot. O comportamento observado é:

- HTTP direto → retorna `403` ou `challenge page` com HTTP 200
- Browser sem warmup → PerimeterX identifica o Chromium pelo fingerprint e bloqueia
- Browser após warmup → funciona por 1–6 horas, depois volta a bloquear

O diagnóstico está implementado: `blocked_provider=perimeterx` aparece no `/admin sources` quando bloqueado.

### O que já existe no código

- `app/services/webmotors_consent.py` — clica botão de cookie/consent automaticamente
- `app/services/challenge_fingerprint.py` — identifica qual anti-bot está ativo
- `app/services/browser_warmup_service.py` — salva `storage_state` por source
- `app/scrapers/webmotors_ops.py` — classifica o tipo de erro (BLOCKED/PROXY/NET/PARSER)
- `app/bot/handlers_admin.py` — `/admin warmup webmotors` já existe

### Estratégia de desbloqueio (em ordem de esforço)

**Nível 1 — Otimizar o warmup (2–3 dias)**

O warmup atual salva cookies mas não simula comportamento humano suficiente para o PerimeterX. Melhorar:

1. No warmup, navegar para a home, aguardar 2s, rolar a página, depois ir para `/comprar/carros`
2. Chamar `try_click_consent(page)` para aceitar cookies antes de salvar o `storage_state`
3. Fazer uma busca simples (ex: `honda civic`) e aguardar os cards carregarem antes de salvar
4. Salvar o `storage_state` com a sessão "aquecida" (cookies + localStorage do PerimeterX)

```python
# Sequência recomendada no warmup do Webmotors:
await page.goto("https://www.webmotors.com.br", wait_until="domcontentloaded")
await page.wait_for_timeout(2000)
await page.evaluate("window.scrollTo(0, 400)")
await page.wait_for_timeout(1000)
from app.services.webmotors_consent import try_click_consent
await try_click_consent(page)
await page.goto("https://www.webmotors.com.br/comprar/carros", wait_until="networkidle")
await page.wait_for_timeout(3000)
# Agora salvar storage_state
```

**Verificar resultado:**
```
/admin warmup webmotors
/admin runall webmotors
```
Se retornar `cards_found > 0` → nível 1 resolveu.

---

**Nível 2 — Proxy residencial para o warmup (3–5 dias)**

Se o nível 1 não resolver, o PerimeterX está bloqueando pelo IP do RPi (IP de datacenter/residencial sem histórico).

Opções de proxy residencial:
- **BrightData** (mais confiável, mais caro — ~$15/GB)
- **Webshare** (mais barato, qualidade variável — ~$3/GB)
- **ProxyMesh** (boa relação custo/qualidade para BR)

Configurar o proxy apenas para o warmup do Webmotors:

```env
SOURCE_PROXY_WEBMOTORS=http://user:pass@proxy-host:port
```

O código já suporta proxy por source via `source_configs.proxy_server`. O warmup usa o mesmo contexto de proxy configurado para a source.

**Verificar resultado:**
```
/admin source webmotors set proxy_server http://user:pass@host:port
/admin warmup webmotors
/admin runall webmotors
```

---

**Nível 3 — Interceptar XHR da API interna (5–10 dias)**

Webmotors carrega os anúncios via chamada XHR para uma API interna (visível no Network tab do DevTools). Essa API retorna JSON estruturado — muito mais limpo que fazer parsing de HTML.

Como investigar:
1. Abrir `https://www.webmotors.com.br/comprar/carros?q=civic` no Chrome
2. Abrir DevTools → Network → filtrar por `XHR`
3. Procurar chamadas para `apigw.webmotors.com.br` ou similar
4. Copiar os headers da requisição (especialmente `Authorization` e cookies)

Se a API exigir token que expira, a estratégia é:
- Browser faz o warmup e captura o token via `page.on("request", ...)`
- Token fica em cache por N minutos
- Requests subsequentes usam o token diretamente via HTTP (sem browser)

Isso eliminaria o custo do Playwright para o Webmotors após o warmup.

---

**Nível 4 — API oficial B2B (decisão de produto)**

Webmotors tem Portal de Developers para integrações B2B. Acesso via:
`https://developers.webmotors.com.br`

Prós: sem bloqueio, dados estruturados, estável
Contras: processo de aprovação, possível custo por acesso, tempo de negociação (semanas)

Avaliar se faz sentido após validar o produto com as outras fontes.

---

### Monitoramento do Webmotors em produção

Quando estiver operacional, configurar:

```env
ENABLE_WEBMOTORS=true
SCHED_WEBMOTORS_MINUTES=90      # não agressivo — menos chance de bloqueio
WEBMOTORS_COOLDOWN_MINUTES=240  # backoff de 4h quando bloqueado
RATE_LIMIT_WEBMOTORS_SECONDS=15 # pausa entre requests
```

No `source_configs`:
```sql
UPDATE source_configs
SET extra = extra || '{"operational_role": "primary"}'::jsonb
WHERE source = 'webmotors';
```

Sinais de saúde:
- `consecutive_blocks > 3` → considerar aumentar cooldown
- `cards_found = 0` por 2 runs seguidas → verificar se warmup expirou
- `blocked_provider = perimeterx` → refazer warmup

---

## OLX — Estabilização

### Comportamento atual

OLX alterna entre dois modos:
- **HTTP via API JSON** (`/api/v1/search/listings`) — quando funciona, retorna dados limpos
- **Browser fallback** — quando a API retorna 403 ou Cloudflare challenge

O problema é que o fallback browser não está sempre configurado de forma otimizada.

### O que verificar

```
/admin source olx status
```

Se `last_status = blocked` com frequência > 30%:

1. Verificar se `browser_fallback_enabled = true` no `source_configs`
2. Verificar se `olx_force_browser` está `false` (forçar browser 100% do tempo consome RAM sem necessidade)
3. Se bloqueio for recorrente por mais de 24h, tentar proxy específico para OLX:

```env
SOURCE_PROXY_OLX=http://user:pass@proxy-host:port
```

### Cadência recomendada

```env
SCHED_OLX_MINUTES=30
OLX_COOLDOWN_MINUTES=60
RATE_LIMIT_OLX_SECONDS=20
```

### Parser — gaps conhecidos

- `year` e `km` às vezes ausentes no resultado da API (campo `params` inconsistente)
- `location` vem como string livre, normalização pode perder cidade
- `external_id` estável via URL slug — não há risco de dedupe falso

---

## GoGarage — Manutenção mínima

### Estado

Browser-first, JS-heavy. Funciona quando o Playwright está aquecido. Problema principal: o site muda o seletor dos cards com alguma frequência, quebrando o parser.

### Como validar

```
/admin source gogarage status
/admin runall gogarage
```

Se `items_found = 0` mas `http_status = 200` → seletor quebrado, precisa atualizar o parser.

Para inspecionar o HTML atual:
```python
# scripts/debug_manual_search.py (reescrever após limpeza do arquivo atual)
from app.services.browser_fetcher import fetch_html_browser
html = await fetch_html_browser("https://www.gogarage.com.br/comprar/?q=civic")
# Salvar em arquivo e inspecionar manualmente
```

### Seletores para manter atualizado

O parser em `app/scrapers/gogarage.py` usa seletores que mudam. Ao ver `items_found = 0`:
1. Abrir o site manualmente no browser
2. Inspecionar o elemento do card de anúncio
3. Atualizar o seletor no scraper

---

## iCarros — Estabilização

### Estado

SSR tradicional + API REST. Menos sujeito a bloqueio que GoGarage. Instável principalmente por:
- Mudanças na estrutura HTML da listagem
- Rate limiting agressivo (429) quando cadência muito alta

### Cadência recomendada

```env
SCHED_ICARROS_MINUTES=120      # 2h — não agressivo
RATE_LIMIT_ICARROS_SECONDS=30  # pausa generosa
```

### Validação

```
/admin runall icarros
```

Se `http_status = 429` → aumentar `RATE_LIMIT_ICARROS_SECONDS` para 60.
Se `items_found = 0` com `http_status = 200` → seletor quebrado, inspecionar HTML.

---

## Mobiauto — Estabilização

### Estado

Similar ao iCarros em estrutura. Diferença: o detalhe do anúncio (URL individual) tem mais dados que a listagem. O código tem `detail enrichment` implementado mas é opcional por custo de requests.

### Estratégia

Manter `detail enrichment = false` por padrão (economiza requests no RPi). Ativar somente para queries de alta prioridade ou para usuários Premium quando implementar priorização.

### Cadência recomendada

```env
SCHED_MOBIAUTO_MINUTES=120
RATE_LIMIT_MOBIAUTO_SECONDS=25
```

---

## Kavak — Validação

### Estado

Source experimental. Kavak vende carros recondicionados com preço fixo — não é o foco principal do produto (entusiasta busca mercado livre), mas pode ser útil para alertas de "preço de mercado" como referência.

### O que validar antes de habilitar

```
/admin source kavak enable
/admin runall kavak
```

Verificar:
- `items_found > 0`
- `items_ingested > 0` (dedupe funcionando)
- Títulos e preços normalizados corretamente
- Nenhum external_id duplicado (Kavak usa IDs numéricos estáveis)

### Decisão de produto

Kavak tem preço fixo e estoque controlado. O volume de "novidade" é baixo — um mesmo carro fica disponível por dias. Considerar cadência longa:

```env
SCHED_KAVAK_MINUTES=360        # 6h — estoque muda devagar
```

---

## TurboClass — Validação

### Estado

Feed de "vendidos" e marketplace de preparação. Heterogêneo — mistura carros, peças e preparações. Útil para usuário que busca bases de projeto ou peças raras.

### Consideração

TurboClass tem modo incremental implementado (cursor por URL). Isso significa que não re-processa anúncios antigos — só pega novos. Muito eficiente para o RPi.

Manter habilitado como fonte secundária para usuários que buscam termos como "base de projeto", "motor", "swap".

---

## Facebook Marketplace — Fora do piloto

### Por que está fora

Requer sessão autenticada por usuário (`fb_sessions`). O fluxo de pairing existe e funciona, mas:
- Cada usuário precisa autenticar manualmente
- Sessões expiram e precisam ser renovadas
- Detectado como bot com facilidade sem proxy residencial dedicado

### Quando reconsiderar

Após atingir 200+ usuários e ter receita que justifique proxy residencial dedicado para Facebook (custo ~$30–50/mês).

---

## Checklist de validação antes de habilitar uma source

Para qualquer source antes de colocar em produção:

```
[ ] /admin source <source> enable
[ ] /admin warmup <source>         (se browser-first)
[ ] /admin runall <source>
[ ] items_found > 0
[ ] items_ingested > 0
[ ] Pelo menos 1 notificação criada (matching funcionando)
[ ] Nenhum erro de dedupe (external_id duplicado no log)
[ ] Títulos em português sem caracteres estranhos
[ ] Preços no formato correto (int, em centavos ou reais conforme modelo)
[ ] URLs abrindo corretamente (não 404)
[ ] Executar por 48h sem intervenção e verificar consecutive_blocks == 0
```

---

## Ordem de prioridade para estabilização

```
Semana 1-2: Webmotors (nível 1 → nível 2 se necessário)
Semana 2:   OLX (ajuste de cadência + proxy se necessário)
Semana 3:   iCarros + Mobiauto (validação de seletores)
Semana 4:   GoGarage (manutenção de parser)
Backlog:    Kavak, TurboClass (validação de volume)
Futuro:     Facebook Marketplace (decisão de produto pós-200 usuários)
```

Com ML + Chaves na Mão estáveis + OLX e Webmotors funcionando, o produto tem cobertura suficiente para o lançamento público. As demais sources são incremento de qualidade, não bloqueadores.

---

*Documento criado em 2026-05-21. Atualizar seção de cada source após cada validação operacional.*

## Webmotors — warmup mensurável

- `/admin warmup webmotors` exibe `still_challenge`, `provider`, `reason`, `title`, `final_url`, `duration_ms` e etapas executadas.
- Comportamento extra (scroll/mouse/consent) fica desligado por default.
- Ative via `source_configs.extra.webmotors_warmup_behavior_enabled=true`.
- Mesmo com warmup bem-sucedido, a validação real continua sendo `/admin runall webmotors`.
- Não há promessa de desbloqueio.

## Mercado Livre (status operacional atual)

- Continua como source `primary`, em recuperação operacional no ambiente Raspberry Pi, sem flip para V2 nesta etapa.
- Estratégia comprovada no probe e aplicada no runtime V1:
  - `lista_vehicle_slug + unified_fetch` pode retornar HTML completo com cards.
  - quando a resposta vem como shell/SPA sem cards, o fallback efetivo é browser com `wait_until=networkidle`.
  - captura de HTML via Playwright precisa ser resiliente a navegação transitória (`Page.content ... page is navigating`), com retries curtos antes de falhar.
  - quando o browser cair em security/captcha (`Seguridad — Mercado Libre` ou `/captcha/wall`), o runtime deve sinalizar bloqueio explícito, evitando `count=0` silencioso.
  - API pública pode retornar `403` (bloqueio/fingerprint/challenge upstream), então não é caminho principal no Raspberry.
- Use probe manual/read-only para triagem de estratégia:
  - `python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json`
- Não há mudança automática de URL/default/impl nesse diagnóstico; objetivo é apenas observabilidade de fetch por estratégia.

- Playwright pode ser incluído como plano B diagnóstico explícito com `--include-browser` (manual/read-only), sem mudança de comportamento de produção.
- Exemplo: `python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json --include-browser`

- `playwright_wait_scroll` executa wait+scroll real (domcontentloaded + waits + scroll leve) somente no probe manual com `--include-browser`.


### Mercado Livre — diagnóstico atual

- Source `primary` em diagnóstico de estratégia de fetch (não despriorizada).
- Probe manual recomendado (read-only): `python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json`.

### Mercado Livre — estratégia V2 atualizada

- O scraper V2 de Mercado Livre usa a mesma estratégia operacional validada no V1: URL HTML do vertical de veículos como padrão.
- Quando o fetch HTTP retorna bloqueio/shell sem cards úteis, o V2 aplica fallback browser com `wait_until="networkidle"` para recuperar HTML completo.
- A API pública do Mercado Livre permanece como compatibilidade/fallback e não deve ser tratada como caminho principal no runtime (especialmente no Raspberry).
- Incluir Playwright apenas de forma explícita: `--include-browser`.


- Anti-hammering: ao detectar `Seguridad — Mercado Libre` ou `\/captcha\/wall`, interrompa novas tentativas browser em sequência para a mesma query e aguarde janela de cooldown antes de repetir o probe completo.
- Shell sem cards (`ml_shell_without_results`) deve usar no máximo 1 retry com contexto Playwright fresco e limpeza de storage da source.
