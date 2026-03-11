# Testes de regressão por source com fixtures

Estrutura padrão (por source e cenário):

```text
tests/fixtures/source_regression/<source>/<scenario>/
  listing.html
  detail_<id>.html (ou detail.html)
  expectations.json
```

## expectations.json
- `required_fields`: campos que **devem** existir em qualquer registro do cenário.
- `records.<external_id>.must_have`: campos críticos esperados para aquele anúncio.
- `records.<external_id>.optional_absent`: campos opcionais que podem faltar sem falha.

Isso evita falso positivo quando a source não expõe um campo no fixture.

## Como promover nova fixture
1. Salvar HTML bruto de listagem e detalhe no cenário da source.
2. Atualizar `expectations.json` com os IDs e campos esperados.
3. Rodar:

```bash
pytest -q tests/test_source_regression_fixtures.py
```

## Escopo atual
- `icarros`: regressão de listagem + detail enrichment.
- `mercadolivre`: regressão de listagem + complemento de preço via VIP/detail.
