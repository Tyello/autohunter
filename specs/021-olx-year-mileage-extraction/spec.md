# Spec 021 — OLX: extrair ano/km na origem e corrigir badge de recência

`[spec-kit: T2 — 6pts: arquivos=1 (arquivos=2 principais + 1 formatter), decisões=2, risco=1, novidade=0, verif=1]`

## Diagnóstico que origina esta spec

Investigação read-only (sessão anterior, sem código alterado) concluiu que:

- O scraper OLX ligado em produção (`app/sources/builtins.py:26,84` → `scrape_olx`) só produz `OlxItem(external_id, title, url, thumbnail_url, price, currency, location)` (`app/scrapers/olx.py:161-169`). **Nunca** extrai `year`/`mileage_km`, em nenhum dos três caminhos de parse (`_extract_items_from_next_data`, `_fallback_parse_from_cards` — constrói `OlxItem` em `app/scrapers/olx.py:761-769` — e o dict final em `_items_to_dicts`, `app/scrapers/olx.py:477-492`).
- `app/sources/normalize.py:320-321` (`pick("km","mileage_km","mileage")` / `pick("year","year_model","ano")`) está correto — ele só não recebe essas chaves para anúncios OLX porque o scraper nunca as popula. Não mexer nesse arquivo.
- FIPE/preço-mercado/raridade caem em cascata (`app/services/notifications_queue_service.py:332-341`) porque as chaves de cohort/FIPE dependem de `year`, que chega `None`. `score_ad` já defaulta honestamente — **não mexer no scorer**.
- Existe uma segunda classe, `OLXScraper` (`app/scrapers/sources/olx.py`), com extração de `year`/`mileage_km` — mas via API própria da OLX (`API_URL`, `raw_data["properties"]`) desconectada do fluxo de produção (que usa HTML/`__NEXT_DATA__`/RSC). Essa classe **não** é religada por esta spec — arriscado demais (API pode estar desatualizada/bloqueada; é por isso que a produção migrou para o parser HTML). O que é reaproveitado é só a lógica de **fallback por regex sobre o título**, que é auto-contida e funciona em qualquer um dos três caminhos de parse do `scrape_olx`: `_extract_from_title` em `app/scrapers/sources/olx.py:284-290+` (regex de ano: `\b(19\d{2}|20\d{2})\b`).
- O badge "🆕 Novo" (`app/notifications/telegram_formatter.py`, função `build_recency_badge` iniciando em `app/notifications/telegram_formatter.py:334`) cai no fallback de `created_at` (nosso timestamp de ingestão, não a data real do anúncio) quando não há data de publicação confiável — o texto "🆕 Novo" fica no fallback em torno de `app/notifications/telegram_formatter.py:371-378`. Mesma causa raiz (falta de dado na origem), mas correção independente do texto do badge.

## Objetivo

1. Fazer `scrape_olx` extrair `year` e `mileage_km` a partir do **título** do anúncio (fallback regex, sem nova requisição HTTP), populando essas chaves no dict retornado, para que `normalize.py:320-321` deixe de receber `None` para anúncios OLX cujo título contenha essa informação.
2. Corrigir o texto do badge de recência para não afirmar "carro novo" quando na verdade é "anúncio novo no nosso feed" (dado não confiável).

## Não-objetivos

- Não religar a classe `OLXScraper` (`app/scrapers/sources/olx.py`) nem seu fetch via API própria.
- Não buscar a página de detalhe do anúncio para extrair `year`/`km` estruturados — fica fora de escopo (custo de requisição extra + anti-bot); só o título, que já está disponível sem custo adicional.
- Não alterar `app/sources/normalize.py`, `app/services/notifications_queue_service.py`, `app/services/market_stats_service.py`, `app/services/fipe_service.py`, nem `app/scoring/score_v2.py` — essas camadas já funcionam corretamente dado um input completo.
- Não implementar a opção B do diagnóstico (guard de contrato em `app/scrapers/contract.py` sinalizando listings incompletos) — fica para uma spec futura, se ainda for necessária depois desta correção.
- Não tentar extrair `make`/`model` (já tem fallback parcial existente e funcionando via `normalize.py`).

## Decisões tomadas

