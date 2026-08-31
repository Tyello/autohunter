# Revisão da suíte de testes (256 arquivos)

Revisão completa da suíte, feita em 5 blocos temáticos por agentes independentes (mesma
metodologia do `DEAD_CODE_AUDIT.md`: conservador, nunca recomenda cortar teste de segurança/DB,
prefere `parametrize`/consolidação a remoção, sinaliza dúvida de arquitetura em vez de tentar
resolver por conta própria).

## Resumo geral

A suíte está em bom estado. Não há testes vazios (`assert True`, `pass`), nem testes que mockam
a própria função sob teste, em nenhum dos 5 blocos. O padrão dominante são testes específicos com
asserções sobre saída real (renderizada/persistida), o que é coerente com um produto rodando 24/7
sem supervisão constante. **Não há motivo para uma limpeza ampla.** As oportunidades reais são
pontuais: consolidar duplicação via `parametrize`, e um punhado de itens de baixo risco.

## Achados por bloco

### 1. Matching / Wishlist filters (33 arquivos)
- **Maior ganho da revisão inteira:** os 5 arquivos `test_matching_*_filters.py` testam o mesmo
  motor genérico de operadores para campos diferentes, com helpers duplicados — consolidar em um
  arquivo parametrizado por campo elimina ~500 linhas sem perder cobertura.
- Os 4 arquivos `test_wishlist_filters_*.py` (doors/mileage/seller_type/body_type) repetem a
  mesma estrutura de 4 testes (aliases de campo, aliases de valor, duplicado, valor inválido) —
  mesma oportunidade, camada diferente (parsing de linguagem natural).
- **Achado de qualidade (não de duplicação):** em `test_facet_search_service.py`, dois testes
  (`test_year_filter_extraction`, `test_facet_counts_with_year_filter`) têm comentários no
  próprio código admitindo que não exercitam de fato o cenário pretendido (extração de filtro de
  ano do termo de busca). Vale reforçar essas asserções antes de qualquer refatoração, para não
  formalizar um buraco de cobertura como se fosse teste válido.

### 2. Scrapers / Sources (~54 arquivos no escopo)
- Nenhum teste de scraper/anti-bot é redundante a ponto de merecer remoção — cada fonte (ML, OLX,
  Webmotors, iCarros, Turboclass, leilões) tem particularidades reais de HTML/anti-bot
  documentadas com fixtures reais ou casos de bug relatado.
- Webmotors e Mercado Livre têm cobertura de resiliência desproporcionalmente maior (Webmotors:
  14 testes de fallback curl_cffi/browser/proxy; ML: 5 arquivos dedicados). **Turboclass tem só 1
  teste, sem nenhum caso de erro/borda** — é o scraper com a maior lacuna de cobertura do grupo,
  não o com testes sobrando.
- 5 arquivos com oportunidade de reorganizar/parametrizar (não remover): split de
  `test_mercadolivre_scraper.py` por legibilidade, fundir/realocar `test_scraper_parsing.py`,
  parametrizar os 5 testes de curl_cffi em `test_webmotors_scraper_resilience.py`, realocar
  testes de admin bot que estão em `test_webmotors_warmup_diagnostics.py`, e trocar
  `time.sleep` real por clock fake em `test_circuit_breaker.py`.
- O trio `test_source_v2_inventory.py` / `test_source_v2_readiness.py` /
  `test_source_impl_alignment.py` não foi lido a fundo e é o candidato mais provável a
  sobreposição real — merece uma segunda passada dedicada.

### 3. FIPE / Notificação / Digest (48 arquivos)
- **Duplicação arquitetural de weekly digest**: dois serviços de produção paralelos
  (`weekly_digest_*` vs `weekly_wishlist_digest_*`). Não é problema de teste — é pergunta de
  arquitetura que merece investigação própria antes de qualquer corte.
- `test_auction_readiness_service.py` é um shim de compatibilidade sem uso comprovado no repo —
  candidato a remoção de baixo risco.
- Oportunidade organizacional de baixo ganho: fundir `test_sender_job.py` +
  `test_sender_micro_batch.py` + `test_sender_daily_limit.py`; parametrize opcional em
  `test_telegram_formatter_vnext.py`.
- Nenhum teste de baixa qualidade encontrado neste grupo — cobertura consistentemente bem
  direcionada a comportamento real, incluindo condições de corrida e edge cases numéricos.

### 4. Bot / Admin (36 arquivos)
- **Teste genuinamente inútil encontrado:** em `test_handlers_buscar_agora.py`, um teste monta e
  verifica um dict Python local, sem tocar código de produção — candidato claro a remoção.
- Padrão de duplicação real: guard de "bloqueia não-admin" reimplementado individualmente por
  subcomando em `test_admin_auctions_commands.py` (9 ocorrências) — parametrizar reduz ~9 testes
  a 1 sem perder cobertura.
- Qualidade geral alta em todos os 36 arquivos. Não recomendo remoções amplas.

### 5. Infra / DB / Scheduler (79 arquivos, ~330 funções)
- `test_pairing_one_time_and_ttl` em `test_fb_pairing.py` duplica dois testes já existentes em
  `test_fb_pairing_validation.py` — seguro remover.
- Boilerplate duplicado 3x nos testes de registro de job do scheduler
  (`test_scheduler_fipe_registration.py` / `_fipe_lookup_registration.py` /
  `_weekly_digest_registration.py`) — mesma `_FakeScheduler` colada em cada arquivo. Candidato
  claro a parametrização.
- **Nenhum teste de segurança/DB é candidato a remoção** — `test_delete_safety.py`,
  `test_db_guardrails.py`, os testes de backup e os de `car_listings_repo` (upsert) são todos de
  alto valor; a única "simplificação" possível é reorganização de arquivo, nunca redução de
  cobertura.

## Recomendação

Não recomendo nenhuma ação de limpeza ampla ou urgente. Se for fazer algo, priorizar nesta ordem:
1. Consolidação `test_matching_*_filters.py` + `test_wishlist_filters_*.py` (maior ganho, ~500+
   linhas).
2. Remover a duplicação confirmada em `test_fb_pairing.py` e o teste morto em
   `test_handlers_buscar_agora.py` (baixo risco, ganho imediato).
3. Investigar a duplicação arquitetural `weekly_digest_*` vs `weekly_wishlist_digest_*` como item
   separado — é uma decisão de produto/arquitetura, não de teste.

Tudo o mais é opcional e de baixo risco/baixo ganho.
