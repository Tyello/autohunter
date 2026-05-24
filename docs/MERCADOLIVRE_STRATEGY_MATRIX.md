# Mercado Livre Strategy Matrix — AI Operational Memory

## Purpose

Este arquivo existe para evitar que agentes/LLMs repitam testes já feitos ou proponham novamente estratégias ruins para Mercado Livre.

Use este arquivo antes de gerar qualquer PR, roadmap, prompt Codex ou diagnóstico relacionado a Mercado Livre.

## Current Source of Truth

- Mercado Livre usa HTML vehicles URL como caminho principal.
- API pública não é caminho principal.
- Playwright networkidle é fallback válido, mas instável.
- Shell sem cards e captcha/security são estados operacionais esperados.
- Strategy probe completo com browser pode piorar bloqueio.
- Não decidir flip V2 durante captcha/security/shell.
- V1 e V2 têm caminho técnico viável, mas dependem de janela sem wall/captcha.

## Status Legend

- GOOD_CONDITIONAL: funcionou em janela boa, pode ser usado com cuidado.
- UNSTABLE: alterna entre bom, shell, timeout ou captcha.
- BAD_PRIMARY: não usar como caminho principal.
- AVOID_REPEAT: evitar em novos testes automáticos.
- DIAGNOSTIC_ONLY: usar só em investigação manual.
- NOT_SEARCH_URL: não serve para busca.

## Observed Facts

Registrar como fatos, não hipótese:

- settings.playwright_storage_dir foi observado como .data/playwright.
- path resolvido foi /opt/autohunter/.data/playwright.
- storage_mercadolivre____no_proxy__.json existia e foi removido.
- Mesmo após remoção, o strategy_probe com browser retornou INCONCLUSIVE.
- API retornou 403/forbidden ou payload inútil.
- HTML/curl frequentemente retornou shell de aproximadamente 7 KB.
- Playwright frequentemente caiu em /captcha/wall.
- Em janela boa, plugin_build_url + playwright_networkidle retornou HTML com cards.
- Em janela boa, lista_vehicle_slug + unified_fetch retornou HTML com cards.
- POLYCARD do V1 parseou até 33 itens a partir de HTML bom.
- V2 já chegou a raw_items_found=11 antes do problema de parser.
- PRs recentes alinharam V2 para HTML vehicles URL + fallback browser + POLYCARD.

## Hypotheses (explicitly not confirmed facts)

- Uma janela limpa sem wall/captcha pode restaurar paridade V1↔V2 sem alteração de fetch.
- A frequência de shell/captcha pode aumentar com probes browser repetidos.

## Strategy Matrix

| strategy_key | url_pattern | observed_result | status | use_in_future | notes_for_ai |
|---|---|---|---|---|---|
| plugin_build_url | `https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/<slug>` | Em janela boa, retornou HTML com cards; em janela ruim, shell/captcha. | GOOD_CONDITIONAL + UNSTABLE | YES, as primary search URL | Use como caminho principal. Detecte shell. Use fallback browser networkidle. Não faça hammering. |
| lista_vehicle_slug | `https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/<slug>` | Em janela boa, `unified_fetch` retornou cards; também alternou para shell/captcha. | GOOD_CONDITIONAL + UNSTABLE | YES, as primary search URL | Trate como builder canônico. Preserve detecção de bloqueio. |
| lista_vehicle_brand_model | `https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/honda/civic` | Pode aparecer como `final_url` canônica. Comportamento instável. | DIAGNOSTIC_ONLY + UNSTABLE | MAYBE, only manual diagnostics | Não substitua o builder primário sem evidência nova. |
| lista_generic_slug | `https://lista.mercadolivre.com.br/<slug>` | Repetiu shell/captcha sem ganho durável. | AVOID_REPEAT | NO | Não proponha novamente como correção. |
| api_with_category | `https://api.mercadolibre.com/sites/MLB/search?q=<query>&category=MLB1743` | Retornou 403/forbidden ou payload inútil (~230 bytes). | BAD_PRIMARY | NO | Já testado. Não propor API-first novamente. |
| api_without_category | `https://api.mercadolibre.com/sites/MLB/search?q=<query>` | Retorno inconsistente e não confiável para o objetivo principal. | BAD_PRIMARY | NO | Não usar como caminho principal de busca. |
| api_category_first | `https://api.mercadolibre.com/sites/MLB/search?category=MLB1743&q=<query>` | Sem ganho operacional. Resultado não confiável. | BAD_PRIMARY | NO | Não insistir em variações API-first. |
| listing_canonical | `https://carro.mercadolivre.com.br/MLB-<id>-_JM` | URL válida de anúncio individual. | NOT_SEARCH_URL | ONLY as listing URL/detail/canonical | Use para detalhe/canonicalização. Não use para estratégia de busca. |

## Fetcher Matrix

