# Guia de matching (anti falso-positivo)

Problema clássico em entusiastas:

- wishlist: **"civic si"**
- fontes devolvem: todo tipo de **Civic** (LXR/EXR/Touring/Type-R...)

A solução do AutoHunter é um matching **token-level** (com regras semânticas opcionais) antes de gerar o alerta.

## Onde está implementado

- `app/core/text_norm.py`: normalização (acentos/pontuação)
- `app/services/matching_service.py`: match AND por tokens + filtros (preço/fonte)
- `app/services/wishlist_semantic_rules.py`: regras específicas (ex.: Civic Si / Hatch)
- `tests/test_query_match.py`: exemplos de casos

## Como evoluir (sem virar “IA pesada”)

### 1) Curadoria por modelo (alto valor, baixo custo)

- adicionar regras em `wishlist_semantic_rules.py`
- exemplos de tokens úteis: `vtec`, `manual`, `b16`, `b18`, `k20`, `eg`, `ek`, `dc2` (depende do nicho)

### 2) Filtros por wishlist (MVP já suporta)

- `source eq <fonte>`
- `price gte/lte <valor>`

### 3) Próximo nível (roadmap)

- ano mínimo, km máximo, UF/cidade
- “excluir termos” por wishlist (UI no bot)

> Curadoria é vantagem competitiva: melhora o sinal sem aumentar crawling.
