# Facebook Agent (bring-your-own-browser)

## Como usar
1. No Telegram, rode `/fb connect`.
2. Abra o link recebido (`/auth/facebook?code=FB-XXXX`).
3. No seu computador, instale dependências:
   - `pip install -r tools/fb_agent/requirements.txt`
   - `playwright install chromium`
4. Rode:
   - `python -m fb_agent --code FB-XXXX --server https://SEU_PUBLIC_BASE_URL`
5. Faça login no Facebook no navegador local aberto pelo agent e pressione Enter no terminal do agent.

## Status
- `PENDING_AGENT`: aguardando agent conectar.
- `AGENT_ONLINE`: agent conectado ao websocket.
- `ACTIVE`: sessão Facebook validada.
- `CHALLENGE_REQUIRED`: checkpoint/challenge detectado.
- `EXPIRED`: login expirado.
- `BLOCKED`: bloqueio detectado.
- `DISABLED`: desconectado via `/fb disconnect`.

## Segurança
- O agent nunca envia cookies/storage_state.
- O servidor recebe apenas status, erros e timestamps.
- O token de bootstrap expira em 5 minutos e é de uso único.

## Troubleshooting
- `CHECKPOINT`: complete o checkpoint no navegador local e aguarde validação.
- `BLOCKED`: aguarde desbloqueio da conta e reconecte com `/fb connect`.
- `offline`: reabra o agent local.
