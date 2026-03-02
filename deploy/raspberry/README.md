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
