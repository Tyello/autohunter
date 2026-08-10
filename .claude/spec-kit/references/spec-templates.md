# Templates de Spec por Tier

Nota geral: não existe marcação `[sonnet]` de execução por etapa. Toda etapa é executada pelo Haiku; o Sonnet entra via escalação e via revisão sênior. A única marcação de etapa é **`[sensível]`**, que muda quem REVISA (spec-reviewer-senior/Sonnet em vez de spec-reviewer/Haiku). Marque `[sensível]` quando a etapa tocar: schema/contrato público, migração ou remoção de dados, segurança/auth, concorrência, ou algo difícil de reverter. Se ao escrever uma etapa você pensar "isso precisa do Sonnet para executar", a etapa está subespecificada — decida agora o que falta decidir e reescreva.

## Formato EARS para critérios de aceitação

Sempre que o critério envolver comportamento (não apenas "teste X passa"), use a notação EARS, que elimina ambiguidade:

```
QUANDO [condição/evento] O SISTEMA DEVE [comportamento verificável]
```

Exemplos:
- QUANDO o usuário envia formulário com CPF inválido O SISTEMA DEVE retornar 422 com campo `errors.cpf`
- QUANDO o pacote tem CRC inválido O SISTEMA DEVE levantar `ChecksumError` (nunca retornar None)

Cada critério EARS deve ser acompanhado do comando que o verifica.

---

## Spec T1 — Micro-spec (inline, sem arquivo)

```
Objetivo: <1 frase>
Toca: <arquivo(s)>
Critério de pronto: <comando/teste + resultado esperado>
```

**Exemplo:**
```
Objetivo: corrigir off-by-one na paginação de resultados
Toca: src/api/search.py
Critério de pronto: pytest tests/test_search.py::test_pagination passa; página 2 começa no item 21
```

### Variante T1-bugfix

Para correção de bug, substitua "Objetivo" pela tripla que impede regressão:

```
Comportamento atual: <o que acontece hoje, com reprodução>
Comportamento esperado: <o que deve acontecer>
Comportamento intocável: <o que NÃO pode mudar como efeito colateral>
Toca: <arquivos>
Critério de pronto: <teste que reproduz o bug passa a verde + suíte existente segue verde>
```

O "comportamento intocável" é o campo mais importante para o executor Haiku: define o perímetro do que ele não pode "consertar de brinde".

---

## Spec T2 — Spec compacta

Salve como `SPEC.md` na raiz da tarefa (ou apresente no chat se o fluxo for conversacional).

```markdown
# Spec: <título>  [spec-kit: T2]

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 12 iterações totais
- Parada: todos os REQs verdes | orçamento estourado → humano
- Registro: specs/<n>/RUN.md (append-only)

## Objetivo
<2-3 frases: o que muda e por quê>

## Requisitos
- REQ-001: QUANDO ... O SISTEMA DEVE ... — verificado por: <comando>
- REQ-002: ...
<Todo requisito tem ID. Toda etapa, teste e commit referencia os REQ-IDs que atende.>

## Não-objetivos
- <o que explicitamente NÃO fazer>

## Premissas assumidas (gate de fechamento)
<Nada sai desta spec silenciosamente ambíguo. Toda pergunta aberta foi resolvida
com o usuário OU está registrada aqui como premissa assinada:>
- PREM-01: <interpretação adotada + por quê é razoável>
<Zonas cinzentas deliberadamente não tratadas são registradas, não omitidas.>

## Decisões tomadas
- <cada escolha em aberto, já resolvida, com justificativa de 1 linha>

## Etapas
### Etapa 1: <nome>  (REQ-001, REQ-003)
- FAZ: <instrução mecânica completa>
- TOCA: <arquivos>
- VALIDA COM: <comando + resultado esperado>
- ESCALA SE: <condição mecânica>

### Etapa 2: ...

## Critérios de aceitação globais
1. Todos os REQ-IDs cobertos por teste com evidência (arquivo:linha)
2. Suíte completa verde: <comando> (<N> testes declarados)
```

---

## Spec T3 — Spec profunda

Regra central: **o executor nunca decide, só implementa e valida.** Todo julgamento foi exercido aqui.

