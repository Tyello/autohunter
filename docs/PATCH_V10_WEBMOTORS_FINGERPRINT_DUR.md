# Patch v10 — Webmotors blocked fingerprint + duration fix

## Problema observado
`- webmotors: 🟠 blocked http=200 backoff=60m dur=Nonems`

- `dur=None` indica que o caminho de erro/blocked não está preenchendo a duração.
- Ainda falta diagnosticar *qual* anti-bot está ativo (Cloudflare / PerimeterX / DataDome / consent etc).
  Sem isso, a correção vira tentativa-e-erro.

## O que o patch adiciona
- `app/services/challenge_fingerprint.py`
  - Extrai `provider`, `title`, `final_url` e `snippet` (texto limpo) do HTML.
  - Não salva HTML inteiro, só fingerprint curto.

## Como plugar (2 pontos)
### (A) No browser_fetcher (quando detectar HTTP 200 challenge)
1. Após obter `html` e `final_url`, faça:

```python
from app.services.challenge_fingerprint import fingerprint_challenge

fp = fingerprint_challenge(html, final_url=final_url)
if fp:
    diag = {
        "blocked_provider": fp.provider,
        "blocked_title": fp.title,
        "blocked_final_url": fp.final_url,
        "blocked_snippet": fp.snippet,
    }
```

2. Ao criar o erro/blocked, inclua `diag` no `err_full` / payload do `SourceRun`, por exemplo:
- `err_full = f"blocked(http=200; provider={fp.provider}; title={fp.title}; url={fp.final_url}; snippet={fp.snippet[:200]})"`

3. Garanta que a duração (`dur_ms`) seja preenchida no caminho de blocked:
- capture `t0 = time.monotonic()` no início e `dur_ms=int((time.monotonic()-t0)*1000)` no retorno/exception.

### (B) No /admin sources e /admin runall (display)
- Se existir `blocked_provider`, mostre no painel:
  - `blocked_provider=perimeterx` (exemplo)
- Se existir `blocked_title`, mostre (curto).
- Se existir `blocked_snippet`, NÃO mostrar inteiro no chat (deixe 120–200 chars no máximo).

## Resultado esperado
Próximo blocked vira algo como:
`blocked http=200 backoff=60m dur=18166ms provider=perimeterx title="..."`

Aí a próxima ação fica objetiva:
- PerimeterX/DataDome: precisa navegar/clicar e fingerprint mais forte + proxy estável.
- Consent: basta clicar "aceitar cookies" no warmup.
- Cloudflare: ajustes de locale/timezone/headers e não bloquear assets pode destravar.
