# Segurança de secrets

## Regras básicas

- **Nunca comite `.env`**: ele contém token do bot e credenciais do banco.
- Use `.env.example` como template.
- Se você já compartilhou um `.env` por zip/print, **rotacione imediatamente**:
  - Telegram: revogue e gere um novo `TELEGRAM_BOT_TOKEN` via @BotFather.
  - Supabase/Postgres: troque a senha/role usada no `DATABASE_URL` (ou crie um usuário novo).

## Sugestões para produção

- No Raspberry Pi, use `EnvironmentFile=/opt/autohunter/.env` (systemd já faz isso).
- No CI/CD, use o cofre de secrets do provider (GitHub Actions Secrets, etc.).
