# Facebook Marketplace onboarding (Pi)

## Dependências
- Instalar Playwright + Chromium (`pip install -r requirements.playwright.txt` e `playwright install chromium`).
- Em Raspberry Pi sem desktop local, use `Xvfb` + `noVNC` para abrir o onboarding headed.

## Fluxo
1. Usuário roda `/fb connect` no Telegram.
2. Bot retorna pairing code + link web (`PUBLIC_BASE_URL/auth/facebook?code=...`).
3. Onboarding no browser web (nunca enviar cookies por Telegram).
4. Clique em **Iniciar login** e depois **Validar sessão**.

## Diretórios e permissões
- Profiles: `/opt/autohunter/profiles/fb/<user_id>/`
- Debug: `/opt/autohunter/debug/fb/<user_id>/`
- Ambos devem ser `0700` e owner `autohunter`.

## Diagnóstico
- Em falhas de validação, screenshots/html ficam em `/opt/autohunter/debug/fb/<user_id>/`.
- Rotação automática mantém até 20 arquivos por usuário.
