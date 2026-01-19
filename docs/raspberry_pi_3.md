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

```
sudo adduser autohunter
sudo mkdir -p /opt/autohunter
sudo chown autohunter:autohunter /opt/autohunter

# copy your repo into /opt/autohunter (git clone or rsync)
cd /opt/autohunter
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Playwright (only if enable_playwright=true)
playwright install chromium
```

## 3) Config (.env)

Minimum:

```
DATABASE_URL=...
TELEGRAM_BOT_TOKEN=...
AUTOHUNTER_ADMINS=5410199985
```

Optional per-source proxy (only OLX uses proxy, the rest runs direct):

```
SOURCE_PROXY_OLX=http://user:pass@host:port
```

Optional per-source throttling:

```
RATE_LIMIT_OLX_SECONDS=20
RATE_LIMIT_WEBMOTORS_SECONDS=10
RATE_LIMIT_GOGARAGE_SECONDS=10
```

Playwright storage (cookie stickiness):

```
PLAYWRIGHT_STORAGE_DIR=.data/playwright
```

## 4) systemd services

Copy unit files:

```
sudo cp deploy/raspberry/systemd/autohunter-bot.service /etc/systemd/system/
sudo cp deploy/raspberry/systemd/autohunter-scheduler.service /etc/systemd/system/
```

Adjust WorkingDirectory/ExecStart if you did not use /opt/autohunter.

Enable and start:

```
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
