"""Conjunto de referencia del benchmark A/B (SPEC.md, CA2), parte estática. No se edita."""

import json
import re
from pathlib import Path

import pytest

from app.core.safety import validate_and_prepare

GOLD = json.loads((Path(__file__).resolve().parents[1] / "benchmarks" / "gold.json").read_text(encoding="utf-8"))
QUESTIONS = GOLD["questions"]
IDS = [q["id"] for q in QUESTIONS]
RELATIVE_TIME = re.compile(r"(?i)\b(NOW\s*\(|CURRENT_DATE|CURRENT_TIMESTAMP|SYSDATE|SYSTIMESTAMP|LOCALTIMESTAMP)")


def test_the_file_has_thirty_questions_with_the_expected_shape():
    assert GOLD["version"] == 1 and GOLD["reference_date"] == "2026-10-01"
    assert IDS == [f"q{n:02d}" for n in range(1, 31)]
    for q in QUESTIONS:
        assert {"id", "question", "category", "difficulty", "ordered", "original_question", "sql"} <= set(q), q["id"]
        assert q["question"].startswith("¿") or q["question"][0].isupper(), q["id"]
        assert q["difficulty"] in {"facil", "media", "dificil"}, q["id"]
        assert isinstance(q["ordered"], bool), q["id"]
        assert set(q["sql"]) == {"postgres", "oracle"}, q["id"]
        assert all(q["sql"][d].strip() for d in q["sql"]), q["id"]


def test_the_questions_are_unique_and_the_mix_is_balanced():
    assert len({q["question"] for q in QUESTIONS}) == 30
    counts = {d: sum(1 for q in QUESTIONS if q["difficulty"] == d) for d in ("facil", "media", "dificil")}
    assert all(n >= 6 for n in counts.values()), counts
    assert len({q["category"] for q in QUESTIONS}) >= 8


def test_ten_questions_map_to_the_original_ten_without_repeats():
    originals = sorted(q["original_question"] for q in QUESTIONS if q["original_question"])
    assert originals == list(range(1, 11))


def test_no_reference_depends_on_today():
    for q in QUESTIONS:
        for dialect, sql in q["sql"].items():
            assert not RELATIVE_TIME.search(sql), (q["id"], dialect)


def test_ordered_questions_have_an_order_by_and_no_unordered_one_needs_it():
    for q in QUESTIONS:
        if q["ordered"]:
            assert all("ORDER BY" in sql.upper() for sql in q["sql"].values()), q["id"]


def test_the_dialect_specific_syntax_is_where_it_should_be():
    for q in QUESTIONS:
        postgres, oracle = q["sql"]["postgres"], q["sql"]["oracle"]
        assert not re.search(r"(?i)\bFETCH\s+FIRST\b", postgres), q["id"]
        assert not re.search(r"(?i)\bLIMIT\s+\d", oracle), q["id"]
        assert "::" not in oracle and not re.search(r"(?i)\b(STRING_AGG|DATE_TRUNC|ILIKE)\b", oracle), q["id"]


@pytest.mark.parametrize("question", QUESTIONS, ids=IDS)
def test_every_reference_passes_the_firewall_of_its_dialect(question):
    validate_and_prepare(question["sql"]["postgres"], 100, dialect="postgres")
    validate_and_prepare(question["sql"]["oracle"], 100, dialect="oracle", allowed_schema="SALES")
