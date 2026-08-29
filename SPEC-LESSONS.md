# Spec Lessons

- [005] Scrapers com fetch "hardened" opcional (curl_cffi/cf_requests): não assumir que o ambiente
  de teste roda sem a lib instalada. Se ela estiver disponível, o código real vai preferi-la sobre
  qualquer fallback mais simples — testes que mockam só o fallback (ex.: `fetch_html`) vão bater na
  rede real silenciosamente. Specs para esse tipo de mudança devem exigir explicitamente
  `monkeypatch.setattr(modulo, "cf_requests", None)` (ou equivalente) nos testes que querem
  exercitar o fallback, e mockar o objeto hardened diretamente nos testes que querem exercitar o
  caminho principal — nunca deixar implícito qual caminho um teste está cobrindo.
- [005] Nunca aceitar checks de `"pytest" in sys.modules` (ou similares) que um executor Haiku
  insira para "fazer os testes passarem" — é sempre um sinal de que o teste está mockando a coisa
  errada, não uma correção válida. Revisar todo diff do executor antes de aceitar, mesmo quando o
  relatório diz "OK" e os testes passam — passar com esse tipo de atalho é pior que falhar.
- [010, 012] O `spec-reviewer` valida escopo comparando `git status`/`git diff` do working tree contra os arquivos autorizados da etapa. Como as etapas de uma spec não commitam entre si, esse diff acumula TODAS as etapas anteriores ainda não commitadas — e o revisor de uma etapa N frequentemente reprova por "vazamento de escopo" apontando arquivos que na verdade pertencem à etapa N-1 já aprovada. Antes de aceitar uma reprovação por vazamento de escopo, o orquestrador deve conferir se o(s) arquivo(s) apontado(s) já foram aprovados em etapa anterior da MESMA spec — se sim, é falso positivo, não uma correção real. Specs T2/T3 devem considerar instruir o revisor a comparar apenas contra os arquivos apontados na etapa atual, ignorando os já aprovados.
- [012] Ao paralelizar um loop sequencial que compartilhava um objeto acumulador mutável entre
  iterações (ex.: `HealthCollector` que acumula counters/buckets/`last_error` ao longo do loop),
  não basta dar a cada thread sua própria instância local e fazer merge no final — é preciso
  também mover toda a lógica que ESCREVE nesse acumulador (ex.: classificação de erro que chama
  `set_error`) para dentro do escopo local de cada iteração/thread, ANTES do merge. Escrever
  diretamente no acumulador principal já compartilhado, mesmo fora de uma race condition real
  (ex.: só na thread principal, após todos os `.result()`), ainda quebra invariantes de ordem
  como "primeira falha por ordem original vence", porque a escrita direta ignora a lógica de
  precedência do `merge()` (que só existe no objeto sendo mesclado PARA DENTRO, não no que já
  está lá). Descoberto por um `spec-reviewer-senior` via análise de consequências de
  concorrência — os testes originais (incluindo um teste específico de "ordem determinística
  da falha vencedora") não cobriam esse caso porque só verificavam os campos de retorno de
  topo, não o `last_error` embutido no resumo persistido/logado. Specs que paralelizam loops
  com acumuladores compartilhados devem exigir explicitamente um teste que falhe 2+ iterações
  no mesmo lote e verifique QUALQUER estado persistido/logado derivado do acumulador, não só o
  valor de retorno direto da função.
- [012] Etapas que introduzem novos defaults de `settings` (ex.: teto de concorrência, tamanho de
  pool) podem passar 100% dos testes e ainda assim entregar o valor errado em produção, porque
  todo teste unitário tende a `monkeypatch.setattr(settings, "campo", valor)` para controlar o
  cenário — nenhum teste exercita o default real do arquivo de settings. Neste caso,
  `source_group_max_workers` ficou `int | None = None` (deveria ser `= 4` pelo contrato da spec);
  com `None`, o código de produção resolvia para paralelismo efetivo de 1, anulando o objetivo
  inteiro da spec fora dos testes — só descoberto porque o `spec-verifier` leu o valor literal do
  arquivo e comparou contra o contrato da spec, em vez de confiar na suíte verde. Specs T2/T3 que
  adicionam ou alteram defaults numéricos de configuração devem incluir, no plano de testes, um
  teste que importa `settings` SEM monkeypatch e afirma o valor literal do contrato — e o
  `spec-verifier` deve sempre conferir defaults de produção linha a linha contra a spec, mesmo
  quando a suíte de testes está 100% verde.