- **Fonte do dado**: só o título (`OlxItem.title`), via regex. Não usar `raw_data["properties"]` do OLXScraper (não confirmado que a JSON de busca atual carrega esse array).
- **Ponto único de inserção**: `app/scrapers/olx.py`, dentro de `_items_to_dicts` (`app/scrapers/olx.py:477-492`) — como todo `OlxItem`, independente de qual dos 3 parsers o gerou, chega ali com `.title` preenchido, é o ponto que cobre os três caminhos sem duplicar lógica em cada parser.
- **Regex de ano**: portar `\b(19\d{2}|20\d{2})\b` de `app/scrapers/sources/olx.py:290` (já testado nesse arquivo). Pegar o **último** match do título (ano do veículo geralmente vem depois da versão/motorização no título OLX, ex. "Honda Fit 2007 1.4"), não o primeiro — decisão nova desta spec porque o parser antigo pegava o primeiro grupo, que pode casar com um número de versão/potência de 4 dígitos coincidente; usar o último reduz esse risco. Validar contra os títulos reais nos fixtures antes de finalizar (etapa 2).
- **Regex de km**: NÃO portar a regex antiga de `app/scrapers/sources/olx.py` verbatim — ela retorna a substring bruta ("50mil k"), não um valor coerente. Escrever regex nova capturando `\d{1,3}(?:\.\d{3})+\s*[Kk][Mm]\b|\b\d{4,6}\s*[Kk][Mm]\b` e passar a string capturada (com "km" incluso) direto para a chave `"km"` do dict — `normalize.py:320` já chama `normalize_mileage_km()`, que faz `.replace("km","")` e parse (`app/sources/normalize.py:74`), então o scraper não precisa converter para `int` ele mesmo.
- **Badge**: manter o mecanismo de fallback (`build_recency_badge`) como está — não é bug de lógica, é rótulo. Trocar o texto do branch de fallback de `created_at` (hoje "🆕 Novo") para algo que não implique "carro novo", ex. "🆕 Anúncio novo no feed" (texto exato a decidir na etapa 4, olhando o branch confiável para não colidir visualmente).

## Premissas assumidas

- **PREM-01**: os títulos de anúncio OLX seguem o padrão observado nos fixtures existentes (`tests/fixtures/olx/*.html`, spec 005) — ano de 4 dígitos e km com sufixo "km", eventualmente com separador de milhar. Se a extração falhar silenciosamente para uma amostra real fora desse padrão, o campo continua `None` (mesmo comportamento de hoje — não piora nada) e fica registrado no RUN.md para spec futura.
- **PREM-02**: nenhum teste existente depende do dict retornado por `_items_to_dicts` **não** conter `year`/`km` — confirmar na etapa 1 antes de mudar o shape do dict.

## Etapas

### Etapa 1 — Ler contratos existentes e confirmar shape do dict
**FAZ**: Ler `app/scrapers/contract.py` (`_CORE_KEYS`, linha ~49, e a função que usa `extras` na linha ~105) e `tests/test_scraper_parsing.py` (função `test_olx_extracts_next_data_json`, linha 52+) para confirmar que adicionar `"year"`/`"km"` ao dict de saída de `_items_to_dicts` não quebra nenhuma asserção de shape exato (ex. `assert set(d.keys()) == {...}`).
**TOCA**: nenhuma edição — só leitura.
**VALIDA COM**: relatar no RUN.md se algum teste faz asserção de shape fechado no dict OLX. Se sim, decisão residual → escalar para spec-resolver com a lista exata dos testes afetados.
**ESCALA SE**: existir teste com `assert set(keys) == ...` ou equivalente que precise ser atualizado — a atualização em si é trivial (T1), mas exige confirmação humana de que a lista de campos esperada muda de propósito.

### Etapa 2 — Implementar `_extract_year_from_title` e `_extract_km_from_title`
**FAZ**: Em `app/scrapers/olx.py`, adicionar duas funções privadas (perto de `_items_to_dicts`, antes dela):
- `_extract_year_from_title(title: str) -> Optional[str]`: usa `re.findall(r"\b(19\d{2}|20\d{2})\b", title)`, retorna o último elemento se a lista não for vazia, senão `None`.
- `_extract_mileage_from_title(title: str) -> Optional[str]`: usa `re.search(r"\d{1,3}(?:\.\d{3})+\s*[Kk][Mm]\b|\b\d{4,6}\s*[Kk][Mm]\b", title)`, retorna `m.group(0)` se casar, senão `None`.
Escrever 6-8 casos de título reais (retirados dos fixtures de `tests/fixtures/olx/` da spec 005, ex. títulos que contenham "2007", "2015", "45.000 km" etc.) como docstring de exemplo ou comentário curto acima de cada função, só para consulta — não é obrigatório.
**TOCA**: `app/scrapers/olx.py` (funções novas).
**VALIDA COM**: `rtk python -c "from app.scrapers.olx import _extract_year_from_title, _extract_mileage_from_title as m; print(_extract_year_from_title('Honda Fit 2007 1.4 Flex')); print(m('Honda Fit 2007 45.000 km'))"` — deve imprimir `2007` e `45.000 km`.
**ESCALA SE**: os títulos reais dos fixtures não casarem com nenhuma das duas regexes em nenhum caso de teste — decisão residual sobre novo padrão de regex.

