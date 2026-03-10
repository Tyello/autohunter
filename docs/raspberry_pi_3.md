# Deploy no Raspberry Pi 3 (Linux)

Este projeto pode rodar com custo mínimo separando responsabilidades em 2 processos:

- Telegram Bot: recebe comandos e grava no DB
- Scheduler: faz o scraping periódico e envia notificações

No Raspberry Pi 3 este é o layout recomendado (menos spikes de memória, reinícios mais simples).

## 1) Pré-requisitos

- Raspberry Pi OS Lite (64-bit recomendado)
- Python 3.11+ (3.12 ok). Evite 3.13 “bleeding-edge” no ARM sem necessidade.
- PostgreSQL (Supabase recomendado) acessível a partir do Pi

## 2) Instalação

Se quiser automatizar o setup (pacotes + venv + deps), use o bootstrap:

```bash
# (assumindo o repo já em /opt/autohunter)
sudo bash deploy/raspberry/scripts/bootstrap_rpi.sh /opt/autohunter
```

Ou faça manualmente:

```bash
sudo adduser autohunter
sudo mkdir -p /opt/autohunter
sudo chown autohunter:autohunter /opt/autohunter

# copie o repo para /opt/autohunter (git clone ou rsync)
cd /opt/autohunter

python -m venv .venv
source .venv/bin/activate

# deps base (sem Playwright)
pip install -r requirements.txt

# opcional: TLS fingerprint melhor para algumas fontes
# se falhar no ARM, remova
pip install -r requirements.optional.txt

# Playwright (pesado) — só se você realmente precisa de browser fallback
# pip install -r requirements.playwright.txt
# python -m playwright install chromium
```

## 3) Configuração (.env)

Crie seu `.env` a partir do template:

```bash
cp .env.example .env
```

Mínimo:

```env
DATABASE_URL=...
TELEGRAM_BOT_TOKEN=...
AUTOHUNTER_ADMINS=5410199985
```

Settings recomendados para Pi:

```env
SCHEDULER_WORKERS=2
SCHED_ML_MINUTES=10
SCHED_OLX_MINUTES=60
SCHED_CHAVESNAMAO_MINUTES=60
SCHED_SENDER_SECONDS=60

ENABLE_PLAYWRIGHT=false
```

Proxy por fonte (apenas OLX usa proxy, as demais rodam direto):

```env
SOURCE_PROXY_OLX=http://user:pass@host:port
```

Throttling por fonte:

```env
RATE_LIMIT_OLX_SECONDS=25
RATE_LIMIT_WEBMOTORS_SECONDS=10
RATE_LIMIT_GOGARAGE_SECONDS=10
```

## 4) systemd services

Torne os scripts executáveis:

```bash
chmod +x deploy/raspberry/scripts/*.sh
```

Copie os unit files:

```bash
sudo cp deploy/raspberry/systemd/autohunter-bot.service /etc/systemd/system/
sudo cp deploy/raspberry/systemd/autohunter-scheduler.service /etc/systemd/system/
```

Ajuste `WorkingDirectory`/`ExecStart` se você não usou `/opt/autohunter`.

Habilite e inicie:

```bash
sudo systemctl daemon-reload
sudo systemctl enable autohunter-bot autohunter-scheduler
sudo systemctl start autohunter-bot autohunter-scheduler

# logs
sudo journalctl -u autohunter-bot -f
sudo journalctl -u autohunter-scheduler -f
```

## 5) Health check

No Telegram (admin only):

- `/admin health` : snapshot de sistema + pools
- `/admin sources` : backoff por fonte + agregados 24h

## 6) Start / Stop / Restart

Start:

```bash
sudo systemctl start autohunter-bot autohunter-scheduler
```

Stop:

```bash
sudo systemctl stop autohunter-bot autohunter-scheduler
```

Restart:

```bash
sudo systemctl restart autohunter-bot autohunter-scheduler
```

