from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.admin_deploy_audit import AdminDeployAudit


def _parse_int_set(raw: str | None) -> set[int]:
    out: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)




def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _truncate(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 12)] + "\n...[truncated]"


def _classify_privilege_error(stderr: str, returncode: int) -> tuple[str, str]:
    normalized = (stderr or "").strip()
    lowered = normalized.lower()
    if "no new privileges" in lowered:
        return "no_new_privileges", "Serviço do bot está com NoNewPrivileges ativo e não pode usar sudo."
    if "a password is required" in lowered:
        return "sudo_password_required", "sudo requer senha interativa; configure NOPASSWD para o wrapper permitido."
    if "not allowed to run sudo" in lowered or "is not in the sudoers file" in lowered:
        return "sudo_not_allowed", "Usuário do bot não possui regra sudoers para o wrapper configurado."
    if "command not found" in lowered and "sudo" in lowered:
        return "sudo_not_found", "Comando sudo não encontrado no host."
    if returncode != 0:
        return "sudo_check_failed", f"Validação de sudo falhou (exit={returncode})."
    return "unknown", "Falha desconhecida ao validar execução privilegiada."


@dataclass
class DeployActor:
    chat_id: int
    tg_user_id: Optional[int]
    username: Optional[str]


class AdminDeployService:
    _lock = asyncio.Lock()

    def __init__(self, db: Session):
        self.db = db
        self.pending_ttl_seconds = int(getattr(settings, "admin_deploy_pending_ttl_seconds", 120) or 120)
        self.rate_limit_seconds = int(getattr(settings, "admin_deploy_rate_limit_seconds", 300) or 300)
        self.wrapper_timeout_seconds = int(getattr(settings, "admin_deploy_wrapper_timeout_seconds", 180) or 180)
        self.output_max = int(getattr(settings, "admin_deploy_output_max_chars", 1200) or 1200)
        self.allowed_user_ids = _parse_int_set(getattr(settings, "autohunter_admin_user_ids", None))
        self.allowed_chat_ids = _parse_int_set(getattr(settings, "autohunter_admin_chat_ids", None) or settings.autohunter_admins)

    def is_allowed(self, actor: DeployActor) -> tuple[bool, Optional[str]]:
        if self.allowed_chat_ids and actor.chat_id not in self.allowed_chat_ids:
            return False, "Chat não permitido para deploy admin."
        if self.allowed_user_ids and (actor.tg_user_id or 0) not in self.allowed_user_ids:
            return False, "Usuário não permitido para deploy admin."
        return True, None

    def _last_by_user(self, tg_user_id: Optional[int]) -> Optional[AdminDeployAudit]:
        if tg_user_id is None:
            return None
        return (
            self.db.query(AdminDeployAudit)
            .filter(AdminDeployAudit.requested_by_tg_user_id == tg_user_id)
            .order_by(AdminDeployAudit.requested_at.desc())
            .first()
        )

    def _run_preflight(self) -> dict:
        root = Path(__file__).resolve().parents[2]

        def run(*args: str, timeout: int = 15) -> tuple[int, str, str]:
            cp = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=timeout)
            return cp.returncode, cp.stdout.strip(), cp.stderr.strip()

        branch = "unknown"
        commit = "unknown"
        tree = "dirty"
        remote_ok = False
        remote_diff = "indisponível"
        wrapper_path = str(getattr(settings, "admin_deploy_wrapper_path", "/usr/local/bin/autohunter-admin-deploy"))
        use_sudo = bool(getattr(settings, "admin_deploy_use_sudo", True))

        privilege_ready = True
        privilege_error_type = None
        privilege_error_message = None

        rc, out, _ = run("git", "rev-parse", "--abbrev-ref", "HEAD")
        if rc == 0 and out:
            branch = out

        rc, out, _ = run("git", "rev-parse", "HEAD")
        if rc == 0 and out:
            commit = out

        rc, out, _ = run("git", "status", "--porcelain")
        if rc == 0:
            tree = "clean" if not out else "dirty"

        rc, _, _ = run("git", "ls-remote", "--heads", "origin", branch)
        remote_ok = rc == 0

        if remote_ok:
            run("git", "fetch", "origin", branch, timeout=30)
            rc, out, err = run("git", "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}")
            if rc == 0 and out:
                remote_diff = out
            elif err:
                remote_diff = err

        wrapper = Path(wrapper_path)
        if not wrapper.exists():
            privilege_ready = False
            privilege_error_type = "wrapper_not_found"
            privilege_error_message = f"Wrapper não encontrado em {wrapper_path}."
        elif (not wrapper.is_file()) or not (wrapper.stat().st_mode & 0o111):
            privilege_ready = False
            privilege_error_type = "wrapper_not_executable"
            privilege_error_message = f"Wrapper sem permissão de execução em {wrapper_path}."
        elif use_sudo:
            rc, _, stderr = run("sudo", "-n", "-l", "--", wrapper_path)
            if rc != 0:
                privilege_ready = False
                mapped_type, mapped_message = _classify_privilege_error(stderr, rc)
                privilege_error_type = mapped_type
                privilege_error_message = f"{mapped_message} stderr={_truncate(stderr or '-', 240)}"

        return {
            "branch": branch,
            "commit": commit,
            "working_tree": tree,
            "remote_ok": remote_ok,
            "remote_diff": remote_diff,
            "privilege_ready": privilege_ready,
            "privilege_error_type": privilege_error_type,
            "privilege_error_message": privilege_error_message,
        }

    def request_deploy(self, actor: DeployActor) -> dict:
        last = self._last_by_user(actor.tg_user_id)
        now = _utcnow()
        if last and (now - _as_utc(last.requested_at)).total_seconds() < self.rate_limit_seconds:
            wait_for = int(self.rate_limit_seconds - (now - _as_utc(last.requested_at)).total_seconds())
            raise ValueError(f"Rate limit ativo. Tente novamente em {wait_for}s.")

        preflight = self._run_preflight()
        operation_id = uuid.uuid4().hex[:12]
        audit = AdminDeployAudit(
            operation_id=operation_id,
            requested_by_tg_user_id=actor.tg_user_id,
            requested_by_username=actor.username,
            chat_id=actor.chat_id,
            requested_at=now,
            expires_at=now + timedelta(seconds=self.pending_ttl_seconds),
            status="pending_confirmation",
            branch=preflight["branch"],
            before_commit=preflight["commit"],
            summary=("preflight_ok" if preflight.get("privilege_ready", True) else "preflight_blocked_privilege"),
            error_type=(
                None
                if preflight.get("privilege_ready", True)
                else f"privilege_{preflight.get('privilege_error_type') or 'unknown'}"
            ),
            error_message=(None if preflight.get("privilege_ready", True) else preflight.get("privilege_error_message")),
        )
        self.db.add(audit)
        self.db.commit()
        return {"operation_id": operation_id, "preflight": preflight, "expires_in": self.pending_ttl_seconds}

    async def confirm_deploy(self, actor: DeployActor, operation_id: str) -> dict:
        now = _utcnow()
        audit = (
            self.db.query(AdminDeployAudit)
            .filter(AdminDeployAudit.operation_id == operation_id)
            .first()
        )
        if not audit:
            raise ValueError("operation_id inválido.")
        if audit.status != "pending_confirmation":
            raise ValueError("Operação já confirmada/finalizada.")
        if (audit.error_type or "").startswith("privilege_"):
            audit.status = "blocked"
            audit.finished_at = now
            audit.summary = "blocked_by_preflight_privilege"
            self.db.commit()
            raise ValueError(
                "Deploy bloqueado por configuração do host: o serviço do bot está com NoNewPrivileges e não pode usar sudo. "
                "Ajuste o systemd/sudoers e rode /admin deploy novamente."
                if audit.error_type == "privilege_no_new_privileges"
                else f"Deploy bloqueado no preflight: {audit.error_message or 'privilégio indisponível.'}"
            )
        if not audit.expires_at or _as_utc(audit.expires_at) < now:
            audit.status = "expired"
            self.db.commit()
            raise ValueError("Operação expirada. Rode /admin deploy novamente.")

        if self._lock.locked():
            raise ValueError("Já existe deploy em andamento.")

        async with self._lock:
            audit.confirmed_at = now
            audit.started_at = _utcnow()
            audit.status = "running"
            self.db.commit()

            started = time.monotonic()
            try:
                wrapper_cmd = [getattr(settings, "admin_deploy_wrapper_path", "/usr/local/bin/autohunter-admin-deploy")]
                if bool(getattr(settings, "admin_deploy_use_sudo", True)):
                    wrapper_cmd = ["sudo"] + wrapper_cmd
                cp = await asyncio.to_thread(
                    subprocess.run,
                    wrapper_cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.wrapper_timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                audit.finished_at = _utcnow()
                audit.status = "failed"
                audit.error_type = "timeout"
                audit.error_message = f"timeout>{self.wrapper_timeout_seconds}s"
                self.db.commit()
                raise ValueError("Deploy falhou por timeout.")

            duration_ms = int((time.monotonic() - started) * 1000)
            stdout_tail = _truncate(cp.stdout, self.output_max)
            stderr_tail = _truncate(cp.stderr, self.output_max)
            output_tail = _truncate(f"STDOUT:\n{stdout_tail}\n\nSTDERR:\n{stderr_tail}", self.output_max)

            payload = None
            try:
                payload = json.loads(cp.stdout or "{}")
            except Exception:
                payload = None

            ok = bool(payload and payload.get("ok") and cp.returncode == 0)
            audit.finished_at = _utcnow()
            audit.status = "succeeded" if ok else "failed"
            audit.summary = (payload or {}).get("status") or ("ok" if ok else "error")
            audit.before_commit = (payload or {}).get("before_commit") or audit.before_commit
            audit.after_commit = (payload or {}).get("after_commit")
            audit.branch = (payload or {}).get("branch") or audit.branch
            audit.services_json = (payload or {}).get("services") if isinstance((payload or {}).get("services"), dict | list) else None
            audit.output_tail = output_tail
            if not ok:
                audit.error_type = (payload or {}).get("error_type") or f"exit_{cp.returncode}"
                audit.error_message = (payload or {}).get("error_message") or _truncate(stderr_tail or stdout_tail, 240)
            audit.summary = f"{audit.summary}; duration_ms={duration_ms}"
            self.db.commit()

            return {
                "ok": ok,
                "status": audit.status,
                "summary": audit.summary,
                "operation_id": operation_id,
                "branch": audit.branch,
                "before_commit": audit.before_commit,
                "after_commit": audit.after_commit,
                "output_tail": output_tail,
            }

    def deploy_status(self) -> dict:
        last = self.db.query(AdminDeployAudit).order_by(AdminDeployAudit.requested_at.desc()).first()
        return {
            "running": self._lock.locked(),
            "last": last,
        }
