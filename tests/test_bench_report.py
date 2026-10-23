"""Informe del benchmark A/B (SPEC.md, CA6). Escritas antes de implementar; no se editan."""

import importlib
import json

import pytest


def mods():
    return (importlib.import_module("scripts.bench_ab.report"), importlib.import_module("scripts.bench_ab.runner"),
            importlib.import_module("scripts.bench_ab.strategies"), importlib.import_module("scripts.bench_ab.scoring"))


def result(model, strategy, qid, status, strict=False, relaxed=False, code=None, category="conteo", original=None):
    _, runner, strategies, _ = mods()
    evaluation = strategies.Evaluation(status=status, strict=strict, relaxed=relaxed, final_sql="SELECT 1",
                                       error=None if status in ("correct", "wrong") else "boom", error_code=code)
    return runner.Result(model=model, strategy=strategy, question_id=qid, category=category, difficulty="media",
                         original_question=original, raw_sql="SELECT 1", evaluation=evaluation,
                         timings_ms={"generate": 10.0, "evaluate": 5.0})


@pytest.fixture
def results():
    return [
        result("sqlcoder", "pg_direct", "q1", "correct", True, True, original=1),
        result("sqlcoder", "pg_direct", "q2", "wrong", False, True, category="top-n"),
        result("sqlcoder", "pg_direct", "q3", "firewall_rejected", category="fechas"),
        result("sqlcoder", "pg_direct", "q4", "execution_error", code="ORA-00942", category="top-n", original=2),
        result("sqlcoder", "oracle_direct", "q1", "correct", True, True),
        result("sqlcoder", "oracle_direct", "q2", "correct", True, True, category="top-n"),
    ]


def test_summarize_counts_each_outcome(results):
    report, _, _, scoring = mods()
    summary = report.summarize(results)
    pg = summary[("sqlcoder", "pg_direct")]
    assert {k: pg[k] for k in ("n", "strict", "relaxed", "executable", "firewall_rejected", "execution_error", "generation_error")} == {
        "n": 4, "strict": 1, "relaxed": 2, "executable": 2, "firewall_rejected": 1, "execution_error": 1, "generation_error": 0,
    }
    assert pg["error_codes"] == {"ORA-00942": 1}
    assert pg["strict_ci"] == pytest.approx(scoring.wilson_interval(1, 4))
    assert pg["relaxed_ci"] == pytest.approx(scoring.wilson_interval(2, 4))
    assert summary[("sqlcoder", "oracle_direct")]["strict"] == 2


def test_the_markdown_report_has_the_required_sections_and_numbers(results):
    report, *_ = mods()
    text = report.render_markdown(results, title="Informe de prueba", checksums={"customers": "300:abc123"})
    assert text.startswith("# Informe de prueba")
    for needle in ("sqlcoder", "pg_direct", "oracle_direct", "1/4", "2/4", "2/2", "IC 95", "ORA-00942", "300:abc123"):
        assert needle in text, needle
    lowered = text.lower()
    for needle in ("por categoría", "taxonomía de errores", "preguntas originales", "limitaciones", "autor"):
        assert needle in lowered, needle


def test_the_report_lists_every_category_present(results):
    report, *_ = mods()
    text = report.render_markdown(results, title="T")
    for category in ("conteo", "top-n", "fechas"):
        assert category in text


def test_the_json_export_is_serializable_and_complete(results):
    report, *_ = mods()
    rows = report.results_to_json(results)
    assert len(rows) == 6
    json.dumps(rows)
    assert set(rows[0]) == {
        "model", "strategy", "question_id", "category", "difficulty", "original_question", "status", "strict", "relaxed",
        "raw_sql", "final_sql", "error", "error_code", "timings_ms",
    }
    assert rows[3]["error_code"] == "ORA-00942" and rows[0]["strict"] is True
