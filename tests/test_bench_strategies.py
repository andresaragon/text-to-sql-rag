"""Estrategias del benchmark A/B (SPEC.md, CA4). Escritas antes de implementar; no se editan."""

import dataclasses
import importlib

import pytest
from sqlalchemy.exc import DatabaseError

from app.core.db import DatabaseUnavailableError, QueryExecutionError, QueryTimeoutError


def strategies():
    return importlib.import_module("scripts.bench_ab.strategies")


class Recorder:
    def __init__(self, rows=None, error=None):
        self.calls, self.rows, self.error = [], rows, error

    def __call__(self, dialect, sql):
        self.calls.append((dialect, sql))
        if self.error is not None:
            raise self.error
        return self.rows


def test_the_strategies_and_their_dialects():
    s = strategies()
    assert s.STRATEGIES == ("pg_direct", "oracle_direct", "pg_transpiled")
    assert s.PROMPT_DIALECT == {"pg_direct": "postgres", "oracle_direct": "oracle", "pg_transpiled": "postgres"}
    assert s.EXEC_DIALECT == {"pg_direct": "postgres", "oracle_direct": "oracle", "pg_transpiled": "oracle"}


def test_evaluation_is_a_frozen_dataclass_with_the_documented_fields():
    ev = strategies().Evaluation
    assert dataclasses.is_dataclass(ev)
    assert {f.name for f in dataclasses.fields(ev)} == {"status", "strict", "relaxed", "final_sql", "error", "error_code"}
    assert ev.__dataclass_params__.frozen


def test_transpile_turns_limit_into_fetch_first():
    sql = strategies().transpile("SELECT * FROM customers LIMIT 5")
    assert "FETCH FIRST 5 ROWS ONLY" in sql.upper() and "LIMIT" not in sql.upper()


def test_pg_direct_correct():
    executor = Recorder(rows=[{"count": 300}])
    ev = strategies().evaluate_sql("pg_direct", "SELECT COUNT(*) FROM customers", [(300,)], False, executor)
    assert (ev.status, ev.strict, ev.relaxed) == ("correct", True, True)
    assert executor.calls[0][0] == "postgres" and "LIMIT 100" in executor.calls[0][1]
    assert ev.final_sql == executor.calls[0][1]


def test_a_wrong_result_is_wrong():
    ev = strategies().evaluate_sql("pg_direct", "SELECT COUNT(*) FROM customers", [(300,)], False, Recorder(rows=[{"count": 301}]))
    assert (ev.status, ev.strict, ev.relaxed) == ("wrong", False, False)


def test_extra_columns_are_wrong_when_strict_but_right_when_relaxed():
    rows = [{"payment_method": "credit_card", "n": 515}]
    ev = strategies().evaluate_sql("pg_direct", "SELECT payment_method, COUNT(*) AS n FROM payments GROUP BY payment_method", [("credit_card",)], False, Recorder(rows=rows))
    assert (ev.status, ev.strict, ev.relaxed) == ("wrong", False, True)


def test_the_firewall_rejection_never_reaches_the_database():
    executor = Recorder(rows=[])
    ev = strategies().evaluate_sql("pg_direct", "DROP TABLE customers", [(1,)], False, executor)
    assert ev.status == "firewall_rejected" and ev.error and not ev.strict
    assert executor.calls == []


