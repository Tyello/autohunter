# Deploy on Raspberry Pi 3 (Linux)

This project can run with minimal cost by splitting responsibilities into 2 processes:

- Telegram Bot: receives commands and writes to DB
- Scheduler: periodically scrapes sources and sends notifications

On Raspberry Pi 3 this is the recommended layout (lower memory spikes, easier restarts).

## 1) Prereqs

- Raspberry Pi OS Lite (64-bit recommended)
- Python 3.11+ (3.12 ok). Avoid bleeding-edge 3.13 on ARM unless you already run it.
- PostgreSQL (Supabase recommended) reachable from the Pi

## 2) Install

Se você quiser automatizar o setup (pacotes + venv + deps), use o bootstrap:

```bash
# (assumindo o repo já em /opt/autohunter)
sudo bash deploy/raspberry/scripts/bootstrap_rpi.sh /opt/autohunter
```

Ou faça manualmente:


```bash
sudo adduser autohunter
sudo mkdir -p /opt/autohunter
sudo chown autohunter:autohunter /opt/autohunter

# copy your repo into /opt/autohunter (git clone or rsync)
cd /opt/autohunter

python -m venv .venv
source .venv/bin/activate

# base deps (no Playwright)
pip install -r requirements.txt

# optional: better TLS fingerprint for some sources (if it fails on your ARM build, remove it)
pip install -r requirements.optional.txt

# Playwright (HEAVY) — only if you really need browser fallback
# pip install -r requirements.playwright.txt
# python -m playwright install chromium
```

## 3) Config (.env)

Create your `.env` from the template:

```bash
cp .env.example .env
```

Minimum:

```env
DATABASE_URL=...
TELEGRAM_BOT_TOKEN=...
AUTOHUNTER_ADMINS=5410199985
```

Recommended Pi settings:

```env
SCHEDULER_WORKERS=2
SCHED_ML_MINUTES=10
SCHED_OLX_MINUTES=60
SCHED_CHAVESNAMAO_MINUTES=60
SCHED_SENDER_SECONDS=60

ENABLE_PLAYWRIGHT=false
```

Optional per-source proxy (only OLX uses proxy, the rest runs direct):

```env
SOURCE_PROXY_OLX=http://user:pass@host:port
```

Optional per-source throttling:

```env
RATE_LIMIT_OLX_SECONDS=25
RATE_LIMIT_WEBMOTORS_SECONDS=10
RATE_LIMIT_GOGARAGE_SECONDS=10
```

## 4) systemd services

Make scripts executable:

```bash
chmod +x deploy/raspberry/scripts/*.sh
```

Copy unit files:

```bash
sudo cp deploy/raspberry/systemd/autohunter-bot.service /etc/systemd/system/
sudo cp deploy/raspberry/systemd/autohunter-scheduler.service /etc/systemd/system/
```

Adjust WorkingDirectory/ExecStart if you did not use `/opt/autohunter`.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable autohunter-bot autohunter-scheduler
sudo systemctl start autohunter-bot autohunter-scheduler

# logs
sudo journalctl -u autohunter-bot -f
sudo journalctl -u autohunter-scheduler -f
```

## 5) Health check

On Telegram (admin only):

- `/admin health` : system + pools snapshot
- `/admin sources` : per-source backoff + 24h aggregates

## 6) Start / Stop / Restart

Start

```bash
sudo systemctl start autohunter-bot autohunter-scheduler
```

Stop

```bash
sudo systemctl stop autohunter-bot autohunter-scheduler
```

Restart

```bash
sudo systemctl restart autohunter-bot autohunter-scheduler
```

Boot Disable

```bash
sudo systemctl disable autohunter-bot autohunter-scheduler
```
## 3) (Opcional, recomendado) Browser Service (Playwright) separado

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

```bash
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

