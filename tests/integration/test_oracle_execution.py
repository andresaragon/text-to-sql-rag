"""Ejecución contra Oracle real (SPEC.md, CA7).

Escritas antes de implementar (rojas por diseño); no se editan para hacerlas pasar.
Solo corren con ORACLE_INTEGRATION=1 (ver tests/run_acceptance.sh).
"""

import re
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.retrieval import RetrievedSchema
from app.core.safety import UnsafeQueryError, validate_and_prepare
from app.main import app
from scripts.index_schema import load_schema_fragments

from .conftest import ENABLED, OWNER_URL, READER_URL

pytestmark = pytest.mark.skipif(not ENABLED, reason="necesita Oracle: bash tests/run_acceptance.sh")

CPU_BOMB = (
    "SELECT COUNT(*) AS n FROM (SELECT LEVEL FROM dual CONNECT BY LEVEL <= 2000) a, "
    "(SELECT LEVEL FROM dual CONNECT BY LEVEL <= 2000) b, "
    "(SELECT LEVEL FROM dual CONNECT BY LEVEL <= 2000) c"
)


def test_unqualified_and_qualified_names_resolve(oracle):
    assert db.execute_select("SELECT COUNT(*) AS n FROM customers") == [{"n": 3}]
    assert db.execute_select("SELECT COUNT(*) AS n FROM sales.invoices") == [{"n": 4}]
    assert db.execute_select("SELECT COUNT(*) AS n FROM payments") == [{"n": 1}]
    assert db.execute_select("SELECT COUNT(*) AS n FROM collection_actions") == [{"n": 3}]


def test_rows_are_dicts_with_lowercase_keys(oracle):
    row = db.execute_select(
        "SELECT customer_id, full_name, created_at FROM customers ORDER BY customer_id FETCH FIRST 1 ROWS ONLY"
    )[0]
    assert set(row) == {"customer_id", "full_name", "created_at"}
    assert row["full_name"] == "Ana Torres"


def test_the_call_timeout_is_a_query_timeout_and_the_pool_recovers(oracle):
    oracle(timeout=2)
    started = time.time()
    with pytest.raises(db.QueryTimeoutError):
        db.execute_select(CPU_BOMB)
    assert time.time() - started < 10
    assert db.execute_select("SELECT 1 AS x FROM dual") == [{"x": 1}]


def test_the_transaction_is_read_only_even_for_the_owner(oracle):
    oracle(url=OWNER_URL, timeout=5)
    with pytest.raises(db.QueryExecutionError, match="ORA-01456"):
        db.execute_select("INSERT INTO customers (full_name, email) VALUES ('x', 'x@x.co')")
    assert db.execute_select("SELECT COUNT(*) AS n FROM customers") == [{"n": 3}]


def test_a_missing_table_is_an_execution_error(oracle):
    with pytest.raises(db.QueryExecutionError, match="ORA-00942"):
        db.execute_select("SELECT * FROM no_existe")


def test_a_wrong_password_is_unavailable_without_leaking_it(oracle):
    oracle(url=READER_URL.replace("app-ro-demo-pw", "clave-mala"))
    with pytest.raises(db.DatabaseUnavailableError) as info:
        db.execute_select("SELECT 1 FROM dual")
    assert "clave-mala" not in str(info.value) and "1521" not in str(info.value)


def test_a_closed_port_is_unavailable_and_fails_fast(oracle):
    oracle(url=READER_URL.replace(":1521/", ":1599/"))
    started = time.time()
    with pytest.raises(db.DatabaseUnavailableError):
        db.execute_select("SELECT 1 FROM dual")
    assert time.time() - started < 20


def _post(sql):
    with (
        patch("app.api.routes.retrieve_relevant_schema", return_value=RetrievedSchema(context="c", best_distance=0.1)),
        patch("app.api.routes.generate_sql", return_value=sql),
    ):
        return TestClient(app).post("/query", json={"question": "pregunta"})


def test_the_api_answers_from_oracle_end_to_end(oracle):
    response = _post("SELECT customer_id, full_name FROM customers ORDER BY customer_id")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["row_count"] == 3
    assert body["rows"][0]["full_name"] == "Ana Torres"
    assert re.search(r"FETCH FIRST 100 ROWS ONLY\s*$", body["sql"])


ATTACKS = [
    "SELECT UTL_INADDR.GET_HOST_NAME FROM customers",
    "SELECT SYS_CONTEXT('USERENV','IP_ADDRESS') FROM customers",
    "SELECT DBMS_LOB.SUBSTR(DBMS_XMLGEN.GETXML('select username from all_users'), 200, 1) FROM customers",
    "SELECT COUNT(*) FROM all_users",
]


@pytest.mark.parametrize("sql", ATTACKS)
def test_the_api_answers_400_to_the_measured_attacks(oracle, sql):
    assert _post(sql).status_code == 400


# Controles: lo que una cuenta de SOLO LECTURA ejecuta en Oracle SIN firewall (medido el 2026-10-23).
CONTROLS = [
    ("IP del cliente con SYS_CONTEXT", "SELECT SYS_CONTEXT('USERENV', 'IP_ADDRESS') AS v FROM dual", lambda v: bool(v)),
    (
        "SQL anidado con DBMS_XMLGEN (esquiva la lista blanca)",
        "SELECT DBMS_LOB.SUBSTR(DBMS_XMLGEN.GETXML('select username from all_users where rownum <= 3'), 300, 1) AS v FROM dual",
        lambda v: "ROWSET" in v and "USERNAME" in v,
    ),
    ("diccionario legible", "SELECT COUNT(*) AS v FROM all_users", lambda v: v > 0),
]


@pytest.mark.parametrize(("name", "sql", "proves"), CONTROLS, ids=[c[0] for c in CONTROLS])
def test_the_attack_works_without_the_firewall_and_is_rejected_with_it(oracle, name, sql, proves):
    assert proves(db.execute_select(sql)[0]["v"]), name
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare(sql, 100, dialect="oracle", allowed_schema="SALES")


def test_every_rag_example_runs_on_oracle(oracle):
    examples = [f for f in load_schema_fragments("oracle") if f["object_type"] == "example_query"]
    assert examples
    for fragment in examples:
        sql = re.search(r"```sql\s*(.*?)```", fragment["description"], re.DOTALL).group(1).strip()
        safe = validate_and_prepare(sql, 100, dialect="oracle", allowed_schema="SALES")
        db.execute_select(safe)  # no debe lanzar
