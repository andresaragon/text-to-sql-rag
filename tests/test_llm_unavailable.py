"""El endpoint traduce fallos de conexión con Ollama a respuestas 503."""

from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from ollama import ResponseError

from app.core.retrieval import RetrievedSchema
from app.main import app


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.TimeoutException("request timed out"),
        ResponseError("upstream unavailable", 500),
        ConnectionError("connection refused"),
    ],
    ids=["connect", "timeout", "ollama-response", "connection"],
)
def test_query_returns_503_when_llm_is_unavailable(error):
    with patch(
        "app.api.routes.retrieve_relevant_schema",
        return_value=RetrievedSchema(context="schema", best_distance=0.1),
    ), patch("app.api.routes.generate_sql", side_effect=error):
        response = TestClient(app).post("/query", json={"question": "consulta"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Modelo de lenguaje no disponible."}
    assert str(error) not in response.text


def test_query_continues_normally_when_llm_succeeds():
    with patch(
        "app.api.routes.retrieve_relevant_schema",
        return_value=RetrievedSchema(context="schema", best_distance=0.1),
    ), patch("app.api.routes.generate_sql", return_value="SELECT 1"), patch(
        "app.api.routes.execute_select", return_value=[{"?column?": 1}]
    ):
        response = TestClient(app).post("/query", json={"question": "consulta"})

    assert response.status_code == 200
    body = response.json()
    # El firewall inyecta el tope de filas (LIMIT), así que solo se exige el prefijo.
    assert body["sql"].startswith("SELECT 1")
    assert body["rows"] == [{"?column?": 1}]
    assert body["row_count"] == 1