| fetcher | observed_result | status | use_in_future | notes_for_ai |
|---|---|---|---|---|
| unified_fetch | Caminho barato e útil em janela boa; também pode cair em shell/security. | GOOD_CONDITIONAL + UNSTABLE | YES | Use como primeira tentativa. Detecte shell/security antes de concluir vazio. |
| curl_cffi_direct | Frequentemente retornou shell HTML ou API 403. | BAD_PRIMARY | NO | Não promover como caminho principal. |
| playwright_domcontentloaded | Muito cedo. Frequentemente retornou shell/captcha. | BAD_PRIMARY | NO | Evite como estratégia padrão. |
| playwright_networkidle | Melhor fallback browser observado. Ainda instável. | GOOD_CONDITIONAL + UNSTABLE | YES, fallback only | Use com anti-hammering e limite de tentativas. |
| playwright_wait_scroll | Mais pesado. Aumentou risco de captcha em testes amplos. | AVOID_REPEAT | NO (unless explicit debugging) | Não execute em matriz ampla sem motivo explícito. |

## DO

- Use HTML vehicles URL as main search URL.
- Keep API only as compatibility/diagnostic path.
- Detect shell without cards.
- Detect security/captcha separately.
- Use at most one browser retry with fresh context after shell.
- Stop browser probes after security wall.
- Wait cooldown before retesting Mercado Livre.
- Prefer single dual-run validation over full strategy matrix.
- Keep V1 operational while V2 is being validated.
- Require v1_count > 0 and v2_count > 0 before any V2 flip.

## DO NOT

- Do not propose API-first again.
- Do not use lista_generic_slug as a new fix.
- Do not run full strategy_probe with --include-browser repeatedly.
- Do not use --ignore-security-wall unless explicitly debugging.
- Do not interpret shell as zero real results.
- Do not interpret captcha/security as parser failure.
- Do not flip V2 while Mercado Livre is in wall/captcha.
- Do not add more Playwright attempts without anti-hammering.
- Do not create migrations for this problem.
- Do not touch WebMotors in Mercado Livre tasks.

## Known Bad Ideas

1. "Switch Mercado Livre to API-first"
   Reason: already tested; API returned 403/forbidden or useless payload.

2. "Use lista.mercadolivre.com.br/<slug>"
   Reason: already tested; shell/captcha, no durable gain.

3. "Run every Playwright strategy repeatedly"
   Reason: increases captcha/security wall risk.

4. "Treat v1_count=0 as no listings"
   Reason: usually shell/captcha/security, not true empty result.

5. "Fix parser when raw_items_found=0"
   Reason: parser is not reached. Fix fetch/blocking first.

6. "Fix fetch when raw_items_found>0 and items_parsed=0"
   Reason: that is parser/normalization stage.

## Decision Rules

- If final_url contains /captcha/wall:
  classify as ml_security_or_captcha_page.
  stop browser attempts.
  recommend cooldown.

- If HTML length is ~7 KB and cards=0 and links=0:
  classify as ml_shell_without_results.
  allow at most one fresh-context retry.

- If raw_items_found=0 and fetch_blocked=true:
  do not work on parser.

- If raw_items_found>0 and items_parsed=0:
  work on parse_listing/extract_raw_data.

- If v1_count>0 and v2_count=0:
  work on V2 parity only.

- If v1_count=0 and v2_count=0 with shell/captcha:
  do not infer regression. Treat as ML blocked window.

- If v1_count>0 and v2_count>0:
  compare matched_count, only_v1, only_v2, field_diffs.

## Safe Commands

Preferred single validation:

```bash
python scripts/source_dual_run_report.py mercadolivre --query "civic si" --format json
```

Probe without browser:

```bash
python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json
```

Probe with browser only when needed:

```bash
python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json --include-browser
```

Avoid unless explicitly debugging:

```bash
python scripts/mercadolivre_strategy_probe.py --query "civic si" --format json --include-browser --ignore-security-wall
```

## When Generating New Codex Tasks

Before generating a Codex task about Mercado Livre:

1. Read this file.
2. Identify the current stage:
   - fetch blocked
   - shell
   - security/captcha
   - raw extracted but parse failed
   - parity diff
3. Do not suggest strategies marked BAD_PRIMARY or AVOID_REPEAT.
4. Reuse existing helpers before adding new ones:
   - `_is_ml_shell_without_results`
   - `_is_ml_security_or_captcha_page`
   - `_fetch_ml_search_with_shell_fallback`
   - `_parse_polycard_items`
   - `reset_browser_state_for_source`
5. Prefer small PRs with tests.
6. Never combine WebMotors with Mercado Livre work.
7. Never propose V2 flip until dual-run is clean.

## Current Recommended Runtime Strategy

- Search URL:
  `https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/<slug>`

- First fetch:
  unified/http path.

- If shell:
  browser networkidle fallback.

- If browser shell:
  reset ML context/storage.
  retry once.

- If security/captcha:
  raise blocked.
  stop.
  backoff/cooldown.

- Parser:
  prefer POLYCARD.
  merge/dedupe visible cards.

- Flip condition:
  only after dual-run stable with v1_count > 0 and v2_count > 0.

## Update Rules

- Whenever a new ML strategy is tested, append to this file.
- Include:
  - date
  - command
  - URL/fetcher
  - observed result
  - final decision
- Do not remove failed strategies. Mark them as BAD_PRIMARY or AVOID_REPEAT.
- Keep this file optimized for agents, not prose.
