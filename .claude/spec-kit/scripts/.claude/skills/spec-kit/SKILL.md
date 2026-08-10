---
name: spec-kit
description: Classifica toda tarefa de código em tiers de complexidade (T0-T3), gera specs proporcionais ao tier e roteia a execução automaticamente para o modelo mais barato (Haiku por padrão; Sonnet apenas em decisões e desbloqueios). Use esta skill em TODA tarefa de código — implementação, refatoração, correção de bug, feature nova, script — mesmo que o usuário não mencione "spec", "planejamento" ou "modelo". Ela decide sozinha quando a spec vale a pena, quando pular direto para a execução, e quando escalar de modelo.
---

# Spec-Kit: Especificação proporcional por tier + roteamento automático de modelo

## Objetivo

Toda tarefa de código passa primeiro por uma **classificação de tier**. O tier determina quanto esforço de especificação vale a pena antes de executar. A lógica econômica: specs profundas custam tokens no planejamento, mas permitem que a execução rode **inteiramente no Haiku** com baixa taxa de retrabalho. O Sonnet só entra em dois momentos: (1) escrever a spec e tomar decisões, (2) resolver escalações quando o Haiku trava.

Regras de ouro:
1. **Quanto maior a tarefa, mais profunda a spec; quanto menor, mais direto ao código.**
2. **Haiku é o executor padrão. Sempre. Sonnet é exceção, nunca rota principal de execução.**

## Roteamento automático de modelo

Esta skill vem com cinco subagentes prontos (instale-os em `.claude/agents/` do projeto — ver seção "Instalação"):

- **`spec-executor`** (`model: haiku`) — executa etapas da spec. Recebe APENAS: a etapa atual, os arquivos que ela toca e o critério de validação. Nunca recebe o histórico da conversa.
- **`spec-reviewer`** (`model: haiku`) — revisão mecânica pós-execução: `git diff` ⊆ arquivos autorizados, nada de brinde, evidência de validação obrigatória. Não julga design.
- **`spec-reviewer-senior`** (`model: sonnet`) — revisão de etapas marcadas `[sensível]`: checklist mecânico + análise de consequências (compatibilidade, dados, segurança, concorrência, irreversibilidade).
- **`spec-resolver`** (`model: sonnet`) — acionado quando o executor escala OU quando um revisor reprova com `Causa provável: spec`. Resolve, atualiza a spec, devolve a etapa. Ao fechar, colhe lição (ver Camada de lições).
- **`spec-verifier`** (`model: sonnet`) — verificação independente pós-spec (obrigatória em T3, recomendada em T2 com etapas `[sensível]`): subagente fresco e read-only, nunca o autor, checa cada REQ-ID com evidência e injeta falhas em cópia descartável para provar que os testes discriminam. Fix loop máx. 3 iterações.

O ciclo automático é:

```
planejar (sonnet: lê constituição + SPEC-LESSONS.md, REQ-IDs, gate de fechamento)
  → por etapa: executar (haiku)
      → escalou? → resolver (sonnet) → volta ao haiku (+ lição)
      → validou? → revisão conforme risco:
            auto-aprovada (T1/leitura/doc)     → próxima etapa
            comum de código (T2/T3)            → spec-reviewer (haiku)
            [sensível]                         → spec-reviewer-senior (sonnet)
                → REPROVADO minor/major → correção (haiku, máx. 2 ciclos)
                → REPROVADO critical, ou 3ª reprovação → humano
                → Causa provável: spec → resolver (sonnet)
  → após a última etapa (T3; T2 sensível): spec-verifier (sonnet)
      → LACUNAS → tarefas FIX-V ao ciclo normal (máx. 3 iterações) → re-verifica
      → APROVADO → colher lições finais, fechar RUN.md, fim
```

### Classificação de risco para revisão (decide quem revisa)

- **Auto-aprovada (sem revisor):** toda etapa T1; etapas T2/T3 que só leem, documentam ou registram baseline. O critério `VALIDA COM` passando é o gate. Registre `auto-aprovada (low-risk)` no fluxo.
- **Revisão mecânica (`spec-reviewer`, Haiku):** etapas T2/T3 que alteram código ou testes, não marcadas `[sensível]`.
- **Revisão sênior (`spec-reviewer-senior`, Sonnet):** etapas marcadas `[sensível]` na spec. Marque `[sensível]` quando a etapa tocar: schema/contrato público, migração ou remoção de dados, segurança/auth, concorrência, ou qualquer coisa difícil de reverter depois de integrada.

Se você se pegar marcando a maioria das etapas como `[sensível]`, ou a tarefa é realmente crítica (ok, pague a revisão Sonnet) ou você está usando `[sensível]` como muleta para spec rasa — nesse caso, aprofunde a spec.

