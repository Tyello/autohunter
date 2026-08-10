# SPEC-LESSONS — lições colhidas pelo spec-kit

Formato: - [data | origem | verificada|não verificada] lição em 1-3 linhas + beco descartado, se houver.
Poda: acima de ~40 lições, consolidar (promover recorrentes à constituição, deletar obsoletas).
Nunca registrar valores de segredos — apenas onde encontrá-los.

- [2026-07-29 | resolver ISSUE-33.14 STEP-03 | verificada] Ao distinguir "veredito fresco do LLM" de "veredito legado/persistido" quando a spec não define marcador de versão explícito, usar como sinal a presença de campos que a doutrina do sistema proíbe o modelo de retornar (ex.: `classification`/`warnings`, calculados só em Python) — se esses campos já estão no dict bruto, é reload de artefato antigo, não resposta nova.
