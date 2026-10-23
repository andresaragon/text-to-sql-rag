"""El conjunto de referencia contra las dos bases reales (SPEC.md, CA2). No se edita."""

import json
from pathlib import Path

import psycopg2
import pytest

from scripts import gen_dataset
from tests.bench_support import normalize, same

from .conftest import ENABLED, oracle_reader

pytestmark = pytest.mark.skipif(not ENABLED, reason="necesita las bases: bash tests/run_bench_acceptance.sh")

QUESTIONS = json.loads((Path(__file__).resolve().parents[2] / "benchmarks" / "gold.json").read_text(encoding="utf-8"))["questions"]


@pytest.fixture(scope="module")
def databases():
    pg = psycopg2.connect(gen_dataset.PG_URL).cursor()
    oracle = oracle_reader().cursor()
    return pg, oracle


def _rows(cursor, sql):
    cursor.execute(sql)
    return cursor.fetchall()


def test_both_databases_hold_the_same_data(databases):
    pg, oracle = databases
    for table, measure in (("customers", "COUNT(*)"), ("invoices", "SUM(amount)"), ("payments", "SUM(amount_paid)"),
                           ("collection_actions", "COUNT(*)")):
        sql = f"SELECT {measure} FROM {table}"
        assert same(_rows(pg, sql), _rows(oracle, sql), ordered=True), table
    counts = [_rows(pg, f"SELECT COUNT(*) FROM {t}")[0][0] for t in gen_dataset.TABLES]
    assert counts == [300, 2000, 1486, 1117]


@pytest.mark.parametrize("question", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_the_two_references_return_the_same_result(databases, question):
    pg, oracle = databases
    postgres_rows = _rows(pg, question["sql"]["postgres"])
    oracle_rows = _rows(oracle, question["sql"]["oracle"])
    assert same(postgres_rows, oracle_rows, question["ordered"]), (postgres_rows[:3], oracle_rows[:3])


@pytest.mark.parametrize("question", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_no_reference_is_trivial(databases, question):
    rows = normalize(_rows(databases[0], question["sql"]["postgres"]))
    assert rows, "la referencia no devuelve filas"
    assert not all(value in (None, 0.0) for row in rows for value in row), "la referencia da solo ceros o nulos"
    assert len(rows) <= 100  # cabe en el tope de filas del firewall


def test_no_reference_is_guessable_by_a_constant_query(databases):
    for question in QUESTIONS:
        rows = normalize(_rows(databases[0], question["sql"]["postgres"]))
        assert rows not in ([(1.0,)], [(0.0,)]), f"{question['id']}: se acierta con SELECT 1 o SELECT 0"


def test_the_references_have_pairwise_different_results(databases):
    seen = {}
    for question in QUESTIONS:
        key = repr(sorted(map(repr, normalize(_rows(databases[0], question["sql"]["postgres"])))))
        assert key not in seen, f"{question['id']} y {seen[key]} tienen el mismo resultado"
        seen[key] = question["id"]
