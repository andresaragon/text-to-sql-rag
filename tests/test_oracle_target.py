"""Contrato de la ejecución contra Oracle (SPEC.md, CA1 a CA5).

Escritas antes de implementar (rojas por diseño); no se editan para hacerlas pasar.
Sin Docker ni Oracle: lo que necesita una base real vive en tests/integration/.
"""

import os
import re
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import call, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from app.config import settings
from app.core import db, sql_generator
from app.core.db import DatabaseUnavailableError, QueryExecutionError, QueryTimeoutError
from app.core.retrieval import RetrievedSchema
from app.core.safety import UnsafeQueryError, validate_and_prepare
from app.core.sql_generator import PROMPT_TEMPLATE, generate_sql
from app.main import app
from scripts.index_schema import load_schema_fragments

ROOT = Path(__file__).resolve().parents[1]
ORACLE_URL = "oracle+oracledb://app_ro:pw@127.0.0.1:1521/?service_name=FREEPDB1"


# ------------------------------------------------------------------ CA1: configuración
def _config(extra_env: dict, drop=()) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("TARGET_DATABASE_URL", *drop)}
    env.update({"DATABASE_URL": "postgresql://u:p@h:5432/d", **extra_env})
    code = "from app.config import settings; print(settings.database_url); print(settings.target_database_url)"
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


def test_target_url_defaults_to_the_database_url():
    database_url, target = _config({})
    assert target == database_url == "postgresql://u:p@h:5432/d"


def test_target_url_is_taken_from_the_environment():
    database_url, target = _config({"TARGET_DATABASE_URL": ORACLE_URL})
    assert database_url == "postgresql://u:p@h:5432/d"
    assert target == ORACLE_URL


def test_an_empty_target_url_falls_back_to_the_database_url():
    database_url, target = _config({"TARGET_DATABASE_URL": ""})
    assert target == database_url


# ------------------------------------------------------------ CA2: mapeo de errores
class FakeOraError(Exception):
    """Imita la forma de oracledb.Error: args[0] tiene full_code y message."""

    def __init__(self, code, message="boom"):
        super().__init__(types.SimpleNamespace(full_code=code, message=f"{code}: {message}", code=0))

    def __str__(self):
        return self.args[0].message


def wrapped(code, message="boom"):
    return DatabaseError("SELECT 1 FROM dual", {}, FakeOraError(code, message))


TIMEOUT_CODES = ["DPY-4024"]
UNAVAILABLE_CODES = [
    "ORA-01017", "ORA-01033", "ORA-01034", "ORA-01089", "ORA-03113", "ORA-03114", "ORA-03135",
    "ORA-12154", "ORA-12170", "ORA-12514", "ORA-12516", "ORA-12519", "ORA-12537", "ORA-12541",
    "DPY-6005", "DPY-6001", "DPY-6999", "DPY-4011",
]  # fmt: skip
EXECUTION_CODES = [
    "ORA-00942", "ORA-00904", "ORA-00900", "ORA-00933", "ORA-03047", "ORA-03162", "ORA-01476",
    "ORA-01722", "ORA-01456", "ORA-30009", "ORA-99999", "DPY-9999", None,
]  # fmt: skip


@pytest.mark.parametrize("make", [wrapped, FakeOraError], ids=["sqlalchemy", "driver"])
@pytest.mark.parametrize("code", TIMEOUT_CODES)
def test_call_timeout_maps_to_query_timeout(make, code):
    err = db.map_oracle_error(make(code))
    assert isinstance(err, QueryTimeoutError)
    assert str(err) == "La consulta tardó demasiado, intenta ser más específico."


@pytest.mark.parametrize("make", [wrapped, FakeOraError], ids=["sqlalchemy", "driver"])
@pytest.mark.parametrize("code", UNAVAILABLE_CODES)
def test_connection_problems_map_to_database_unavailable(make, code):
    err = db.map_oracle_error(make(code, "host 10.0.0.9 puerto 1521"))
    assert isinstance(err, DatabaseUnavailableError)
    assert str(err) == "Base de datos no disponible."  # sin host, puerto ni código


