# Skill: setup-pre-commit

Use para propor hooks/checks locais de qualidade adaptados a Python.

## Objetivo

Aumentar segurança local sem tornar o fluxo lento ou pesado.

## Avaliar

- Ruff lint/format, se aplicável.
- Pytest seletivo ou smoke tests leves.
- Checagem de secrets.
- Checagem de arquivos grandes, cache e debug artifacts.
- Proteção contra alteração acidental de migrations críticas.
- Custo aceitável para uso local.

## Processo

1. Inspecione stack e ferramentas já presentes.
2. Proponha hooks mínimos.
3. Evite ferramenta pesada sem benefício claro.
4. Documente instalação e bypass seguro.
5. Rode validação local.

## Regras AutoHunter

- Não assumir stack Node/Husky.
- Preferir tooling Python simples.
- Considerar Raspberry e máquinas modestas.
- Não bloquear commits por teste lento demais.
