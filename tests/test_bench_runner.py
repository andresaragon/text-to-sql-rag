"""Runner del benchmark A/B (SPEC.md, CA5). Escritas antes de implementar; no se editan."""

import dataclasses
import importlib

from app.core.db import QueryExecutionError


def runner():
    return importlib.import_module("scripts.bench_ab.runner")


def strategies():
    return importlib.import_module("scripts.bench_ab.strategies")


QUESTIONS = [
    {"id": "t1", "question": "¿Cuántos clientes hay?", "category": "conteo", "difficulty": "facil", "ordered": False,
     "original_question": None, "sql": {"postgres": "SELECT COUNT(*) FROM customers", "oracle": "SELECT COUNT(*) FROM customers"}},
    {"id": "t2", "question": "¿Cuántos pagos hay?", "category": "conteo", "difficulty": "media", "ordered": False,
     "original_question": 6, "sql": {"postgres": "SELECT COUNT(*) FROM payments", "oracle": "SELECT COUNT(*) FROM payments"}},
]
REFERENCES = {q["sql"][d] for q in QUESTIONS for d in ("postgres", "oracle")}


class FakeDatabase:
    """execute(dialect, sql): cuenta filas por tabla y deja constancia de cada llamada."""

    def __init__(self):
        self.calls = []

    def __call__(self, dialect, sql):
        self.calls.append((dialect, sql))
        if "customers" in sql:
            return [{"count": 300}]
        if "payments" in sql:
            return [{"count": 1486}]
        raise QueryExecutionError("No se pudo ejecutar la consulta: ORA-00942: table or view does not exist")


def gold_generator(model, dialect, question):
    return next(q["sql"][dialect] for q in QUESTIONS if q["question"] == question)


def run(generate, models=("m1", "m2"), prepare=None, database=None):
    database = database or FakeDatabase()
    prepared = []
    results = runner().run_benchmark(
        questions=QUESTIONS, models=list(models), strategies=list(strategies().STRATEGIES),
        generate=generate, execute=database, prepare=prepare or prepared.append,
    )
    return results, prepared, database


def test_load_gold_reads_the_thirty_questions():
    questions = runner().load_gold()
    assert len(questions) == 30 and questions[0]["id"] == "q01"


def test_result_is_a_dataclass_with_the_documented_fields():
    result = runner().Result
    assert dataclasses.is_dataclass(result)
    assert {f.name for f in dataclasses.fields(result)} == {
        "model", "strategy", "question_id", "category", "difficulty", "original_question", "raw_sql", "evaluation", "timings_ms",
    }


def test_fed_with_the_reference_sql_everything_is_correct():
    results, _, _ = run(gold_generator)
    assert len(results) == 2 * 3 * 2
    assert all(r.evaluation.status == "correct" and r.evaluation.strict for r in results)
    assert {(r.model, r.strategy, r.question_id) for r in results} == {
        (m, s, q["id"]) for m in ("m1", "m2") for s in strategies().STRATEGIES for q in QUESTIONS
    }


def test_fed_with_wrong_sql_only_the_matching_question_is_correct():
    results, _, _ = run(lambda model, dialect, question: "SELECT COUNT(*) FROM payments")
    for r in results:
        assert r.evaluation.strict == (r.question_id == "t2"), r
    assert all(r.raw_sql == "SELECT COUNT(*) FROM payments" for r in results)


def test_the_index_is_prepared_once_per_dialect_and_model_in_that_order():
    _, prepared, _ = run(gold_generator)
    assert prepared == ["postgres", "oracle", "postgres", "oracle"]


def test_the_prompt_dialect_follows_the_strategy():
    seen = []
    results, _, _ = run(lambda model, dialect, question: seen.append(dialect) or gold_generator(model, dialect, question), models=("m1",))
    assert sorted(seen) == ["oracle"] * 2 + ["postgres"] * 4
    assert len(results) == 6


def test_the_reference_sql_is_executed_once_per_dialect_and_question():
    _, _, database = run(gold_generator)
    reference_runs = [call for call in database.calls if call[1] in REFERENCES]
    assert len(reference_runs) == 4  # 2 preguntas x 2 dialectos, aunque haya 2 modelos y 3 estrategias


def test_the_gold_rows_of_each_strategy_come_from_its_own_execution_dialect():
    _, _, database = run(gold_generator, models=("m1",))
    assert {d for d, sql in database.calls if sql in REFERENCES} == {"postgres", "oracle"}


def test_a_generator_that_raises_is_a_generation_error_and_the_run_continues():
    def failing(model, dialect, question):
        if question == QUESTIONS[0]["question"]:
            raise RuntimeError("ollama caído")
        return gold_generator(model, dialect, question)

    results, _, _ = run(failing, models=("m1",))
    broken = [r for r in results if r.question_id == "t1"]
    assert broken and all(r.evaluation.status == "generation_error" and "ollama caído" in r.evaluation.error for r in broken)
    assert all(r.evaluation.status == "correct" for r in results if r.question_id == "t2")


def test_every_result_has_timings_and_carries_the_question_metadata():
    results, _, _ = run(gold_generator, models=("m1",))
    for r in results:
        assert set(r.timings_ms) >= {"generate", "evaluate"} and all(v >= 0 for v in r.timings_ms.values())
    assert {(r.question_id, r.category, r.difficulty, r.original_question) for r in results} == {
        ("t1", "conteo", "facil", None), ("t2", "conteo", "media", 6),
    }
