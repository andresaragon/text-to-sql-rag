"""El arnés completo contra las dos bases reales (SPEC.md, CA8). No se edita.

La propiedad que importa: alimentado con el SQL de referencia, el arnés debe dar el 100 % en las estrategias
directas; y con SQL equivocado, 0 %. Un arnés que no cumple eso no mide nada.
"""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from .conftest import ENABLED

pytestmark = pytest.mark.skipif(not ENABLED, reason="necesita las bases: bash tests/run_bench_acceptance.sh")

ROOT = Path(__file__).resolve().parents[2]
# Techo medido de la transpilación Postgres -> Oracle con sqlglot 25.24.0 sobre las referencias: ver SPEC.md.
TRANSPILE_CEILING = 27


def run_cli(tmp_path, *args):
    out_json, out_md = tmp_path / "result.json", tmp_path / "report.md"
    command = [sys.executable, "-m", "scripts.bench_ab", *args, "--out-json", str(out_json), "--out-md", str(out_md)]
    done = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-1500:]
    return json.loads(out_json.read_text(encoding="utf-8")), out_md.read_text(encoding="utf-8")


def strict_by_strategy(rows):
    counts = Counter(r["strategy"] for r in rows if r["strict"])
    totals = Counter(r["strategy"] for r in rows)
    return counts, totals


def test_fed_with_the_reference_sql_the_direct_strategies_score_one_hundred_percent(tmp_path):
    rows, report = run_cli(tmp_path, "--llm", "gold", "--models", "referencia", "--strategies", "pg_direct", "oracle_direct")
    counts, totals = strict_by_strategy(rows)
    assert totals == {"pg_direct": 30, "oracle_direct": 30}
    wrong = [(r["strategy"], r["question_id"], r["status"], r["error"]) for r in rows if not r["strict"]]
    assert not wrong, wrong
    assert counts == {"pg_direct": 30, "oracle_direct": 30}
    assert report.startswith("# ") and "30/30" in report


def test_fed_with_wrong_sql_nothing_scores(tmp_path):
    rows, _ = run_cli(tmp_path, "--llm", "wrong", "--models", "equivocado", "--strategies", "all")
    counts, totals = strict_by_strategy(rows)
    assert totals == {"pg_direct": 30, "oracle_direct": 30, "pg_transpiled": 30}
    assert sum(counts.values()) == 0
    assert all(r["status"] in {"wrong", "execution_error", "firewall_rejected"} for r in rows)


def test_the_transpilation_ceiling_is_measured_and_every_failure_is_classified(tmp_path):
    rows, _ = run_cli(tmp_path, "--llm", "gold", "--models", "referencia", "--strategies", "pg_transpiled")
    assert len(rows) == 30
    correct = sum(1 for r in rows if r["strict"])
    assert correct == TRANSPILE_CEILING, f"el techo medido cambió: {correct} (¿cambió sqlglot?)"
    for r in rows:
        if not r["strict"]:
            assert r["status"] in {"wrong", "execution_error", "firewall_rejected"}
            assert r["error"] or r["status"] == "wrong"
            if r["status"] == "execution_error":
                assert r["error_code"]  # ORA-xxxxx o TRANSPILE: nunca un error sin clasificar


def test_limit_and_the_model_list_are_respected(tmp_path):
    rows, _ = run_cli(tmp_path, "--llm", "gold", "--models", "a", "b", "--strategies", "oracle_direct", "--limit", "5")
    assert len(rows) == 10
    assert {r["model"] for r in rows} == {"a", "b"}
    assert {r["question_id"] for r in rows} == {"q01", "q02", "q03", "q04", "q05"}


def test_the_json_rows_carry_timings_and_the_raw_sql(tmp_path):
    rows, _ = run_cli(tmp_path, "--llm", "gold", "--models", "referencia", "--strategies", "oracle_direct", "--limit", "3")
    for r in rows:
        assert r["raw_sql"].upper().startswith("SELECT")
        assert r["timings_ms"]["generate"] >= 0 and r["timings_ms"]["evaluate"] > 0
        assert r["final_sql"] and "FETCH FIRST" in r["final_sql"].upper()
