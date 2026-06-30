# SPIKE — Webmotors via API do app mobile (time-boxed, 1 dia)

> **Tipo:** spike de investigação — decisão go/no-go, NÃO implementação de produção
> **Time-box:** 1 dia. Ao fim do dia, decisão registrada. Sem decisão = no-go por padrão.
> **Dono:** Marcelo
> **Contexto:** Webmotors está protegido por PerimeterX/HUMAN. Já falharam, no eixo "fingir um browser melhor": curl_cffi (impersonação TLS/JA3), Patchright, e sequências de warmup comportamental. O sensor de browser do PerimeterX derrota TLS isolado.

## Hipótese

O app **nativo** do Webmotors não carrega o sensor de browser do PerimeterX (que é
uma tecnologia web). Apps nativos costumam falar com endpoints JSON e autenticar de
forma diferente (API key, request assinado, token de device) — o desafio de browser
simplesmente não existe nesse canal. Se a autenticação do app for estática ou
reproduzível, abre-se um caminho HTTP limpo e barato para uma fonte que hoje só o
Playwright resolve (e mal).

## Pergunta a responder (única)

**É viável e sustentável replicar as chamadas de busca do app mobile do Webmotors
a partir do nosso scraper, sem browser?**

Decompõe em três perguntas de fato, em ordem:
1. O app fala com endpoints JSON de busca identificáveis?
2. Como esses endpoints autenticam? (key estática? token de sessão? assinatura por
   request? attestation de device?)
3. Essa autenticação é reproduzível fora do app com esforço razoável e estável o
   bastante para produção?

## Setup

- mitmproxy (ou mitmweb) como proxy HTTPS na máquina de dev.
- Um celular (ou emulador Android) com o app Webmotors instalado, configurado para
  usar o proxy e confiar no certificado do mitmproxy.
- **Atenção a cert pinning:** apps financeiros/comerciais frequentemente fazem
  pinning. Se o tráfego não aparece no mitmproxy, é provável pinning → ver "Riscos".

## Roteiro do dia (time-boxed)

**Bloco 1 — Captura (≈2h)**
- [ ] Subir mitmproxy, apontar o device, confiar no cert.
- [ ] Abrir o app e executar buscas reais (ex.: "Civic Si", com filtros de
      preço/ano/cidade). Capturar o tráfego.
- [ ] Confirmar que as chamadas de busca aparecem em claro. Se não aparecerem →
      provável cert pinning → ir direto para a avaliação de risco (não queimar o dia
      tentando furar pinning num spike de 1 dia).

**Bloco 2 — Mapeamento da API (≈2h)**
- [ ] Identificar o(s) endpoint(s) de busca: URL, método, headers, corpo.
- [ ] Mapear os parâmetros de busca (modelo, faixa de preço, ano, localização,
      paginação) para o formato que nossas wishlists já produzem.
- [ ] Catalogar os headers de auth: API key? Bearer token? header de assinatura?
      headers de device/app version?

**Bloco 3 — Teste de reprodutibilidade (≈2h)**
- [ ] Tentar replicar **uma** chamada de busca fora do app (curl/httpx) com os
      headers capturados.
- [ ] Variar: a auth é estática (mesma key sempre funciona) ou expira/rotaciona?
- [ ] Se houver assinatura por request, avaliar se o algoritmo é inferível
      (timestamp + segredo? hash de quê?) ou opaco.

**Bloco 4 — Decisão (≈1h)**
- [ ] Preencher a matriz de decisão abaixo e registrar go/no-go.

## Matriz de decisão (go/no-go)

| Achado | Veredito |
|--------|----------|
| Endpoints JSON em claro + auth estática (key fixa ou token de longa duração) | **GO forte** — caminho HTTP limpo |
| Endpoints em claro + token que expira mas renovável de forma simples | **GO condicional** — viável com refresh; estimar esforço |
| Assinatura por request reproduzível (algoritmo inferível) | **GO condicional** — depende da fragilidade |
| Assinatura opaca / attestation de device (Play Integrity etc.) | **NO-GO** — não sustentável |
| Cert pinning impede captura | **NO-GO neste time-box** — registrar e parar |

## Critérios de sucesso do spike

O spike é **bem-sucedido** se ao fim do dia existir:
- [ ] Um documento de 1 página: endpoint(s), esquema de auth, e o veredito da matriz.
- [ ] Se GO: um exemplo de chamada reproduzida com sucesso fora do app (prova de conceito), com nota sobre estabilidade da auth.
- [ ] Se NO-GO: o motivo concreto (pinning / attestation / assinatura opaca), para não retentar o mesmo caminho à toa.

Sucesso do spike NÃO é "ter um scraper pronto" — é **ter a resposta go/no-go com evidência**.

## Riscos e limites (assumir antes de começar)

- **Cert pinning** pode bloquear a captura logo no Bloco 1. Furar pinning
  (Frida/patch do APK) está **fora do escopo** de um spike de 1 dia — se aparecer,
  é NO-GO neste ciclo e vira uma decisão separada sobre se vale o esforço.
- **Termos de uso:** acessar a API do app pode violar o ToS do Webmotors. Isso é
  uma decisão de risco do produto, não técnica — registrar explicitamente antes de
  levar qualquer coisa a produção. O spike é investigação; produção é outra decisão.
- **Fragilidade:** mesmo um GO pode quebrar quando o app atualiza o esquema de auth.
  Qualquer implementação futura precisa de detecção de quebra + fallback (o Playwright
  atual permanece como rede de segurança).
- Não persistir credenciais/keys capturadas em repositório. Tratar como segredo.

## Se der GO

Não implementar dentro do spike. Abrir item separado: "Webmotors HTTP source via
mobile API", que entra como mais uma fonte no caminho HTTP-first (alinhado ao
ADR-0002, e que reforça o ganho do async ao aumentar a fração de tráfego HTTP).
