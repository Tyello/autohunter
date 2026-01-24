# Segurança (secrets)

- **Nunca comite `.env`**: ele tem token do bot e credenciais do banco.
- Use `.env.example` como template.
- Se você já compartilhou um `.env` por zip/print, **rotacione imediatamente**:
  - Telegram: revogue e gere um novo `TELEGRAM_BOT_TOKEN` via @BotFather
  - Supabase/Postgres: troque senha/role usada no `DATABASE_URL` (ou crie um usuário novo)

Sugestão (produção):
- no Raspberry Pi, use `EnvironmentFile=/opt/autohunter/.env` (systemd já faz isso)
- no CI/CD, use secrets do provider (GitHub Actions Secrets, etc.)
