"""Teste de mutacao de UM modulo, isolado numa copia do repositorio.

Uso:
    py tools/mutation_test.py app/services/source_backoff_service.py
    py tools/mutation_test.py app/services/source_backoff_service.py --tests tests/test_a.py tests/test_b.py
    py tools/mutation_test.py app/services/x.py --jobs 4 --timeout 60

O que faz
  1. copia app/, tests/, config/ e arquivos de raiz para .data/mutation/<modulo>/repo (o
     cosmic-ray reescreve o arquivo-alvo no disco; na copia o codigo real nunca e tocado);
  2. descobre os testes que importam o modulo (ou usa --tests);
  3. roda o cosmic-ray (baseline + exec) e, para cada mutante, grava quais testes falharam;
  4. escreve .data/mutation/<modulo>/result.json e um resumo em texto.

Saida (result.json): score, mutantes sobreviventes (com linha e operador) e a matriz
"teste -> mutantes que mata". Teste que nao mata nenhum mutante nem cobre linha exclusiva e
candidato a remocao; mutante sobrevivente e candidato a teste novo.

Requer: pip install cosmic-ray   (mutmut NAO roda em Windows: exige os.fork)
Nao rode em producao: cada mutante executa pytest.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK_BASE = ROOT / ".data" / "mutation"
COPY_DIRS = ("app", "tests", "config", "migrations")
COPY_FILES = ("pytest.ini", "alembic.ini", "requirements.txt")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".data", "*.db")
FAILED_RE = re.compile(r"^FAILED\s+(\S+)", re.M)


def _slug(module: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", module.removesuffix(".py")).strip("_")


def discover_tests(module: str) -> list[str]:
    dotted = module.removesuffix(".py").replace("/", ".")
    base = Path(module).stem
    pattern = re.compile(rf"\b{re.escape(dotted)}\b|\bimport\s+{re.escape(base)}\b|\b{re.escape(base)}\b")
    found = []
    for p in sorted((ROOT / "tests").rglob("test_*.py")):
        try:
            if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                found.append(p.relative_to(ROOT).as_posix())
        except OSError:
            continue
    return found


def prepare_copy(work: Path) -> Path:
    repo = work / "repo"
    if repo.exists():
        def _force_remove(func, path, _exc):  # Windows: arquivos somente-leitura / recem-usados
            import os
            import stat

            os.chmod(path, stat.S_IWRITE)
            func(path)

        shutil.rmtree(repo, onerror=_force_remove)
    repo.mkdir(parents=True, exist_ok=True)
    for d in COPY_DIRS:
        if (ROOT / d).exists():
            shutil.copytree(ROOT / d, repo / d, ignore=IGNORE)
    for f in COPY_FILES:
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, repo / f)
    return repo


def write_config(work: Path, module: str, tests: list[str], timeout: float) -> Path:
    cmd = f'"{sys.executable}" -m pytest {" ".join(tests)} -q -p no:warnings -p no:cacheprovider --tb=no -rf'
    cfg = work / "cosmic-ray.toml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            [cosmic-ray]
            module-path = "{module}"
            timeout = {timeout}
            excluded-modules = []
            test-command = {json.dumps(cmd)}

            [cosmic-ray.distributor]
            name = "local"

            # `A | B` so aparece em anotacoes de tipo (nunca executadas com `from __future__ import
            # annotations`): os mutantes seriam equivalentes e so inflam os sobreviventes.
            [cosmic-ray.filters.operators-filter]
            exclude-operators = ["core/ReplaceBinaryOperator_BitOr_.*"]
            """
        ),
        encoding="utf-8",
    )
    return cfg


def cr(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "cosmic_ray.cli", *args], cwd=cwd, capture_output=True, text=True)