**Regra dura:** o orquestrador NUNCA envia uma etapa direto ao Sonnet para execução "por precaução". Se a etapa parece exigir julgamento, isso é sinal de que a spec está incompleta — volte ao planejamento e elimine o julgamento, depois mande ao Haiku. A única exceção: uma etapa que já escalou 2 vezes vai direto ao Sonnet para execução completa (limite de ping-pong). O mesmo limite vale para reprovações: na 3ª reprovação da mesma etapa, pare e envolva o usuário — ciclo de correção infinito queima mais token que fazer no modelo grande.

### Protocolo de escalação (o que faz o Haiku parar)

O executor escala se, e somente se, ocorrer um destes gatilhos mecânicos:

1. **Validação falhou 2x** — o critério de aceitação da etapa não passa após 2 tentativas de correção.
2. **Realidade ≠ spec** — arquivo, função, schema ou dependência citada na spec não existe ou tem assinatura diferente.
3. **Decisão residual** — a etapa exige uma escolha que a spec não resolveu (qualquer "depende").
4. **Condição de escalação da etapa** — o gatilho explícito escrito na própria spec disparou.

O relatório de escalação é estruturado (formato em `agents/spec-executor.md`) para que o Sonnet resolva sem reler tudo.

## Passo 1 — Classificar o tier

Avalie a tarefa nestes 5 eixos e some os pontos:

| Eixo | 0 pontos | 1 ponto | 2 pontos |
|---|---|---|---|
| **Arquivos tocados** | 1 | 2–4 | 5+ ou arquitetura nova |
| **Decisões em aberto** | nenhuma (caminho óbvio) | 1–2 escolhas locais | escolhas de design/API/schema |
| **Risco de quebra** | isolado, sem consumidores | afeta módulo existente | afeta contratos, dados, ou público |
| **Novidade** | padrão já existente no repo | variação de padrão existente | território novo (lib nova, domínio novo) |
| **Verificabilidade** | trivial de testar manualmente | testável com testes existentes | exige novos testes/critérios |

**Mapeamento:** 0–1 → **T0** | 2–4 → **T1** | 5–7 → **T2** | 8–10 → **T3**

Em dúvida entre dois tiers, escolha o **menor** — subir de tier no meio (escalação) é mais barato que spec desnecessária.

Declare o tier em uma linha: `[spec-kit: T2 — 6pts: arquivos=1, decisões=2, risco=1, novidade=1, verif=1]`

## Passo 2 — Clarificar (T2/T3 apenas, e só se houver ambiguidade)

Antes de escrever spec T2/T3, liste mentalmente as ambiguidades do pedido. Se houver alguma cuja resposta errada invalidaria a spec, faça **no máximo 3 perguntas objetivas** ao usuário de uma vez só (nunca em série). Se não houver, siga direto. T0/T1 nunca param para clarificar — assumem a interpretação óbvia e a declaram em 1 linha.

## Passo 3 — Executar o protocolo do tier

### T0 — Trivial (typo, one-liner, ajuste de config)
**Sem spec, sem subagente, sem cerimônia.** Execute direto e mostre o diff.

### T1 — Pequena (função nova, bugfix localizado, refactor de 1 arquivo)
**Micro-spec inline** (3–6 linhas): objetivo, arquivos, critério de pronto. Depois delegue ao `spec-executor` (Haiku) em uma única chamada. Bugfix usa a variante bugfix (comportamento atual / esperado / intocável) de `references/spec-templates.md`.

### T2 — Média (feature multi-arquivo, refactor com consumidores, integração)
**Spec compacta** (template em `references/spec-templates.md`): objetivo, não-objetivos, arquivos e mudanças, **todas as decisões tomadas**, critérios de aceitação em formato EARS, condições de escalação por etapa. Execute etapa a etapa via `spec-executor`.

### T3 — Grande (subsistema novo, mudança arquitetural, pipeline)
**Spec profunda** (template em `references/spec-templates.md`): tudo do T2, mais contratos/schemas por extenso, exemplos de entrada/saída, plano de testes escrito ANTES da implementação (os testes são o critério executável que dispensa julgamento do Haiku), grafo de dependências entre etapas (etapas independentes podem rodar em executores paralelos), e **passo de análise de consistência** antes de liberar (ver abaixo).

**Análise de consistência (obrigatória no T3):** antes da primeira etapa, releia a spec inteira procurando: critérios que não cobrem algum requisito, etapas que dependem de artefatos que nenhuma etapa anterior cria, contradições entre contratos e exemplos, e frases que delegam julgamento. Corrija antes de executar — cada furo encontrado aqui custa centavos; encontrado pelo Haiku, custa uma escalação.

## Rastreabilidade e gate de fechamento (T2/T3)

- Todo requisito ganha ID (`REQ-NNN`) em formato EARS. O ID flui: spec → etapa → teste → commit (mensagem de commit cita os REQs da etapa). O verifier checa cada REQ com evidência arquivo:linha — evidência ou zero.
- **Gate de fechamento de requisitos**: nada sai da fase de spec silenciosamente ambíguo. Toda pergunta aberta é resolvida com o usuário OU registrada como premissa assinada (`PREM-NN`) na seção "Premissas assumidas". Zonas cinzentas deliberadamente recusadas são registradas, não omitidas.