@pytest.mark.parametrize("make", [wrapped, FakeOraError], ids=["sqlalchemy", "driver"])
@pytest.mark.parametrize("code", EXECUTION_CODES)
def test_everything_else_maps_to_query_execution_error(make, code):
    err = db.map_oracle_error(make(code, "detalle"))
    assert isinstance(err, QueryExecutionError)
    assert str(err).startswith("No se pudo ejecutar la consulta: ")
    assert "detalle" in str(err)


def test_an_error_without_an_oracle_code_is_an_execution_error():
    assert isinstance(db.map_oracle_error(Exception("boom")), QueryExecutionError)


# ----------------------------------------------- CA3: ejecución en Oracle (con mocks)
class _Tx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class _Conn(_Tx):
    def __init__(self, script):
        self.script, self.calls = script, []

    def begin(self):
        return _Tx()

    def exec_driver_sql(self, sql, *args, **kwargs):
        self.calls.append(("driver", sql))

    def execute(self, clause, *args, **kwargs):
        self.calls.append(("execute", str(clause)))
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Engine:
    def __init__(self, script, connect_error=None):
        self.conn, self.connects, self.connect_error = _Conn(script), 0, connect_error

    def connect(self):
        self.connects += 1
        if self.connect_error is not None:
            raise self.connect_error
        return self.conn


