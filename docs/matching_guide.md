# Matching “leve” (anti falso-positivo)

Problema clássico em entusiastas:

- wishlist: **"civic si"**
- fontes devolvem: todo tipo de **Civic** (LXR/EXR/Touring/Type-R...)

A solução do AutoHunter é um matching **token-level** (e regras semânticas opcionais) antes de gerar alerta.

## Onde está implementado

- `app/core/text_norm.py`: normalização (acentos/pontuação)
- `app/services/matching_service.py`: match AND por tokens + filtros (price/source)
- `app/services/wishlist_semantic_rules.py`: regras específicas (ex.: Civic Si / Hatch)
- `tests/test_query_match.py`: exemplos de casos

## Como evoluir (sem virar “IA pesada”)

1) **Curadoria por modelo** (mais valor, zero custo de infra)
   - adicionar regras em `wishlist_semantic_rules.py`
   - exemplos de tokens úteis: `vtec`, `manual`, `b16`, `b18`, `k20`, `eg`, `ek`, `dc2` (depende do nicho)

2) **Filtros por wishlist** (MVP já suporta)
   - `source eq <fonte>`
   - `price gte/lte <valor>`

3) **Próximo nível** (roadmap)
   - ano mínimo, km máximo, UF/cidade
   - “excluir termos” por wishlist (UI no bot)

> Curadoria é vantagem competitiva: melhora o sinal sem aumentar crawling.