```markdown
# Spec: <título>  [spec-kit: T3]

## Loop contract
- Verificador por etapa: VALIDA COM + revisor conforme risco
- Verificação final: spec-verifier independente (obrigatório em T3), fix loop máx. 3 iterações
- Orçamento: máx. 2 escalações/etapa, 3 reprovações/etapa, 20 iterações totais
- Parada: veredito APROVADO do verifier | orçamento estourado → humano
- Registro: specs/<n>/RUN.md (append-only)

## Objetivo
<parágrafo: problema, solução escolhida, resultado esperado>

## Requisitos
- REQ-001: QUANDO ... O SISTEMA DEVE ... — verificado por: <comando>
<IDs obrigatórios. Fluxo de rastreabilidade: REQ → etapa → teste → commit.
O spec-verifier checa cada REQ com evidência arquivo:linha.>

## Não-objetivos
- <lista explícita>

## Premissas assumidas (gate de fechamento)
- PREM-01: <interpretação adotada + justificativa>
<Toda ambiguidade foi resolvida com o usuário ou está assinada aqui. Zonas
cinzentas recusadas são registradas, não omitidas.>

## Decisões tomadas
- <todas, com justificativa de 1 linha>

## Contratos e schemas
<POR EXTENSO. Assinaturas completas, JSON schemas, tipos.>

```python
def decode_packet(raw: bytes) -> DecodedPacket:
    """Levanta ChecksumError se CRC inválido. Nunca retorna None."""
```

## Plano de testes
<Escreva os testes AQUI, por extenso, ANTES das etapas de implementação.
São o critério executável que dispensa julgamento do executor.
Cada teste referencia o REQ-ID que asserta. Declare a contagem total de testes
(o verifier compara para detectar deleção silenciosa).
Litmus não-raso: asserção que passaria com implementação errada é rejeitada —
asserte valor real/estado persistido, nunca apenas que um mock foi chamado.>

## Antes de escrever o plano de testes
<Amostre 5-10 testes existentes do repo para extrair estilo, framework, localização
e profundidade por camada (trate a profundidade encontrada como piso, não teto).
Extraia os comandos reais de teste dos manifests/CI — não adivinhe o ecossistema.
Se o projeto não tem testes, pergunte ao usuário quais tipos e comandos usar.>

## Grafo de dependências
<Quais etapas dependem de quais. Etapas sem dependência mútua formam "ondas"
que podem ser despachadas a executores paralelos.>

Onda 1: etapas 1, 2 (independentes)
Onda 2: etapa 3 (depende de 1) | etapa 4 (depende de 2)
Onda 3: etapa 5 (depende de 3 e 4)

## Etapas
### Etapa 1: <nome>   ← acrescente [sensível] se aplicável
- FAZ: <instrução mecânica completa>
- TOCA: <arquivos>
- EXEMPLO E/S: <par concreto de entrada/saída, se não-trivial>
- VALIDA COM: <comando + resultado>
- ESCALA SE: <condições>

...

## Riscos conhecidos e mitigação
| Risco | Etapa | Mitigação já embutida na spec |
|---|---|---|

## Análise de consistência (preencher antes de liberar)
- [ ] Todo requisito do objetivo é coberto por ao menos um critério de aceitação
- [ ] Toda etapa consome apenas artefatos criados por etapas anteriores (ou pré-existentes verificados)
- [ ] Nenhuma contradição entre contratos, exemplos e testes
- [ ] Nenhuma frase delega julgamento ("escolha", "se apropriado", "da melhor forma")
```

---

## Checklist de qualidade da spec (antes de liberar ao executor)

1. Alguma frase pede julgamento? → decida agora e reescreva.
2. Todo critério é comando + resultado esperado (EARS quando comportamental)? → se não, torne executável.
3. Cada etapa cabe isolada no contexto do Haiku (com os arquivos que toca)? → se não, divida.
4. As condições de ESCALA SE são detectáveis mecanicamente (erro, teste falhando, arquivo inexistente)? → condições vagas não param executor nenhum.
5. Se você previu escalação certa em alguma etapa → não a escreva assim; resolva a causa na spec agora.
