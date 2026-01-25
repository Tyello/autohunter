#!/usr/bin/env bash
set -euo pipefail

# deps do sistema (necessárias pro browser rodar)
sudo python -m playwright install-deps

# baixa os browsers (executa como o usuário que roda o serviço)
python -m playwright install chromium
