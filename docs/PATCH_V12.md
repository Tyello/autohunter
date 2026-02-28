# Patch v12 — Webmotors observability + runall dur fix + warmup consent

## Objetivos
1) `dur=Nonems` não aparecer mais no `/admin runall`.
2) Quando `blocked http=200`, mostrar `provider/title/snippet/url_final` no painel.
3) Warmup webmotors mais efetivo: tentar aceitar cookies/consent antes de salvar storage_state.

---

## Arquivos adicionados
- `app/bot/runall_format.py`
- `app/services/webmotors_consent.py`

Esses arquivos **não quebram nada** por si só. Você pluga em 3 pontos abaixo.

---

## (A) Fix do dur no /admin runall
No `app/bot/handlers_admin.py` (ou onde você monta a linha do runall por source),
substitua o trecho que imprime `dur=...` para usar:

```python
from app.bot.runall_format import format_dur_ms

dur_s = format_dur_ms(
    getattr(result, "dur_ms", None),
    (payload or {}).get("dur_ms"),
    getattr(run, "dur_ms", None),
)
```

E então use `dur={dur_s}`.

---

## (B) Fingerprint no blocked (provider/title/snippet/url)
No seu `app/services/browser_fetcher.py` (ou função equivalente que retorna HTML),
no branch que detecta challenge (HTTP 200 mas HTML não é página real):

1) Importe:
```python
from app.services.challenge_fingerprint import fingerprint_from_html
```

2) Após obter `html` e `final_url`, faça:
```python
fp = fingerprint_from_html(html, final_url=final_url)
diag = {}
if fp:
    diag.update({
        "blocked_provider": fp.provider,
        "blocked_title": fp.title,
        "blocked_final_url": fp.final_url,
        "blocked_snippet": fp.snippet,
    })
```

3) Ao criar o erro/blocked, injete `diag` no payload/err_full persistido e limite snippet no display.

---

## (C) Warmup webmotors: aceitar consent
No serviço/handler do warmup (você já tem `/admin warmup webmotors` funcionando),
antes de salvar o `storage_state`:

1) Importe:
```python
from app.services.webmotors_consent import try_click_consent
```

2) Após `goto(home)`, faça:
```python
await try_click_consent(page)
```

3) Opcional: navegue para `/carros` após o clique e antes de salvar state.

---

## Como validar
1) `/admin warmup webmotors`
2) `/admin runall webmotors`

Se bloquear, o painel deve passar a mostrar algo como:
`blocked http=200 ... provider=perimeterx title="..."`

E `dur` no runall deve ser numérico (ex.: `dur=18937ms`), nunca `Nonems`.
