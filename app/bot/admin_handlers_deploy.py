from __future__ import annotations

from app.bot.text_sanitize import sanitize_for_telegram
from app.db.session import SessionLocal
from app.services.admin_deploy_service import AdminDeployService, DeployActor


async def admin_deploy(update, args: list[str], *, fmt_dt):
    sub = (args[0].lower() if args else "")
    actor = DeployActor(
        chat_id=update.effective_chat.id,
        tg_user_id=(update.effective_user.id if update.effective_user else None),
        username=(update.effective_user.username if update.effective_user else None),
    )

    with SessionLocal() as db:
        service = AdminDeployService(db)
        allowed, reason = service.is_allowed(actor)
        if not allowed:
            await update.message.reply_text(reason or "Sem permissão.")
            return

        if sub in ("", "preflight"):
            try:
                out = service.request_deploy(actor)
            except ValueError as e:
                await update.message.reply_text(str(e))
                return
            preflight = out["preflight"]
            privilege_ready = bool(preflight.get("privilege_ready", True))
            lines = [
                "Deploy admin (preflight):",
                f"- operation_id: {out['operation_id']}",
                f"- branch: {preflight.get('branch')}",
                f"- commit: {preflight.get('commit')}",
                f"- working_tree: {preflight.get('working_tree')}",
                f"- remote_ok: {'yes' if preflight.get('remote_ok') else 'no'}",
                f"- remote_diff: {preflight.get('remote_diff')}",
                f"- privilege_ready: {'yes' if privilege_ready else 'no'}",
                f"- privilege_error_type: {preflight.get('privilege_error_type') or '-'}",
            ]
            if preflight.get("privilege_error_message"):
                lines.append(f"- privilege_error_message: {preflight.get('privilege_error_message')}")
            if preflight.get("working_tree") != "clean":
                lines.append("Deploy bloqueado no preflight: working tree dirty. Limpe/reverta arquivos runtime (state/cache/log) e rode /admin deploy novamente.")
            elif not preflight.get("remote_ok"):
                lines.append("Deploy bloqueado no preflight: remoto indisponível (remote_ok=no).")
            elif preflight.get("branch") in (None, "", "unknown") or preflight.get("commit") in (None, "", "unknown"):
                lines.append("Deploy bloqueado no preflight: erro estrutural do host (estado git inválido).")
            elif privilege_ready:
                lines.extend([f"Confirme em até {out['expires_in']}s com:", f"/admin deploy confirm {out['operation_id']}"])
            else:
                lines.append("Deploy bloqueado no preflight. Corrija a configuração do host antes de confirmar.")
            await update.message.reply_text("\n".join(lines))
            return

        if sub == "confirm":
            operation_id = (args[1] if len(args) > 1 else "").strip()
            if not operation_id:
                await update.message.reply_text("Use: /admin deploy confirm <operation_id>")
                return
            await update.message.reply_text("Deploy iniciado. Aguardando execução do wrapper...")
            try:
                result = await service.confirm_deploy(actor, operation_id)
                lines = [
                    f"Deploy finalizado: {'OK' if result['ok'] else 'FALHA'}",
                    f"- operation_id: {result['operation_id']}",
                    f"- branch: {result.get('branch') or '-'}",
                    f"- before: {result.get('before_commit') or '-'}",
                    f"- after: {result.get('after_commit') or '-'}",
                    f"- summary: {result.get('summary') or '-'}",
                ]
                if result.get("output_tail"):
                    lines.append("- output_tail:\n" + sanitize_for_telegram(result["output_tail"]))
                await update.message.reply_text("\n".join(lines))
            except ValueError as e:
                await update.message.reply_text(str(e))
            return

        if sub == "status":
            out = service.deploy_status()
            last = out.get("last")
            current = out.get("current")
            if not last:
                await update.message.reply_text("Deploy status: idle\nÚltimo deploy (UTC): -")
                return

            duration = "-"
            if last.started_at and last.finished_at:
                duration = f"{int((last.finished_at - last.started_at).total_seconds())}s"

            last_deploy_at = fmt_dt(last.finished_at or last.started_at or last.requested_at)
            lines = [
                f"Deploy status: {out.get('status')}",
                f"Último deploy (UTC): {last_deploy_at}",
                f"Último resultado: {last.status}",
                f"Branch: {last.branch or '-'}",
                f"Before: {last.before_commit or '-'}",
                f"After: {last.after_commit or '-'}",
                f"Duração: {duration}",
                f"Resumo: {last.summary or '-'}",
            ]
            if current:
                lines.extend([
                    "Operação em andamento:",
                    f"- operation_id: {current.operation_id}",
                    f"- started_at_utc: {fmt_dt(current.started_at)}",
                ])
            await update.message.reply_text("\n".join(lines))
            return

        await update.message.reply_text("Use: /admin deploy | /admin deploy confirm <operation_id> | /admin deploy status")
