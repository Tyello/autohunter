# Garagem Alvo / AutoHunter — Limitações para beta

Atualizado em: 2026-06-10.

Este documento registra pontos que devem ser considerados antes de abrir o produto para mais usuários.

## Produto

- Garagem Alvo não é marketplace, loja ou concessionária.
- A jornada principal é o bot no Telegram.
- A API é auxiliar e operacional.
- O público inicial é entusiasta automotivo.

## Cobertura

- A cobertura pode variar por fonte, modelo, cidade e momento.
- Fontes externas podem ficar instáveis ou entregar dados incompletos.
- Não prometer cobertura total do mercado.
- WebMotors está despriorizada operacionalmente e não deve ser promessa pública do beta.

## Alertas

- Evitar reenvio indevido de alertas é prioridade crítica.
- Mudanças em ingestão, matching, sender ou retenção precisam validar dedupe e limite diário.
- Contexto de preço e raridade deve ser conservador quando a amostra for pequena.

## Pagamento

- O Premium precisa de webhook ou aprovação admin em 1 clique antes de abertura pública ampla.
- Limites de busca, tracking e alertas protegem o runtime.

## Leilões

- Leilões permanecem em piloto controlado.
- Todo alerta precisa avisar que lance não é preço final.
- O usuário deve conferir edital, taxas, documentação e regras do leiloeiro.

## Operação

- O beta inicial deve ser barato e controlado.
- Não introduzir arquitetura pesada sem evidência de necessidade.
- Comandos administrativos precisam ficar restritos ao admin autorizado.
- Mensagens ao usuário não devem expor detalhes técnicos internos.

## Comunicação recomendada

Garagem Alvo monitora fontes automotivas em expansão e avisa no Telegram quando aparecem oportunidades compatíveis com suas buscas. A cobertura pode variar por modelo, cidade e fonte.