@pytest.mark.parametrize("raw", [None, "", "   \n"])
@pytest.mark.parametrize("strategy", ["pg_direct", "oracle_direct", "pg_transpiled"])
def test_a_missing_generation_is_a_generation_error(strategy, raw):
    executor = Recorder(rows=[])
    ev = strategies().evaluate_sql(strategy, raw, [(1,)], False, executor)
    assert ev.status == "generation_error" and not ev.strict and executor.calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (QueryExecutionError("No se pudo ejecutar la consulta: ORA-00942: table or view does not exist"), "ORA-00942"),
        (QueryExecutionError("No se pudo ejecutar la consulta: ORA-00904: \"X\": invalid identifier"), "ORA-00904"),
        (QueryExecutionError("No se pudo ejecutar la consulta: (psycopg2.errors.UndefinedColumn) column x does not exist"), "UndefinedColumn"),
        (QueryTimeoutError("La consulta tardó demasiado, intenta ser más específico."), "TIMEOUT"),
        (DatabaseUnavailableError("Base de datos no disponible."), "UNAVAILABLE"),
        (QueryExecutionError("No se pudo ejecutar la consulta: algo raro"), None),
    ],
)
def test_execution_errors_are_classified_by_code(error, code):
    ev = strategies().evaluate_sql("oracle_direct", "SELECT COUNT(*) FROM customers", [(300,)], False, Recorder(error=error))
    assert ev.status == "execution_error" and ev.error_code == code and ev.error


def test_oracle_direct_validates_with_the_oracle_firewall_and_executes_on_oracle():
    executor = Recorder(rows=[{"count": 300}])
    ev = strategies().evaluate_sql("oracle_direct", "SELECT COUNT(*) FROM customers", [(300,)], False, executor)
    assert ev.status == "correct"
    assert executor.calls[0][0] == "oracle" and "FETCH FIRST 100 ROWS ONLY" in executor.calls[0][1]
    rejected = strategies().evaluate_sql("oracle_direct", "SELECT UTL_INADDR.GET_HOST_NAME FROM customers", [(1,)], False, Recorder(rows=[]))
    assert rejected.status == "firewall_rejected"


def test_oracle_direct_accepts_the_schema_qualified_owner():
    ev = strategies().evaluate_sql("oracle_direct", "SELECT COUNT(*) FROM sales.customers", [(300,)], False, Recorder(rows=[{"n": 300}]))
    assert ev.status == "correct"


def test_pg_transpiled_transpiles_then_executes_on_oracle():
    executor = Recorder(rows=[{"payment_method": "credit_card"}])
    raw = "SELECT payment_method FROM payments GROUP BY payment_method ORDER BY COUNT(*) DESC LIMIT 1"
    ev = strategies().evaluate_sql("pg_transpiled", raw, [("credit_card",)], False, executor)
    assert ev.status == "correct"
    dialect, sql = executor.calls[0]
    assert dialect == "oracle" and "LIMIT" not in sql.upper() and "FETCH" in sql.upper()
    assert ev.final_sql == sql


def test_pg_transpiled_reports_a_transpile_failure_without_executing():
    executor = Recorder(rows=[])
    ev = strategies().evaluate_sql("pg_transpiled", "SELECT * FROM (", [(1,)], False, executor)
    assert ev.status == "execution_error" and ev.error_code == "TRANSPILE" and executor.calls == []


def test_pg_transpiled_still_applies_the_firewall():
    executor = Recorder(rows=[])
    ev = strategies().evaluate_sql("pg_transpiled", "DROP TABLE customers", [(1,)], False, executor)
    assert ev.status == "firewall_rejected" and executor.calls == []


def test_an_unknown_strategy_is_refused():
    with pytest.raises(ValueError):
        strategies().evaluate_sql("magia", "SELECT 1", [(1,)], False, Recorder(rows=[]))


def test_a_postgres_error_code_comes_from_the_chained_driver_exception():
    class UndefinedColumn(Exception):  # imita psycopg2.errors.UndefinedColumn
        pass

    error = QueryExecutionError('No se pudo ejecutar la consulta: column "x" does not exist')
    error.__cause__ = DatabaseError("SELECT x FROM customers", {}, UndefinedColumn('column "x" does not exist'))
    ev = strategies().evaluate_sql("pg_direct", "SELECT COUNT(*) FROM customers", [(300,)], False, Recorder(error=error))
    assert ev.status == "execution_error" and ev.error_code == "UndefinedColumn"
