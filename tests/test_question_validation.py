"""Tests de aceptación de la validación de `question` en POST /query (ver SPEC.md).

Los escribió el checker (Claude) antes de la implementación; el maker (agy) no los modifica.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.retrieval import RetrievedSchema
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def deps():
    """Sustituye retrieval, LLM y base de datos; devuelve los mocks para inspeccionar las llamadas."""
    with patch(
        "app.api.routes.retrieve_relevant_schema", return_value=RetrievedSchema(context="", best_distance=0.1)
    ) as retrieve, \
         patch("app.api.routes.generate_sql", return_value="SELECT 1") as generate, \
         patch("app.api.routes.execute_select", return_value=[{"x": 1}]) as execute:
        yield {"retrieve": retrieve, "generate": generate, "execute": execute}


def _nada_llamado(deps):
    return all(m.call_count == 0 for m in deps.values())


# Criterio 1
@pytest.mark.parametrize("question", ["", "   ", "\n\t "])
def test_vacia_o_solo_espacios_da_422_sin_llamar_a_nada(client, deps, question):
    response = client.post("/query", json={"question": question})
    assert response.status_code == 422
    assert _nada_llamado(deps)


# Criterio 2
def test_demasiado_larga_da_422_sin_llamar_a_nada(client, deps):
    response = client.post("/query", json={"question": "a" * 501})
    assert response.status_code == 422
    assert _nada_llamado(deps)


# Criterio 3
def test_justo_en_el_limite_es_aceptada(client, deps):
    response = client.post("/query", json={"question": "a" * 500})
    assert response.status_code == 200
    assert deps["execute"].call_count == 1


# Criterio 4
def test_se_recorta_antes_de_usarla(client, deps):
    response = client.post("/query", json={"question": "  total de ventas  "})
    assert response.status_code == 200
    assert deps["retrieve"].call_args.args[0] == "total de ventas"
    assert deps["generate"].call_args.args[0] == "total de ventas"


# Criterio 5
def test_limite_por_defecto_es_500():
    assert settings.max_question_chars == 500


def test_limite_configurable_se_lee_en_cada_peticion(client, deps, monkeypatch):
    monkeypatch.setattr(settings, "max_question_chars", 10)
    assert client.post("/query", json={"question": "a" * 11}).status_code == 422
    assert client.post("/query", json={"question": "a" * 10}).status_code == 200


# Criterio 6
def test_limite_cuenta_despues_de_recortar(client, deps):
    response = client.post("/query", json={"question": "   " + "a" * 500 + "   "})
    assert response.status_code == 200
