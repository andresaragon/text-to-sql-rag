"""Runner del benchmark A/B."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from ollama import ResponseError

from scripts.bench_ab.strategies import (
    EXEC_DIALECT,
    PROMPT_DIALECT,
    Evaluation,
    evaluate_sql,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Result:
    model: str
    strategy: str
    question_id: str
    category: str
    difficulty: str
    original_question: int | None
    raw_sql: str | None
    evaluation: Evaluation
    timings_ms: dict[str, float]


def load_gold(path: str | Path | None = None) -> list[dict]:
    """Carga las preguntas y consultas de referencia desde benchmarks/gold.json."""
    gold_path = Path(path) if path else ROOT / "benchmarks" / "gold.json"
    data = json.loads(gold_path.read_text(encoding="utf-8"))
    return data["questions"]


def run_benchmark(
    *,
    questions: Sequence[dict[str, Any]],
    models: Sequence[str],
    strategies: Sequence[str],
    generate: Callable[[str, str, str], str | None],
    execute: Callable[[str, str], list[dict]],
    prepare: Callable[[str], None] | None = None,
    progress: Callable[[Result], None] | None = None,
) -> list[Result]:
    """
    Ejecuta el benchmark A/B para los modelos y estrategias indicados.
    Caché de consultas de referencia por (dialecto_ejecucion, id_pregunta).
    """
    results: list[Result] = []
    gold_cache: dict[tuple[str, str], list[dict]] = {}

    for model in models:
        for prompt_dialect in ("postgres", "oracle"):
            strats_for_dialect = [s for s in strategies if PROMPT_DIALECT.get(s) == prompt_dialect]
            if not strats_for_dialect:
                continue

            if prepare is not None:
                prepare(prompt_dialect)

            for strategy in strats_for_dialect:
                for q in questions:
                    t_gen_0 = time.perf_counter()
                    raw_sql: str | None = None
                    gen_error: str | None = None
                    try:
                        raw_sql = generate(model, prompt_dialect, q["question"])
                    except (RuntimeError, OSError, ValueError, httpx.HTTPError, ResponseError) as err:
                        gen_error = str(err)
                    gen_ms = (time.perf_counter() - t_gen_0) * 1000.0

                    t_eval_0 = time.perf_counter()
                    if gen_error is not None:
                        evaluation = Evaluation(
                            status="generation_error",
                            strict=False,
                            relaxed=False,
                            final_sql=None,
                            error=gen_error,
                            error_code=None,
                        )
                    else:
                        exec_dialect = EXEC_DIALECT[strategy]
                        cache_key = (exec_dialect, q["id"])
                        if cache_key not in gold_cache:
                            ref_sql = q["sql"][exec_dialect]
                            gold_cache[cache_key] = execute(exec_dialect, ref_sql)
                        gold_rows = gold_cache[cache_key]

                        evaluation = evaluate_sql(
                            strategy=strategy,
                            raw_sql=raw_sql,
                            gold_rows=gold_rows,
                            ordered=q.get("ordered", False),
                            execute=execute,
                        )
                    eval_ms = (time.perf_counter() - t_eval_0) * 1000.0

                    res = Result(
                        model=model,
                        strategy=strategy,
                        question_id=q["id"],
                        category=q["category"],
                        difficulty=q["difficulty"],
                        original_question=q.get("original_question"),
                        raw_sql=raw_sql,
                        evaluation=evaluation,
                        timings_ms={"generate": gen_ms, "evaluate": eval_ms},
                    )
                    results.append(res)
                    if progress is not None:
                        progress(res)

    return results
