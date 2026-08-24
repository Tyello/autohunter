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
