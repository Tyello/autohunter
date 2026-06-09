# Skill: zoom-out

Use quando a análise estiver presa em arquivo/função e precisar recuperar o fluxo completo do produto.

## Objetivo

Entender o sistema antes de alterar código.

## Processo

Antes de propor mudança, explique:

1. Qual fluxo maior este trecho pertence.
2. Quem chama.
3. Que dados entram e saem.
4. Que tabela, configuração ou runtime participa.
5. Que comportamento chega ao usuário no Telegram.
6. Quais contratos não podem quebrar.

Depois proponha a menor intervenção segura.

## Regras AutoHunter

- Telegram é a jornada principal.
- FastAPI é superfície auxiliar.
- Sources são DB-driven em operação.
- Nem todo plugin existente está ativo em produção.
- Runtime e documentação histórica podem divergir; confirme no código.
