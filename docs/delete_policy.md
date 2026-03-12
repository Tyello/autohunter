# Política de deleção segura (AutoHunter)

## Decisão arquitetural

O AutoHunter **não permite deleção implícita por cascade** (`ON DELETE CASCADE`) em relações de domínio.

Motivação:
- reduzir risco operacional em produção;
- evitar remoção silenciosa de dados críticos;
- exigir fluxos de exclusão explícitos, auditáveis e com tratamento de erro claro.

## Regras

- FKs críticas de domínio usam `RESTRICT` (ou `NO ACTION` equivalente).
- Referências opcionais de telemetria podem usar `SET NULL`.
- Relacionamentos ORM não devem usar `delete-orphan`/`cascade` destrutivo para apagar árvores sem comando explícito.
- Qualquer remoção em cadeia deve acontecer por código explícito no serviço responsável.

## Implementação

- Migration corretiva (`9a6f3e2d1c4b_remove_fk_cascades`) recria FKs que antes permitiam cascade com política restritiva.
- Serviços de remoção (ex.: wishlist) fazem limpeza explícita de dependências antes de remover o registro pai.
