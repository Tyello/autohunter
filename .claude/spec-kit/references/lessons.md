# Camada de Lições — triagem, promoção e destinos

O spec-kit aprende com as próprias falhas: escalações resolvidas, DVGs de revisão e lacunas do verificador são colhidas como lições. O objetivo é errar cada erro **uma vez por projeto**. Esta referência define quem colhe, como triar e quando promover.

## Quem colhe (pontos de colheita)

- **spec-resolver** — ao fechar qualquer escalação ou defeito de spec: o diagnóstico já está em mãos; triagem custa 3 linhas.
- **spec-verifier** — ao emitir veredito: mutante sobrevivente e REQ sem teste são lições por definição.
- **orquestrador** — ao encerrar a spec: se o RUN.md mostrar padrão (ex.: 3 escalações do mesmo tipo), destile a lição agregada.

## Triagem por granularidade (decide O DESTINO)

| Achado | Destino |
|---|---|
| One-off genuíno (não vai se repetir) | **descarta** — não polua o contexto futuro |
| Fato ou correção de 1-2 linhas | **`SPEC-LESSONS.md`** na raiz do repo |
| Convenção que já causou 2+ falhas/escalações | **promove a `SPEC-CONSTITUTION.md`** (princípio inegociável) |
| Procedimento multi-step reutilizável (caminho dourado) | **skill própria** em `.claude/skills/learned/<nome>/SKILL.md` |

## Regra de promoção (decide A CONFIANÇA)

Lição só vira conhecimento **autoritativo** (constituição ou skill) quando as TRÊS condições valem:

1. **Verificação real passou** — teste verde, build limpo, repro reproduzido. "Pareceu funcionar" não conta.
2. **Padrão de falha nomeado** — a falha que a lição evita ou diagnostica tem nome explícito.
3. **Beco sem saída descartado** — pelo menos uma abordagem concreta foi tentada e eliminada, e está registrada.

Faltou qualquer uma → fica em `SPEC-LESSONS.md` marcada `[não verificada]`, ou é descartada. Palpite promovido a regra é pior que ignorância: a próxima sessão confia sem re-derivar.

## Formato da lição em SPEC-LESSONS.md

```md
- [2026-07-14 | ISSUE/spec-005 | verificada] Validação do schema `case.json` aceita
  `suspects: []` silenciosamente; specs que tocam geração de caso devem incluir teste
  de lista vazia. Beco descartado: validar no prompt do gerador (modelo ignora sob carga).
```

Uma linha de data/origem/status + 1-3 linhas de conteúdo. Registre o beco sem saída sempre que existir — ele economiza mais token que o acerto, porque impede a re-exploração.

## Como as lições são consumidas

- O **planejador** lê `SPEC-LESSONS.md` (junto da constituição) antes de escrever qualquer spec T2/T3, e incorpora as lições pertinentes como critérios/decisões — a lição vira spec, não fica só como aviso.
- Skills colhidas em `.claude/skills/learned/` carregam sozinhas por description matching quando o assunto aparecer.
- **Poda**: se `SPEC-LESSONS.md` passar de ~40 lições, o planejador propõe consolidação — promover recorrentes à constituição, deletar obsoletas. Lição demais no contexto é tão ruim quanto nenhuma.

## Segurança (inegociável)

Lições e skills colhidas são commitadas e potencialmente compartilhadas. NUNCA escreva valores de segredos (senha, token, connection string, API key). Registre apenas ONDE encontrar: nome da env var, secret manager, arquivo de config ignorado pelo git.