def collect(session: Path, repo: Path) -> dict:
    from cosmic_ray.work_db import WorkDB, use_db

    mutants, killers = [], {}
    with use_db(str(session), WorkDB.Mode.open) as db:
        for item, result in db.completed_work_items:
            for mut in item.mutations:
                worker = str(getattr(result.worker_outcome, "name", result.worker_outcome))
                outcome = "SKIPPED" if worker == "SKIPPED" else str(getattr(result.test_outcome, "name", result.test_outcome))
                failed = sorted(set(FAILED_RE.findall(result.output or "")))
                row = {
                    "job_id": item.job_id,
                    "operator": mut.operator_name,
                    "line": mut.start_pos[0],
                    "occurrence": mut.occurrence,
                    "outcome": outcome,
                    "killed_by": failed,
                }
                mutants.append(row)
                for t in failed:
                    killers.setdefault(t, []).append(item.job_id)
    return {"mutants": mutants, "killers": killers}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("module", help="caminho do modulo-alvo, ex.: app/services/source_backoff_service.py")
    ap.add_argument("--tests", nargs="*", help="arquivos de teste (default: auto-descoberta)")
    ap.add_argument("--timeout", type=float, default=60.0, help="timeout por mutante (s)")
    args = ap.parse_args()

    module = args.module.replace("\\", "/")
    if not (ROOT / module).exists():
        print(f"modulo nao encontrado: {module}", file=sys.stderr)
        return 2
    tests = args.tests or discover_tests(module)
    if not tests:
        print("nenhum teste encontrado para o modulo", file=sys.stderr)
        return 2

    work = WORK_BASE / _slug(module)
    work.mkdir(parents=True, exist_ok=True)
    repo = prepare_copy(work)
    cfg = write_config(work, module, tests, args.timeout)
    session = work / "session.sqlite"
    session.unlink(missing_ok=True)

    print(f"[mutacao] {module}\n[mutacao] testes: {len(tests)} arquivo(s)")
    for step in (["init", str(cfg), str(session)], ["baseline", str(cfg)]):
        r = cr(step, repo)
        if r.returncode != 0:
            print(f"[mutacao] falhou em '{step[0]}':\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}", file=sys.stderr)
            return 1
        if step[0] == "init":
            # Marca como SKIPPED os mutantes equivalentes (operators-filter do TOML) e as linhas
            # com `# pragma: no mutate`, antes de executar.
            for flt, extra in (("operators_filter", [str(cfg)]), ("pragma_no_mutate", [])):
                fr = subprocess.run(
                    [sys.executable, "-m", f"cosmic_ray.tools.filters.{flt}", str(session), *extra],
                    cwd=repo, capture_output=True, text=True,
                )
                if fr.returncode != 0:
                    print(f"[mutacao] filtro {flt} falhou:\n{fr.stderr[-800:]}", file=sys.stderr)
                    return 1
    r = cr(["exec", str(cfg), str(session)], repo)
    if r.returncode != 0:
        print(f"[mutacao] exec falhou:\n{r.stderr[-1500:]}", file=sys.stderr)
        return 1

    data = collect(session, repo)
    mutants = data["mutants"]
    killed = [m for m in mutants if m["outcome"] == "KILLED"]
    survived = [m for m in mutants if m["outcome"] == "SURVIVED"]
    skipped = [m for m in mutants if m["outcome"] == "SKIPPED"]  # equivalentes / pragma: no mutate
    other = [m for m in mutants if m["outcome"] not in ("KILLED", "SURVIVED", "SKIPPED")]
    valid = len(killed) + len(survived)
    score = round(100 * len(killed) / valid, 1) if valid else 100.0

    out = {
        "module": module,
        "tests": tests,
        "total": len(mutants),
        "killed": len(killed),
        "survived": len(survived),
        "skipped": len(skipped),
        "other": len(other),
        "score": score,
        "survivors": survived,
        "killers": data["killers"],
    }
    (work / "result.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[mutacao] mutantes={len(mutants)} mortos={len(killed)} sobreviventes={len(survived)} pulados={len(skipped)} outros={len(other)} score={score}%")
    for m in survived[:40]:
        print(f"  SOBREVIVEU linha {m['line']:>4}  {m['operator']}  (job {m['job_id']})")
    print(f"[mutacao] resultado: {work / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