## Camada de lições (o harness aprende)

Falhas custam tokens uma vez; lições impedem que custem duas. Escalações resolvidas, DVGs e lacunas do verifier são colhidas conforme `references/lessons.md`:

- **Triagem por granularidade**: one-off → descarta; fato de 1-2 linhas → `SPEC-LESSONS.md`; convenção com 2+ ocorrências → promove a `SPEC-CONSTITUTION.md`; procedimento multi-step → skill própria em `.claude/skills/learned/`.
- **Regra de promoção**: lição só vira conhecimento autoritativo com verificação real que passou + padrão de falha nomeado + beco sem saída descartado. Faltou algum → nota `[não verificada]` ou descarte. Nunca registre valores de segredos.
- O planejador lê `SPEC-LESSONS.md` (com a constituição) antes de toda spec T2/T3 e incorpora lições pertinentes como critérios/decisões.

## Registro de execução (RUN.md)

Toda spec T2/T3 mantém `specs/<n>/RUN.md` append-only: uma linha por evento (etapa concluída, escalação, reprovação+DVG, veredito do verifier), com contadores do loop contract. Serve para: retomar sessão interrompida, auditar o ciclo, e — após ~10 specs — calibrar os thresholds de tier com dados reais (specs T1 que escalaram muito → critérios de classificação frouxos; T3 sem nenhuma escalação → talvez spec-teatro).

## Constituição do projeto (opcional, recomendado)

Se existir um arquivo `SPEC-CONSTITUTION.md` na raiz do repo, trate-o como princípios inegociáveis que toda spec herda automaticamente (ex.: "todo endpoint tem teste de contrato", "nunca usar ORM X", "logs sempre em JSON"). Isso evita repetir as mesmas decisões em toda spec e reduz escalações por conflito de convenção. Se não existir e você notar decisões se repetindo entre tarefas, sugira criá-lo.

## Escalação de tier no meio do caminho

Se durante a execução aparecer algo que a classificação não previu, **pare e reclassifique**:
1. Declare: `[spec-kit: escalando T1→T2 — motivo: <1 frase>]`
2. Gere a spec do tier novo apenas para a parte restante
3. Continue no ciclo normal (Haiku executa)

## Anti-padrões

- **Spec-teatro**: spec T3 para tarefa T1. O custo do planejamento tem que ser menor que o retrabalho que evita.
- **Spec-código**: se a spec é praticamente o código, escreva o código.
- **Decisão delegada**: "escolha a melhor abordagem" numa spec é bug da spec.
- **Sonnet preventivo**: mandar etapa ao Sonnet "porque parece difícil". Difícil para o Haiku = spec rasa. Aprofunde a spec.
- **Contexto gordo**: passar histórico da conversa ao executor. Ele recebe etapa + arquivos + critério, nada mais.
- **Critério vago**: "deve funcionar corretamente" não é critério. Critério é comando + resultado esperado.

## Instalação (uma vez por projeto)

Use o instalador incluído — ele copia a skill, instala os 5 subagentes em `.claude/agents/` (obrigatório: o Claude Code só carrega subagentes dessa pasta) e cria `specs/` + `SPEC-LESSONS.md` no projeto:

```powershell
# Windows (PowerShell) — dentro da pasta do projeto:
.\spec-kit\scripts\install.ps1            # ou -Target C:\repo, -Global, -Force
```
```bash
# Linux / macOS / WSL / Git Bash:
bash spec-kit/scripts/install.sh          # ou ./install.sh /caminho/repo, -g, FORCE=1
```

Verifique com `/agents` no Claude Code: devem aparecer spec-executor, spec-reviewer, spec-reviewer-senior, spec-resolver e spec-verifier.

Fora do Claude Code (sem subagentes), simule o roteamento: escreva a spec com todo o rigor, execute as etapas mecanicamente como se fosse o executor, revise o diff contra o checklist do revisor, e trate escalações explicitamente no fluxo.

## Referências

- `references/spec-templates.md` — templates T1/T2/T3 (com loop contract, REQ-IDs, premissas) + variante bugfix + checklist. Leia ao gerar qualquer spec T2/T3.
- `references/lessons.md` — triagem, regra de promoção e destinos das lições. Leia ao colher qualquer lição.
- `agents/spec-executor.md` — executor (Haiku) e formato do relatório de escalação.
- `agents/spec-reviewer.md` — revisor mecânico (Haiku): escopo via git diff, evidência de validação, DVGs com severidade.
- `agents/spec-reviewer-senior.md` — revisor sênior (Sonnet) para etapas `[sensível]`: consequências, compatibilidade, reversibilidade.
- `agents/spec-resolver.md` — resolvedor (Sonnet) de escalações e defeitos de spec; colhe lições ao fechar.
- `agents/spec-verifier.md` — verificador independente (Sonnet): rastreabilidade REQ, injeção de falhas, fix loop limitado.
