# Deploy no Raspberry Pi com systemd

Este diretório contém templates de script/unit para executar os serviços do AutoHunter via `systemd`.

## API FastAPI (`autohunter-api.service`)

Arquivos de deploy da API:

- Script: `deploy/raspberry/scripts/run_api.sh`
- Unit: `deploy/raspberry/systemd/autohunter-api.service`

### Instalação no Pi

Assumindo o repositório em `/opt/autohunter`:

```bash
sudo install -m 755 /opt/autohunter/deploy/raspberry/scripts/run_api.sh /opt/autohunter/deploy/raspberry/scripts/run_api.sh
sudo install -m 644 /opt/autohunter/deploy/raspberry/systemd/autohunter-api.service /etc/systemd/system/autohunter-api.service
```

### Habilitar e iniciar

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now autohunter-api
```

### Validação

```bash
curl http://127.0.0.1:8000/docs
curl http://<IP_DO_PI>:8000/docs
```

### Logs

```bash
sudo journalctl -u autohunter-api -f
```

## Scheduler (`autohunter-scheduler.service`)

Roda como usuário `autohunter`, via `deploy/raspberry/scripts/run_scheduler.sh` (`python -m app.cli.run_scheduler`).

### Job mensal FIPE

O job `monthly_fipe_update` (crawler + sync FIPE) tem um kill switch que **vem desligado por padrão**:

```bash
FIPE_MONTHLY_UPDATE_ENABLED=false   # default em app/core/settings.py
```

Para ativar a atualização mensal automática da tabela FIPE em produção, defina `FIPE_MONTHLY_UPDATE_ENABLED=true` em `/opt/autohunter/.env` (ver `.env.example` para as demais variáveis `FIPE_MONTHLY_UPDATE_*` / `FIPE_API_*`) e reinicie o serviço:

```bash
sudo systemctl restart autohunter-scheduler
```

O agendamento do job é persistido no Postgres/Supabase (`SQLAlchemyJobStore` sobre o mesmo `DATABASE_URL` da aplicação), então sobrevive a restarts do systemd — não é necessário reagendar manualmente após um deploy ou reboot do Pi.
