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
