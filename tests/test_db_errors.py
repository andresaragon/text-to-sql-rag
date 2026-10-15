"""Clasificación de errores de Postgres en execute_select: base caída (503),
timeout (504) o error de la consulta (400)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core import db
from app.core.db import (
    DatabaseUnavailableError,
    QueryExecutionError,
    QueryTimeoutError,
    execute_select,
)
from app.core.retrieval import RetrievedSchema
from app.main import app


def _operational_error(pgcode, connection_invalidated=False):
    return OperationalError(
        "SELECT 1",
        {},
        MagicMock(pgcode=pgcode),
        connection_invalidated=connection_invalidated,
    )


def _execute_raising(error):
    with patch("app.core.db._engine") as mock_engine:
        mock_engine.connect.side_effect = error
        execute_select("SELECT 1")


@pytest.mark.parametrize(
    "pgcode",
    [None, "08006", "08001", "57P01", "57P02", "57P03", "53300"],
)
def test_unavailable_sqlstates_raise_database_unavailable(pgcode):
    with pytest.raises(DatabaseUnavailableError):
        _execute_raising(_operational_error(pgcode))


def test_invalidated_connection_is_unavailable_whatever_the_sqlstate():
    with pytest.raises(DatabaseUnavailableError):
        _execute_raising(_operational_error("XX000", connection_invalidated=True))


def test_statement_timeout_is_still_a_query_timeout():
    with pytest.raises(QueryTimeoutError):
        _execute_raising(_operational_error("57014"))


def test_other_operational_errors_are_query_errors():
    # 55P03 = lock_not_available: la base responde, falla la consulta.
    with pytest.raises(QueryExecutionError):
        _execute_raising(_operational_error("55P03"))


def test_sql_errors_are_query_errors():
    error = ProgrammingError("SELECT x", {}, MagicMock(pgcode="42703"))
    with pytest.raises(QueryExecutionError):
        _execute_raising(error)


def test_real_psycopg2_against_closed_port_is_unavailable():
    engine = create_engine(
        "postgresql://u:p@127.0.0.1:1/x", connect_args={"connect_timeout": 2}
    )
    try:
        with patch.object(db, "_engine", engine), \
             pytest.raises(DatabaseUnavailableError):
            execute_select("SELECT 1")
    finally:
        engine.dispose()


def test_query_endpoint_returns_503_when_postgres_goes_down():
    with patch(
        "app.api.routes.retrieve_relevant_schema",
        return_value=RetrievedSchema(context="", best_distance=0.1),
    ), patch("app.api.routes.generate_sql", return_value="SELECT 1"), \
         patch(
             "app.api.routes.execute_select",
             side_effect=DatabaseUnavailableError("Base de datos no disponible."),
         ):
        res = TestClient(app).post("/query", json={"question": "consulta"})

    assert res.status_code == 503
    assert res.json() == {"detail": "Base de datos no disponible."}
