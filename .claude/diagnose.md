# Skill: diagnose

Use quando houver bug, regressão, falha de build, problema visual, erro de PDF, comportamento inesperado do validator, pacote quebrado ou inconsistência sem causa óbvia.

## Procedimento

1. Leia `AGENTS.md` e `docs/LLM_CONTEXT.md`.
2. Reproduza o problema no menor escopo possível.
3. Separe sintoma, hipótese e evidência.
4. Liste 1 a 3 causas prováveis.
5. Instrumente o mínimo necessário.
6. Corrija apenas a causa comprovada.
7. Adicione teste de regressão quando viável.
8. Valide com os comandos compatíveis com o escopo.

## Comandos típicos

```bash
pytest tests/ -q
ruff check generator/
python -m generator.validator examples/caso_canonico_iniciante.json --strict
python -m generator.validator examples/caso_canonico_intermediario.json --strict
python -m scripts.build_package examples/caso_canonico_iniciante.json --output output/iniciante --strict
python -m scripts.build_package examples/caso_canonico_intermediario.json --output output/intermediario --strict
```

## Guardrails

- Não refatore áreas não relacionadas.
- Não use PDF fake como prova de baseline visual real.
- Não transforme documento de jogador em gabarito.
- Não abra feature nova durante diagnóstico.
- Não reabra decisões já estabilizadas sem evidência nova de teste, PDF ou playtest.

## Resposta final

Informe:

- skill: `diagnose`;
- sintoma confirmado;
- causa raiz;
- arquivos alterados;
- teste/regressão;
- comandos e resultados;
- limitações de ambiente;
- próxima pendência real, se existir.