Disable on boot:

```bash
sudo systemctl disable autohunter-bot autohunter-scheduler
```

## 7) (Opcional, recomendado) Browser Service (Playwright) separado

Quando OLX exige Cloudflare/anti-bot, Playwright vira o recurso mais caro. No Raspberry Pi 3, o ideal é **isolar** o browser em um serviço separado:

- se o Chromium travar, você reinicia só o serviço do browser
- dá pra limitar CPU/RAM do Playwright sem derrubar bot/scheduler
- prepara o caminho pra mover isso pra outro host no futuro (sem refatorar)

### Instalar dependências do Playwright (uma vez)

```bash
source /opt/autohunter/.venv/bin/activate
pip install -r requirements.playwright.txt
python -m playwright install chromium
```

### Configurar `.env`

No `/opt/autohunter/.env`:

```env
ENABLE_PLAYWRIGHT=true
PLAYWRIGHT_ENDPOINT=http://127.0.0.1:8787
# opcional: trava o serviço com um token simples
# PLAYWRIGHT_SERVICE_TOKEN=algum_segredo
```

### Habilitar no systemd

```bash
sudo cp deploy/raspberry/systemd/autohunter-browser.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autohunter-browser.service
sudo systemctl status autohunter-browser.service
```

Se precisar ajustar limites no Pi, edite o unit e mexa em `MemoryMax` e `CPUQuota`.

## 8) Admin Deploy via Telegram (wrapper privilegiado)

Para `/admin deploy` + `/admin deploy confirm <operation_id>` funcionar em produção, o bot **não** pode depender de shell livre: ele só pode executar um wrapper único e fixo.

Checklist operacional:

- O usuário do bot precisa conseguir executar **apenas** o wrapper permitido.
- Em host com systemd, o `autohunter-bot.service` não deve bloquear escalonamento (`NoNewPrivileges=true`) nem bloquear acesso ao HOME do usuário da aplicação (`ProtectHome=true`).
- O `sudoers` deve permitir `NOPASSWD` somente para `/usr/local/bin/autohunter-admin-deploy`.
- O wrapper deve ser root-owned, fora do repo, e sem aceitar comandos arbitrários do Telegram.

### Exemplo: override do systemd

```bash
sudo systemctl edit autohunter-bot.service
```

Conteúdo:

```ini
[Service]
NoNewPrivileges=false
ProtectHome=false
```

Aplicar:

```bash
sudo systemctl daemon-reload
sudo systemctl restart autohunter-bot.service
```

### Exemplo: sudoers restrito

```bash
sudo visudo -f /etc/sudoers.d/autohunter-admin-deploy
```

Conteúdo:

```sudoers
autohunter ALL=(root) NOPASSWD: /usr/local/bin/autohunter-admin-deploy
```

Referência de implementação do wrapper: `deploy/raspberry/scripts/autohunter-admin-deploy.example.sh` (copie para `/usr/local/bin/autohunter-admin-deploy` e mantenha fora do repo em produção).

Valide permissões do wrapper:

```bash
sudo chown root:root /usr/local/bin/autohunter-admin-deploy
sudo chmod 750 /usr/local/bin/autohunter-admin-deploy
```

Com isso, o preflight de `/admin deploy` passa a informar claramente se o caminho privilegiado está pronto (`privilege_ready=yes`) ou bloqueado (`privilege_ready=no`, com `privilege_error_type`).

Guia operacional curto: `docs/admin_deploy_telegram_ops.md`.

Se o erro incluir `Permission denied` para:

- `/home/autohunter/.ssh/known_hosts` → `protect_home_blocked`
- `/home/autohunter/.config/git/ignore` → `home_not_accessible_from_service`

trata-se de sintoma típico de sandbox de systemd no serviço do bot. Revise o override de `autohunter-bot.service` e confirme que o processo consegue ler `/home/autohunter`.
