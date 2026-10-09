"""Pruebas del manejo de errores del endpoint POST /query."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import QueryExecutionError, QueryTimeoutError
from app.core.retrieval import retrieve_relevant_schema
from app.core.sql_generator import generate_sql


@pytest.fixture(autouse=True)
def reset_caches():
    """Limpia las cachés antes y después de cada prueba."""
    retrieve_relevant_schema.cache_clear()
    generate_sql.cache_clear()
    yield
    retrieve_relevant_schema.cache_clear()
    generate_sql.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def _configure_dependencies(mock_embed, mock_engine, mock_client):
    mock_embed.return_value = [0.05] * 384
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.mappings.return_value.all.return_value = []
    mock_client.generate.return_value = {"response": "SELECT 1"}


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (QueryTimeoutError("tardó demasiado"), 504, "tardó demasiado"),
        (QueryExecutionError("columna inexistente"), 400, "columna inexistente"),
    ],
)
def test_query_maps_database_errors(client, error, status_code, detail):
    with patch("app.core.retrieval.embed_text") as mock_embed, \
         patch("app.core.retrieval._engine") as mock_engine, \
         patch("app.core.sql_generator._client") as mock_client, \
         patch("app.api.routes.retrieve_relevant_schema", return_value=""), \
         patch("app.api.routes.generate_sql", return_value="SELECT 1"), \
         patch("app.api.routes.execute_select", side_effect=error):
        _configure_dependencies(mock_embed, mock_engine, mock_client)

        response = client.post("/query", json={"question": "consulta"})

    assert response.status_code == status_code
    assert detail in response.json()["detail"]


def test_query_rejects_unsafe_sql_without_executing(client):
    with patch("app.core.retrieval.embed_text") as mock_embed, \
         patch("app.core.retrieval._engine") as mock_engine, \
         patch("app.core.sql_generator._client") as mock_client, \
         patch("app.api.routes.retrieve_relevant_schema", return_value=""), \
         patch("app.api.routes.generate_sql", return_value="DROP TABLE t"), \
         patch("app.api.routes.execute_select") as mock_execute:
        _configure_dependencies(mock_embed, mock_engine, mock_client)
        mock_client.generate.return_value = {"response": "DROP TABLE t"}

        response = client.post("/query", json={"question": "borra la tabla"})

    assert response.status_code == 400
    assert mock_execute.call_count == 0
