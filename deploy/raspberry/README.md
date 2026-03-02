# Deploy no Raspberry Pi com systemd

Este diretório contém os scripts e unit files para subir serviços do AutoHunter via `systemd`.

## Arquivos adicionados/atualizados

- API FastAPI:
  - `deploy/raspberry/scripts/run_api.sh`
  - `deploy/raspberry/systemd/autohunter-api.service`
- Browser Service (Playwright isolado):
  - `deploy/raspberry/scripts/run_browser_service.sh`
  - `deploy/raspberry/systemd/autohunter-browser.service`

## Pré-requisitos

- Código em `/opt/autohunter`
- Usuário de execução (ex.: `autohunter`) com permissão no diretório
- Ambiente virtual criado em `/opt/autohunter/venv` ou `/opt/autohunter/.venv` (opcional, mas recomendado)
- Arquivo `.env` em `/opt/autohunter/.env` (se usado pelo projeto)

## Instalação dos serviços no Pi

Copie os arquivos para os caminhos finais:

```bash
sudo install -m 755 /opt/autohunter/deploy/raspberry/scripts/run_api.sh /opt/autohunter/deploy/raspberry/scripts/run_api.sh
sudo install -m 755 /opt/autohunter/deploy/raspberry/scripts/run_browser_service.sh /opt/autohunter/deploy/raspberry/scripts/run_browser_service.sh

sudo install -m 644 /opt/autohunter/deploy/raspberry/systemd/autohunter-api.service /etc/systemd/system/autohunter-api.service
sudo install -m 644 /opt/autohunter/deploy/raspberry/systemd/autohunter-browser.service /etc/systemd/system/autohunter-browser.service
```

## Habilitar e iniciar

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now autohunter-api
sudo systemctl enable --now autohunter-browser
```

## Logs

```bash
sudo journalctl -u autohunter-api -f
sudo journalctl -u autohunter-browser -f
```

## Testes rápidos

API local:

```bash
curl http://127.0.0.1:8000/docs
```

API pela rede (troque `<IP>` pelo IP do Raspberry Pi):

```bash
curl http://<IP>:8000/docs
```

Browser service local:

```bash
curl http://127.0.0.1:7001/health
```
