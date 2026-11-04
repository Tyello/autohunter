# Testes

Pirâmide do AutoHunter: **unitários → integração → e2e**, com **teste de mutação** como medida de
qualidade dos testes de domínio. A suíte roda em SQLite (sem credenciais reais, sem rede).

| Camada | Onde | O que prova | Como rodar |
|---|---|---|---|
| Unitário / integração | `tests/test_*.py` | regra de domínio, serviços com banco de teste | `pytest -n auto -m "not e2e"` |
| End-to-end | `tests/e2e/` | caminho oficial `wishlist → source → ingestão → dedupe → matching → fila → sender` | `pytest -m e2e` |
| Mutação | `tools/mutation_test.py` | os testes **detectam defeitos** de verdade (não só executam linhas) | `py tools/mutation_test.py app/services/<modulo>.py` |

## Rodar

```bash
pip install -r requirements.txt -r requirements.dev.txt
pytest -n auto -m "not e2e"     # ~1 min (era >10 min serial)
pytest -m e2e                   # fluxo completo, fronteiras externas falsas
```

Por que ficou rápido: `tests/conftest.py` cria o schema **uma vez por processo** e cada teste só
esvazia as tabelas (antes: `drop_all`+`create_all` de ~31 tabelas por teste, ~0,7 s × 2.300). Com
`pytest-xdist` cada worker usa o **próprio arquivo SQLite**; compartilhar um arquivo entre workers
apaga as tabelas uns dos outros (`no such table`).

## E2E

`tests/e2e/test_pipeline_e2e.py` registra um **plugin real** (`SourcePlugin`) no registro real e só
falsifica as duas fronteiras externas: a página da source (`plugin.scrape`) e o Telegram (`sender_fn`).
Banco, ingestão, dedupe, matching, fila, limites de plano e sender rodam de verdade.

Cenários: ingestão+match+envio; reexecução sem duplicar nem renotificar; limite diário do plano
Free; falha da source sem alerta. Um `xfail(strict=True)` documenta um **bug conhecido** (busca de
uma palavra nunca vira candidata — ver abaixo) e passa a falhar quando alguém corrigir, para o
marcador ser removido.

Limite do SQLite: só há um escritor. Cada grupo de busca roda em sessão própria (como em produção);
o fixture confirma a sessão do teste antes de cada grupo para emular o isolamento do Postgres.

## Mutação

`tools/mutation_test.py` usa [cosmic-ray](https://cosmic-ray.readthedocs.io) (o `mutmut` não roda em
Windows: exige `os.fork`). Ele **copia o repositório** para `.data/mutation/<modulo>/repo` — o código
real nunca é alterado — descobre os testes que importam o módulo, executa os mutantes e grava
`result.json` com score, sobreviventes (linha + operador) e a matriz *teste → mutantes que mata*.

- Cada mutante roda `pytest` (~4 s); módulo de ~80 linhas ≈ 190 mutantes ≈ 12 min. Rode por módulo.
- Mutantes `A | B` são excluídos (só aparecem em anotações de tipo, são equivalentes).
- `# pragma: no mutate` exclui uma linha (use só para equivalentes comprovados).
- Workflow manual: *Actions → Mutation testing*.

**Leitura do resultado**
- Mutante **sobrevivente** = comportamento que nenhum teste protege → escreva o teste (fronteiras,
  valores padrão, entradas inválidas, ramos de erro).
- Teste que **não mata nenhum mutante** do módulo que cobre e não tem linha exclusiva → candidato a remoção.

## Quando um teste é "necessário"

Um teste fica se **pelo menos um** vale:

1. mata um mutante que nenhum outro mata;
2. cobre linhas de produção que nenhum outro cobre;
3. é e2e de um fluxo do `AGENTS.md` (caminho oficial, leilões, gates de notificação, billing).

Cobertura de linhas **sozinha não basta para apagar**: dois testes podem executar as mesmas linhas com
asserções diferentes. A análise por contexto (`coverage run` com `dynamic_context = test_function`)
só aponta candidatos; a remoção exige evidência de mutação ou duplicata exata.

## Bug conhecido revelado pelo e2e

`candidate_wishlist_ids_for_listing_tokens` (`app/services/wishlist_tokens_service.py`) exige
`min_overlap=2` tokens em comum. Uma busca de **uma palavra** (`defender`, `cuore`, `rs4`) tem no
máximo 1 token no índice e **nunca é candidata** no matching do scheduler — só recebe alertas no
backfill da criação. Em produção (03/11/2026): os últimos alertas dessas buscas são de junho, apesar
de 217 anúncios de "defender" nos últimos 30 dias.