### Etapa 3 — Popular `year`/`km` no dict de `_items_to_dicts`
**FAZ**: Em `_items_to_dicts` (`app/scrapers/olx.py:477-492`), para cada item, chamar as duas funções da etapa 2 sobre `it.title` e incluir `"year": ...` e `"km": ...` no dict resultante (mesmo padrão dos campos já existentes na função).
**TOCA**: `app/scrapers/olx.py` (`_items_to_dicts`).
**VALIDA COM**: `rtk python -m pytest tests/test_scraper_parsing.py -k olx -v` — deve passar; e um teste novo (ver etapa 5) que monta um `OlxItem` com título "Honda Fit 2007 1.4 Flex 45.000 km" e confirma que `_items_to_dicts([item])[0]["year"] == "2007"` e `["km"] == "45.000 km"`.
**ESCALA SE**: `_CORE_KEYS`/testes de shape (etapa 1) travarem a asserção mesmo com o ajuste — decisão sobre extras vs. core key.

### Etapa 4 — Corrigir texto do badge de recência
**FAZ**: Em `app/notifications/telegram_formatter.py`, no branch de fallback de `build_recency_badge` (em torno da linha 371-378, onde hoje retorna o texto com "🆕 Novo" quando a data não é confiável), trocar o texto para não afirmar que o carro é novo — ex. "🆕 Anúncio novo no feed" (ajustar redação exata se colidir em tamanho/formatação com o branch confiável, que deve permanecer inalterado).
**TOCA**: `app/notifications/telegram_formatter.py`.
**VALIDA COM**: localizar teste(s) existentes de badge (`rtk grep "build_recency_badge\|🆕" tests/`) e rodar `rtk python -m pytest <arquivo_do_teste> -v`; atualizar a string esperada nos testes existentes se eles fixarem o texto antigo.
**ESCALA SE**: não existir nenhum teste cobrindo o branch de fallback hoje — está OK escrever um novo teste mínimo (mesma etapa, não escala) confirmando `reliable=False` → texto novo.

### Etapa 5 — Testes novos de extração OLX
**FAZ**: Em `tests/test_scraper_parsing.py`, adicionar `test_olx_extracts_year_and_mileage_from_title()` e `test_olx_missing_year_or_mileage_returns_none()` cobrindo: título com ano e km presentes, título sem km (retorna `None` só para km), título sem nenhum dos dois. Usar `_extract_year_from_title`/`_extract_mileage_from_title` diretamente (unit) e `_items_to_dicts` com um `OlxItem` construído manualmente (integração leve).
**TOCA**: `tests/test_scraper_parsing.py`.
**VALIDA COM**: `rtk python -m pytest tests/test_scraper_parsing.py -v` — todos passam, incluindo os pré-existentes.
**ESCALA SE**: nenhum gatilho esperado (etapa mecânica).

## Critérios de aceitação globais (EARS)

- **REQ-001**: Quando `scrape_olx` processa um anúncio cujo título contém um ano de 4 dígitos entre 1900-2099, o dict retornado por `_items_to_dicts` DEVE conter a chave `"year"` com esse valor (o último match, se houver mais de um).
- **REQ-002**: Quando `scrape_olx` processa um anúncio cujo título contém uma quilometragem no formato `\d[.\d]*\s*km` (case-insensitive), o dict retornado DEVE conter a chave `"km"` com a substring casada.
- **REQ-003**: Quando o título não contém ano ou km reconhecíveis, a chave correspondente DEVE ser `None` (nunca lançar exceção, nunca quebrar o restante do dict).
- **REQ-004**: O badge de recência exibido quando a data de publicação não é confiável (`reliable=False`) NÃO DEVE conter o texto "🆕 Novo" implicando veículo novo.
- **REQ-005**: Nenhum teste pré-existente em `tests/test_scraper_parsing.py` ou nos testes de badge quebra após as mudanças (rodar suíte completa relevante).

## Gate de fechamento

Nenhuma pergunta em aberto pendente de decisão do usuário — todas as escolhas de regex/texto foram travadas na seção "Decisões tomadas" acima como premissas assinadas (PREM-01, PREM-02). Se a etapa 1 ou 2 revelar que os fixtures reais não seguem o padrão assumido, a etapa correspondente escala para `spec-resolver` em vez de decidir sozinha.
