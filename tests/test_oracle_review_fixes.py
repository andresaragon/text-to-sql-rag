"""Pruebas para las correcciones de la revisión ciclo 1 (B1 y B2)."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.config import settings
from app.core import db, sql_generator
from scripts.index_schema import load_schema_fragments


# ------------------------------------------------------------------ B1: propagación de errores
def test_execute_select_propagates_pool_timeout_error(monkeypatch):
    """El TimeoutError del pool debe propagarse sin ser atrapado como QueryExecutionError."""
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    monkeypatch.setattr(
        settings, "target_database_url", "oracle+oracledb://u:p@h:1521/?service_name=X"
    )
    monkeypatch.setattr(settings, "allowed_schema", "SALES")
    db.reset_target_engine()

    fake_engine = MagicMock()
    fake_engine.connect.side_effect = PoolTimeoutError(
        "QueuePool limit of size 5 overflow 10 reached"
    )

    with patch("app.core.db._target_engine", return_value=fake_engine), pytest.raises(
        PoolTimeoutError
    ):
        db.execute_select("SELECT 1 FROM dual")


def test_execute_select_propagates_invalid_schema_value_error(monkeypatch):
    """Un allowed_schema inválido debe lanzar ValueError y no convertirse en QueryExecutionError."""
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    monkeypatch.setattr(settings, "allowed_schema", "SALES; DROP TABLE customers")
    db.reset_target_engine()

    with pytest.raises(ValueError):
        db.execute_select("SELECT 1 FROM dual")


# ------------------------------------------------------- B2: normalización de mayúsculas/minúsculas
@pytest.mark.parametrize("dialect", ["Oracle", "ORACLE", "oracle", " oRaCLE "])
def test_dialect_case_insensitivity_in_build_prompt(monkeypatch, dialect):
    monkeypatch.setattr(settings, "target_dialect", dialect)
    prompt = sql_generator.build_prompt("¿Cuántos clientes?", "ctx")
    assert "FETCH FIRST" in prompt
    assert "Oracle" in prompt

    # También cuando se pasa explícitamente como argumento
    prompt_arg = sql_generator.build_prompt("¿Cuántos clientes?", "ctx", dialect=dialect)
    assert "FETCH FIRST" in prompt_arg
    assert "Oracle" in prompt_arg


@pytest.mark.parametrize("dialect", ["Oracle", "ORACLE", "oracle", " oRaCLE "])
def test_dialect_case_insensitivity_in_load_schema_fragments(monkeypatch, dialect):
    monkeypatch.setattr(settings, "target_dialect", dialect)
    fragments = load_schema_fragments()
    tables = {f["object_name"] for f in fragments if f["object_type"] == "table"}
    assert tables == {"customers", "invoices", "payments", "collection_actions"}
    # Verifica que no contenga Postgres-isms (leyó tables_oracle.md)
    for f in fragments:
        assert "::" not in f["description"]

    # También pasando el argumento
    fragments_arg = load_schema_fragments(dialect=dialect)
    assert {f["object_name"] for f in fragments_arg if f["object_type"] == "table"} == tables


@pytest.mark.parametrize("dialect", ["Oracle", "ORACLE", "oracle", " oRaCLE "])
def test_dialect_case_insensitivity_in_execute_select(monkeypatch, dialect):
    monkeypatch.setattr(settings, "target_dialect", dialect)
    monkeypatch.setattr(
        settings, "target_database_url", "oracle+oracledb://u:p@h:1521/?service_name=X"
    )
    monkeypatch.setattr(settings, "allowed_schema", "SALES")
    db.reset_target_engine()

    class _FakeResult:
        def mappings(self):
            return [{"x": 1}]

    fake_conn = MagicMock()
    fake_conn.execute.return_value = _FakeResult()
    fake_engine = MagicMock()
    fake_engine.connect.return_value.__enter__.return_value = fake_conn

    with patch("app.core.db._target_engine", return_value=fake_engine):
        rows = db.execute_select("SELECT 1 AS x FROM dual")

    assert rows == [{"x": 1}]
    # Verifica que tomó la rama de Oracle (ejecutó SET TRANSACTION READ ONLY)
    fake_conn.exec_driver_sql.assert_called_once_with("SET TRANSACTION READ ONLY")
