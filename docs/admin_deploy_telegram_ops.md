# Admin Deploy via Telegram — Guia Operacional (produção)

Este guia cobre o caminho operacional mínimo para `/admin deploy` em produção.

## 1) Wrapper privilegiado (fixo, fora do repo)

- Caminho esperado: `/usr/local/bin/autohunter-admin-deploy`
- Dono/permissões:
  - `root:root`
  - executável (`750` recomendado)
- O wrapper deve conter fluxo fixo: `git fetch/pull --ff-only` + restart dos serviços permitidos.
- **Não aceitar argumentos vindos do Telegram** (branch/service/comando dinâmico).

Referência de implementação:
- `deploy/raspberry/scripts/autohunter-admin-deploy.example.sh`

## 2) Sudoers restrito

Criar entrada dedicada e mínima:

```sudoers
autohunter ALL=(root) NOPASSWD: /usr/local/bin/autohunter-admin-deploy
```

- Não usar wildcard (`*`).
- Não liberar shell (`/bin/bash`, `sh`, etc).

## 3) Ajustes de systemd do bot

No serviço `autohunter-bot.service`:

- `NoNewPrivileges=false` (se true, bloqueia `sudo` no fluxo)
- Garantir acesso ao HOME da app (evitar bloqueio por `ProtectHome=true` quando necessário para git/ssh/config)
- Executar `daemon-reload` após mudanças.

## 4) Runtime dirs e permissões

- Repo operacional consistente com o caminho do wrapper.
- HOME da app válido (ex.: `/home/autohunter`) com:
  - `.ssh/known_hosts`
  - `.config/git/*`
- O usuário do bot deve conseguir leitura/escrita nesses caminhos de runtime.

## 5) Validação manual no host

1. Validar sudoers:

```bash
sudo -n -l -- /usr/local/bin/autohunter-admin-deploy
```

2. Validar wrapper:

```bash
sudo /usr/local/bin/autohunter-admin-deploy
```

3. Validar via Telegram:

- `/admin deploy` (preflight)
- `/admin deploy confirm <operation_id>`
- `/admin deploy status`

## 6) Troubleshooting rápido

- `working_tree_dirty`: limpar/reverter artefatos runtime antes de novo deploy.
- `remote_unreachable`: falha de conectividade com remoto Git.
- `privilege_no_new_privileges`: ajustar `NoNewPrivileges=false` no service do bot.
- `privilege_sudo_not_allowed`/`sudo_password_required`: corrigir sudoers NOPASSWD restrito ao wrapper.
- `protect_home_blocked`/`home_not_accessible_from_service`: revisar sandbox do systemd e acesso ao HOME.
- `git_fetch`/`git_pull`: checar credenciais/ssh remoto e branch esperada.
- `service_restart`/`service_health`: checar `systemctl status` dos serviços alvo.
