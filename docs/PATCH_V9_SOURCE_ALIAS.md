# Patch v9 — Source alias + validation (admin commands)

## Problema
Você digitou `/admin warmup webmotor` (sem "s") e o sistema tratou como source diferente, gerando um storage_state separado.
Esse patch adiciona canonicalização conservadora de nomes de source (aliases) para comandos admin.

## O que foi adicionado
- `app/bot/source_alias.py` com:
  - aliases (webmotor -> webmotors, wm -> webmotors)
  - função `canonicalize_source_arg(...)` que retorna (canonical, note)

## Como aplicar no seu código (sem sobrescrever handlers_admin.py)
Nos handlers dos comandos que recebem `<source>`, logo após ler o argumento:
- `warmup`
- `runall`
- `matchdebug`
- (opcional) `sources set`, `enable/disable`

adicione:

```python
from app.bot.source_alias import canonicalize_source_arg
```

e depois:

```python
source, note = canonicalize_source_arg(source, known_sources=<lista_de_sources>)
if note:
    lines.append(f"Nota: {note}")  # ou reply_text(note)
```

### Onde obter `known_sources`
Use o mesmo método que o painel `/admin sources` já usa para listar sources (DB `source_configs`, etc.).
Se não quiser validar, passe `known_sources=None` e só canonicalize.

## Recomendações
- Use canonicalização no início do handler e use apenas o nome canonical daí pra frente (inclusive para o storage_state).
- Não inclua aliases agressivos demais (prefira poucos e certeiros).
