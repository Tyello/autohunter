# Prompt Claude Code — Execução v2: melhorias nas sources de classificados

> **Substitui as Fases 1 a 4** de `docs/prompts/PROMPT-exec-melhorias-sources.md`. A Fase 0 (PR #395) continua válida e é a base deste prompt.
> Repriorização em 28/09/2026, depois da Fase 0 e de um teste manual no Mercado Livre.
> Execute **por fases**. Cada fase = 1 branch + 1 PR. **Não comece a próxima** sem testes verdes, relatório atualizado e PR revisado.

## Modo de operação

- **Proibido:** migrações e alterações de schema, deploy, mudar `source_configs` em produção, qualquer bypass anti-bot, solver de CAPTCHA, proxy ou uso de login/cookies de conta pessoal, e adicionar dependências novas (Scrapling já é **NO-GO**).
- **Rede:** só para recapturar fixtures quando indispensável, com **no máximo 20 requisições** por fase, intervalo ≥2s, respeitando `robots.txt` e `Crawl-delay` (Kavak: 20s). Registre cada comando e o status HTTP no relatório.
- **Citações:** toda afirmação sobre o código precisa de `arquivo:linha`. O que não puder ser confirmado deve ser marcado como **NÃO VERIFICADO**.
- **Entregável de acompanhamento (único):** continue atualizando `docs/spikes/sources-melhorias-execucao.md`, com uma seção nova por fase: o que mudou (`arquivo:linha`), testes, antes/depois de preenchimento e cobertura por fixture, riscos e pendências.
- **Fixtures:** use as de `tests/fixtures/source_regression/<source>/2026-09-28_civic/` capturadas na Fase 0.

## Contexto (não reconstrua; use isto)

- **Restrições obrigatórias:**
  1. Raspberry Pi 4 (4 GB), com CPU fraca.
  2. Supabase é remoto: **nenhuma** query por anúncio.
  3. Chromium consome muita memória: toda mudança deve **reduzir** o uso de browser.
- **ADR-0001:** dedup por chave canônica; "na dúvida, não colapsar". **O `external_id` de cada source não pode mudar.** Se mudar, pare e reporte.
- **ADR-0002:** async só no scraping HTTP-first.
- **Resultados da Fase 0** (`docs/spikes/sources-melhorias-execucao.md`):
  - Mobiauto e Kavak já extraem ano/km via JSON embutido. O que falta nas duas é o **modo de fetch**.
  - Chaves na Mão captura **5 de 15** anúncios por página; os 15 estão no JSON-LD `ItemList`, que não é usado.
  - OLX tem 100% de ano/km pelo caminho RSC.
- **Decisão sobre o Mercado Livre (28/09):**
  - A busca exige login para qualquer visitante anônimo. Até num Chrome comum, com IP residencial e janela anônima, o site redireciona para `/gz/account-verification` ("Olá! Para continuar, acesse sua conta", `path=/security/suspicious_traffic`).
  - A API pública já foi descartada (`docs/MERCADOLIVRE_STRATEGY_MATRIX.md:58-60`).
  - Usar login de conta foi **descartado**: o risco cairia sobre a conta, que pode estar ligada ao Mercado Pago dos pagamentos, e isso viola os termos do site.
  - **Decisão:** o ML vira `deprioritized`, igual à Webmotors. **Não** implemente a extração de ano/km do ML nesta rodada.

## Pré-requisito — ajustes no PR #395 (antes do merge)

1. Corrigir o log de rede do relatório: o texto diz 16 requisições e a tabela lista 15.
2. Mover `tests/fixtures/source_regression/_fase0_baseline.py` para `scripts/spikes/probe_fase0_baseline.py` e ajustar as referências.

---

## Fase 1 — Chaves na Mão (cobertura 5 → 15) + Mercado Livre `deprioritized`

### 1A. Chaves na Mão
Arquivo: `app/scrapers/chavesnamao.py`.
1. Faça do JSON-LD `ItemList` a fonte **primária** dos itens: `name`, `offers.price`, `url`, `brand`, `model`, `color` e `offers.seller.name`. O ano vem do `name` ou da `url`; o km vem do texto do card correspondente, casado pela `url`.
2. Mantenha o caminho atual (`<a href>` + regex, `:182-220`) como **fallback** quando não houver `ItemList`.
3. O `external_id` precisa sair **idêntico** ao atual (regex `id-NNN` do path, `:199-200`). Compare item a item na fixture.
4. Verifique a paginação `?pg=N` no builder/scraper e **documente** como está hoje. Não aumente o número de páginas por run nesta fase.

Testes:
- a fixture de 28/09 deve render 15 itens;
- `year` e `price` presentes em 100% dos itens, e `km` em ≥90%;
- os `external_id` dos 5 itens capturados hoje devem continuar iguais;
- deve existir um teste do fallback, rodando sem o bloco `ItemList`.

### 1B. Mercado Livre → `deprioritized`
Arquivos: `app/sources/builtins.py` (só o bloco do ML), `docs/SOURCES_GUIDE.md` e `docs/MERCADOLIVRE_STRATEGY_MATRIX.md`.
1. No plugin do ML, defina `operational_role="deprioritized"` e `default_enabled=False`, seguindo o padrão da Webmotors. Isso afeta só o seed; **não** altere o banco de produção.
2. Confirme, com a fixture bloqueada da Fase 0, que `_is_ml_security_or_captcha_page` (`app/scrapers/mercadolivre.py:86`) classifica a página como bloqueio, e **não** como `found=0`. O marcador `account-verification` já está em `:95`. Se não houver teste para isso, crie.
3. Confirme que um bloqueio do ML **não** dispara alerta crítico global. Sources `deprioritized` não devem contar como falha de saúde global (ver `docs/SOURCES_GUIDE.md`, seção "Sources despriorizadas e saúde global"). Cite onde isso é aplicado.
4. Atualize os dois docs, registrando:
   - bloqueio anônimo confirmado em 28/09 (`/gz/account-verification`, `suspicious_traffic`);
   - API descartada;
   - login de conta descartado por risco de conta/Mercado Pago e termos de uso;
   - status `deprioritized`.
5. No relatório, liste os comandos que o Marcelo deve rodar no Pi, **sem executar nenhum**:
   - `/admin sources disable mercadolivre`;
   - a checagem das wishlists que hoje dependem só do ML.

**Gate:** fixtures verdes, `external_id` da Chaves na Mão inalterado e docs atualizados.

## Fase 2 — Tirar o Chromium de Kavak e Mobiauto (preparar, não virar)

Arquivos: `app/scrapers/kavak.py`, `app/scrapers/mobiauto.py` e `app/sources/builtins.py` (só `fetch_mode` e defaults).
1. **Kavak:** hoje chama `fetch_html_browser` direto (`app/scrapers/kavak.py:117`). Troque para `fetch_html_with_browser_fallback`, como faz o Mobiauto (`app/scrapers/mobiauto.py:321`). A extração RSC (`_extract_rsc_cars`, `:33-106`) passa a ser o caminho primário do HTTP.
   - Respeite o `Crawl-delay: 20` no rate limit da source. Verifique `rate_limit_kavak_seconds` e o intervalo do agendamento, e documente.
2. **Mobiauto:** confirme que, com `force_browser=False`, o caminho HTTP + `_extract_next_data_deals` (`:168-209`) gera o mesmo conjunto de itens e campos que o browser.
   - Os campos `title` e `thumbnail` devem sair do `__NEXT_DATA__` quando o DOM não estiver disponível. Se hoje dependem do DOM, implemente o mapeamento a partir do JSON (`trim.make`, `trim.model`, `trim.name` e `images`).
3. **Não altere** `force_browser` em produção nem o default de seed nesta fase. Entregue no relatório o plano de rollout:
   - `dual_run` em `compare_only` por ≥24 h no Pi;
   - critério de go/no-go: `found` HTTP ≥95% do browser e preenchimento de campos ≥ o baseline do browser;
   - os comandos `/admin` na ordem.
4. `external_id` idêntico ao atual nas duas sources.

**Gate:** testes com fixture HTTP pura (sem browser) com `year`/`km`/`price` ≥ o baseline da Fase 0, e `external_id` inalterado.

## Fase 3 — OLX: limpeza

Arquivo: `app/scrapers/olx.py`.
1. Remova duplicatas por `listId` dentro da mesma página, que vêm de itens `fixedOnTop`/patrocinados. Não descarte o anúncio.
2. Extraia `gearbox`, `fuel` e `professionalAd` das `properties` como campos extras **somente se** `finalize_listings` (`app/scrapers/contract.py`) já os aceitar sem mudança de schema. Caso contrário, só documente.

**Gate:** zero `listId` duplicado na fixture e `year`/`km` mantidos em 100%.

## Fase 4 — GoGarage e TurboClass

1. **GoGarage** (`app/scrapers/gogarage.py`):
   - rode o parser real contra a fixture da Fase 0 e preencha o baseline pendente;
   - reconcilie a divergência de citação (JSON-LD de 25/09 vs só `WebSite` em 28/09);
   - restrinja a extração aos cards da grade de resultados, excluindo o carrossel de boosts/destaques;
   - **não** migre `external_id` para `data-ad-id`; só avalie no relatório (ADR-0001).
2. **TurboClass** (`app/scrapers/turboclass.py`): exponha a `MOTORIZAÇÃO` (variável `spec`, `:230-232`) como campo extra, por exemplo `engine_tag`, sem mudança de schema. Se exigir schema, só documente.

**Gate:** nenhum item fora do termo buscado na fixture GoGarage e baseline GoGarage preenchido.

## Fora de escopo

- Mercado Livre: extração de ano/km, login, cookies de conta e API.
- Webmotors, iCarros, Facebook Marketplace e leilões.
- `_YearRange_`/`_PriceRange_`.
- Mudanças de schema, mudanças no scorer e deploy.
