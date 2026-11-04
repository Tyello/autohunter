"""Quais testes sao NECESSARIOS para um modulo, a partir do result.json da mutacao.

Uso: py tools/test_necessity.py app_services_source_pacing_service [...]

Para cada teste (funcao, ignorando parametros) calcula o conjunto de mutantes que ele mata e:
  - EXCLUSIVO: mata ao menos um mutante que nenhum outro teste mata  -> necessario
  - REDUNDANTE: tudo que mata tambem e morto por outros              -> candidato a remocao
  - OCIOSO: nao mata nenhum mutante do modulo                          -> candidato (se o arquivo
            de teste e dedicado ao modulo) ou apenas cobre outro modulo
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = lambda x: re.sub(r"\[.*\]$", "", x)  # noqa: E731


def analyze(slug: str) -> dict:
    r = json.loads((ROOT / ".data" / "mutation" / slug / "result.json").read_text(encoding="utf-8"))
    by_test: dict[str, set] = {}
    for test, jobs in r["killers"].items():
        by_test.setdefault(base(test), set()).update(jobs)
    all_funcs = {}
    for tf in r["tests"]:
        tree = ast.parse((ROOT / tf).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
                all_funcs[f"{tf}::{n.name}"] = tf
    # Conjunto minimo (guloso) que ainda mata TODOS os mutantes mortos. Quem fica fora dele pode sair
    # sem reduzir o score; o par-a-par abaixo nao basta (dois testes que se cobrem aparecem como
    # "redundantes" ao mesmo tempo, e remover os dois perderia mortes).
    pool = {t: set(v) for t, v in by_test.items() if t in all_funcs}
    remaining = set().union(*pool.values()) if pool else set()
    keep: list[str] = []
    while remaining:
        best = max(pool, key=lambda t: (len(pool[t] & remaining), -len(pool[t])))
        if not pool[best] & remaining:
            break
        keep.append(best)
        remaining -= pool.pop(best)
    removable = sorted(t for t in by_test if t in all_funcs and t not in keep)
    exclusive, redundant, idle = [], [], []
    for t in all_funcs:
        mine = by_test.get(t, set())
        if not mine:
            idle.append(t)
            continue
        others = set().union(*(v for k, v in by_test.items() if k != t)) if len(by_test) > 1 else set()
        (exclusive if mine - others else redundant).append(t)
    return {"module": r["module"], "tests": r["tests"], "exclusive": exclusive, "redundant": redundant, "idle": idle,
            "keep": sorted(keep), "removable": removable}


if __name__ == "__main__":
    for slug in sys.argv[1:]:
        a = analyze(slug)
        print(f"\n== {a['module']}")
        print(f"   necessarios (matam algo que so eles matam): {len(a['exclusive'])}")
        print(f"   redundantes (mortes ja cobertas por outros): {len(a['redundant'])}")
        print(f"   ociosos (nenhuma morte neste modulo):        {len(a['idle'])}")
        print(f"   conjunto minimo que preserva todas as mortes: {len(a['keep'])} | removiveis sem perder morte: {len(a['removable'])}")
        for k in ("redundant", "idle"):
            for t in a[k]:
                print(f"     {k[:3]}  {t}")