@pytest.fixture
def oracle_mode(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    monkeypatch.setattr(settings, "target_database_url", ORACLE_URL)
    monkeypatch.setattr(settings, "allowed_schema", "SALES")
    db.reset_target_engine()
    yield
    db.reset_target_engine()


def test_read_only_transaction_comes_first_and_no_statement_timeout(oracle_mode):
    engine = _Engine([_Result([{"n": 1}])])
    with patch("app.core.db._target_engine", return_value=engine):
        rows = db.execute_select("SELECT COUNT(*) AS n FROM customers")
    assert rows == [{"n": 1}]
    kinds = [kind for kind, _ in engine.conn.calls]
    assert kinds[0] == "driver"
    assert engine.conn.calls[0][1].strip().upper() == "SET TRANSACTION READ ONLY"
    assert engine.conn.calls[1] == ("execute", "SELECT COUNT(*) AS n FROM customers")
    assert not any("statement_timeout" in sql for _, sql in engine.conn.calls)


def test_ora_01466_is_retried_five_times_at_most(oracle_mode):
    engine = _Engine([wrapped("ORA-01466")] * 2 + [_Result([{"n": 7}])])
    with patch("app.core.db._target_engine", return_value=engine), patch("app.core.db.time.sleep") as sleep:
        assert db.execute_select("SELECT 1 AS n FROM dual") == [{"n": 7}]
    assert sleep.call_args_list == [call(1), call(1)]
    assert engine.connects == 3


def test_ora_01466_gives_up_after_five_retries(oracle_mode):
    engine = _Engine([wrapped("ORA-01466")] * 10)
    with (
        patch("app.core.db._target_engine", return_value=engine),
        patch("app.core.db.time.sleep") as sleep,
        pytest.raises(QueryExecutionError),
    ):
        db.execute_select("SELECT 1 FROM dual")
    assert sleep.call_count == 5
    assert engine.connects == 6


def test_timeout_during_execution_is_a_query_timeout(oracle_mode):
    engine = _Engine([wrapped("DPY-4024")])
    with patch("app.core.db._target_engine", return_value=engine), pytest.raises(QueryTimeoutError):
        db.execute_select("SELECT 1 FROM dual")


@pytest.mark.parametrize("code", ["DPY-6005", "ORA-01017"])
def test_connect_errors_are_database_unavailable(oracle_mode, code):
    engine = _Engine([], connect_error=wrapped(code, "secreto-host"))
    with patch("app.core.db._target_engine", return_value=engine), pytest.raises(DatabaseUnavailableError) as info:
        db.execute_select("SELECT 1 FROM dual")
    assert "secreto-host" not in str(info.value)


def test_unknown_errors_during_execution_become_execution_errors(oracle_mode):
    engine = _Engine([wrapped("ORA-00942", "tabla no existe")])
    with patch("app.core.db._target_engine", return_value=engine), pytest.raises(QueryExecutionError, match="ORA-00942"):
        db.execute_select("SELECT * FROM no_existe")


def test_postgres_target_is_the_existing_engine(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "postgres")
    monkeypatch.setattr(settings, "target_database_url", settings.database_url)
    db.reset_target_engine()
    try:
        assert db._target_engine() is db._engine
    finally:
        db.reset_target_engine()


def test_oracle_engine_is_built_from_the_target_url(oracle_mode):
    engine = db._target_engine()
    assert engine.dialect.name == "oracle"
    assert engine.pool.size() == settings.db_pool_size
    assert db._target_engine() is engine  # cacheado
    db.reset_target_engine()
    assert db._target_engine() is not engine


@pytest.mark.parametrize("schema", ["SALES; DROP USER x", "1SALES", "SA LES", "", "SALES--"])
def test_an_invalid_schema_name_is_refused_when_building_the_oracle_engine(oracle_mode, monkeypatch, schema):
    monkeypatch.setattr(settings, "allowed_schema", schema)
    db.reset_target_engine()
    with pytest.raises(ValueError):
        db._target_engine()


def test_the_default_public_schema_is_not_an_oracle_current_schema(oracle_mode, monkeypatch):
    monkeypatch.setattr(settings, "allowed_schema", "public")
    db.reset_target_engine()
    assert db._target_engine().dialect.name == "oracle"  # no lanza


# ------------------------------------------------------------------- CA4: el dialecto
def test_the_postgres_prompt_is_unchanged():
    assert sql_generator.build_prompt("q", "ctx", "postgres") == PROMPT_TEMPLATE.format(schema_context="ctx", question="q")


def test_the_oracle_prompt_asks_for_oracle_sql():
    prompt = sql_generator.build_prompt("¿Cuántos clientes?", "ctx", "oracle")
    for needle in ("Oracle", "FETCH FIRST", "SYSDATE", "TRUNC", "LISTAGG", "LIMIT", "::", "ctx", "¿Cuántos clientes?", "SELECT"):
        assert needle in prompt, needle
    assert "PostgreSQL" not in prompt and "Postgres" not in prompt


def test_the_prompt_dialect_defaults_to_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    assert sql_generator.build_prompt("q", "c") == sql_generator.build_prompt("q", "c", "oracle")


def test_generate_sql_sends_the_dialect_prompt():
    generate_sql.cache_clear()
    try:
        with patch("app.core.sql_generator._client") as client:
            client.generate.return_value = {"response": "SELECT 1"}
            generate_sql("pregunta uno", "ctx", "oracle")
            assert "FETCH FIRST" in client.generate.call_args.kwargs["prompt"]
            generate_sql("pregunta dos", "ctx", "postgres")
            assert "FETCH FIRST" not in client.generate.call_args.kwargs["prompt"]
    finally:
        generate_sql.cache_clear()


def test_the_route_passes_the_target_dialect_and_uses_fetch_first(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    monkeypatch.setattr(settings, "allowed_schema", "SALES")
    with (
        patch("app.api.routes.retrieve_relevant_schema", return_value=RetrievedSchema(context="c", best_distance=0.1)),
        patch("app.api.routes.generate_sql", return_value="SELECT * FROM customers") as generate,
        patch("app.api.routes.execute_select", return_value=[]) as execute,
    ):
        response = TestClient(app).post("/query", json={"question": "hola"})
    assert response.status_code == 200
    assert "oracle" in [*generate.call_args.args, *generate.call_args.kwargs.values()]
    assert re.search(r"FETCH FIRST 100 ROWS ONLY\s*$", execute.call_args.args[0])


# -------------------------------------------------------------- CA5: documentos de esquema
POSTGRES_ISMS = [
    r"::", r"(?i)\bILIKE\b", r"(?i)\bNOW\(\)", r"(?i)interval\s+'[^']*days?'", r"(?i)\bLIMIT\b\s+\d",
    r"(?i)GROUP BY\s+\d", r"(?i)STRING_AGG", r"(?i)date_trunc",
]  # fmt: skip


def _example_sql(fragment) -> str:
    return re.search(r"```sql\s*(.*?)```", fragment["description"], re.DOTALL).group(1).strip()


def test_default_fragments_are_the_postgres_ones():
    assert load_schema_fragments() == load_schema_fragments("postgres")


def test_oracle_fragments_describe_the_four_tables_and_have_examples():
    fragments = load_schema_fragments("oracle")
    tables = {f["object_name"] for f in fragments if f["object_type"] == "table"}
    assert tables == {"customers", "invoices", "payments", "collection_actions"}
    assert len([f for f in fragments if f["object_type"] == "example_query"]) >= 6


def test_the_oracle_documents_have_no_postgres_constructs():
    for fragment in load_schema_fragments("oracle"):
        for pattern in POSTGRES_ISMS:
            assert not re.search(pattern, fragment["description"]), (fragment["object_name"], pattern)


def test_every_oracle_example_passes_the_oracle_firewall():
    examples = [f for f in load_schema_fragments("oracle") if f["object_type"] == "example_query"]
    assert examples
    for fragment in examples:
        safe = validate_and_prepare(_example_sql(fragment), 100, dialect="oracle", allowed_schema="SALES")
        assert re.search(r"FETCH (FIRST|NEXT) \d+ ROWS ONLY\s*$", safe), (fragment["object_name"], safe)


def test_clear_schema_embeddings_uses_the_metadata_engine_and_returns_the_count():
    class _Meta(_Tx):
        def __init__(self):
            self.statements = []

        def execute(self, clause, *args, **kwargs):
            self.statements.append(str(clause))
            return types.SimpleNamespace(rowcount=3)

    meta = _Meta()
    fake_engine = types.SimpleNamespace(begin=lambda: meta)
    with patch("app.core.db._engine", fake_engine):
        assert db.clear_schema_embeddings() == 3
    assert len(meta.statements) == 1
    assert re.fullmatch(r"(?is)\s*DELETE FROM schema_embeddings\s*;?\s*", meta.statements[0])


def test_the_indexer_does_not_send_its_delete_to_the_target_database(monkeypatch):
    import scripts.index_schema as index

    monkeypatch.setattr(settings, "target_dialect", "oracle")
    fragments = load_schema_fragments("oracle")
    with (
        patch.object(index, "embed_batch", return_value=[[0.0]] * len(fragments)),
        patch.object(index, "save_schema_embedding") as save,
        patch.object(index, "clear_schema_embeddings", return_value=0, create=True) as clear,
        patch.object(index, "execute_select", side_effect=AssertionError("usa clear_schema_embeddings"), create=True),
    ):
        index.main()
    clear.assert_called_once()
    assert save.call_count == len(fragments)
    assert {c.kwargs["object_name"] for c in save.call_args_list} >= {"customers", "invoices", "payments"}


# ----------------------------------- el firewall rechaza la matriz de ataques medida en Oracle
ATTACKS = [
    "SELECT UTL_INADDR.GET_HOST_NAME FROM customers",
    "SELECT SYS_CONTEXT('USERENV','IP_ADDRESS') FROM customers",
    "SELECT DBMS_LOB.SUBSTR(DBMS_XMLGEN.GETXML('select username from all_users'), 200, 1) FROM customers",
    "SELECT COUNT(*) FROM all_users",
    "SELECT ORA_DATABASE_NAME FROM customers",
    "SELECT USER FROM customers",
    "SELECT DBMS_RANDOM.VALUE FROM customers",
]


@pytest.mark.parametrize("sql", ATTACKS)
def test_the_firewall_rejects_the_measured_attacks(sql):
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare(sql, 100, dialect="oracle", allowed_schema="SALES")

