"""
Tests para la capa de caching en memoria de retrieval y generación de SQL.

Verifica que:
1. `retrieve_relevant_schema` ejecute embeddings y búsqueda en DB una sola vez
   para preguntas repetidas (cache hit).
2. `generate_sql` ejecute la llamada al LLM (Ollama) una sola vez para
   preguntas y esquemas repetidos (cache hit).
3. En el endpoint `POST /query`, las etapas costosas (retrieval + LLM) se
   reutilizan del cache en preguntas repetidas, pero `execute_select` se
   ejecuta SIEMPRE (no se cachea, garantizando datos frescos de la DB).
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.retrieval import retrieve_relevant_schema
from app.core.sql_generator import generate_sql


@pytest.fixture(autouse=True)
def reset_caches():
    """Limpia la memoria caché antes y después de cada prueba para aislamiento."""
    retrieve_relevant_schema.cache_clear()
    generate_sql.cache_clear()
    yield
    retrieve_relevant_schema.cache_clear()
    generate_sql.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_retrieve_relevant_schema_caches_for_repeated_question():
    """Comprueba que llamar dos veces con la misma pregunta a retrieve_relevant_schema
    solo ejecute embeddings y consulta pgvector una vez."""
    question = "¿cuántas facturas están vencidas?"

    with patch("app.core.retrieval.embed_text") as mock_embed, \
         patch("app.core.retrieval._engine") as mock_engine:

        mock_embed.return_value = [0.05] * 384
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.mappings.return_value.all.return_value = [
            {
                "object_name": "invoices",
                "object_type": "table",
                "description": "Tabla de facturas del sistema",
            }
        ]

        result1 = retrieve_relevant_schema(question)
        result2 = retrieve_relevant_schema(question)

        assert result1 == result2
        assert "### table: invoices" in result1
        assert mock_embed.call_count == 1
        assert mock_engine.connect.call_count == 1

        info = retrieve_relevant_schema.cache_info()
        assert info.hits == 1
        assert info.misses == 1


def test_retrieve_relevant_schema_miss_for_different_questions():
    """Preguntas distintas deben provocar un cache miss y ejecutar retrieval nuevamente."""
    q1 = "¿cuántas facturas hay?"
    q2 = "¿quiénes son los clientes con más deuda?"

    with patch("app.core.retrieval.embed_text") as mock_embed, \
         patch("app.core.retrieval._engine") as mock_engine:

        mock_embed.return_value = [0.05] * 384
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.mappings.return_value.all.return_value = [
            {"object_name": "invoices", "object_type": "table", "description": "desc"}
        ]

        retrieve_relevant_schema(q1)
        retrieve_relevant_schema(q2)

        assert mock_embed.call_count == 2
        assert mock_engine.connect.call_count == 2

        info = retrieve_relevant_schema.cache_info()
        assert info.hits == 0
        assert info.misses == 2


def test_generate_sql_caches_for_repeated_input():
    """Comprueba que generate_sql con mismos argumentos consulte al LLM una sola vez."""
    question = "¿cuántas facturas están vencidas?"
    schema_context = "### table: invoices\nTabla de facturas"

    with patch("app.core.sql_generator._client") as mock_client:
        mock_client.generate.return_value = {
            "response": "SELECT COUNT(*) FROM invoices WHERE status = 'overdue';"
        }

        sql1 = generate_sql(question, schema_context)
        sql2 = generate_sql(question, schema_context)

        assert sql1 == sql2
        assert sql1 == "SELECT COUNT(*) FROM invoices WHERE status = 'overdue';"
        assert mock_client.generate.call_count == 1

        info = generate_sql.cache_info()
        assert info.hits == 1
        assert info.misses == 1


def test_query_endpoint_caches_retrieval_and_sql_but_never_db_execution(client):
    """
    Test de integración del endpoint POST /query:
    Al repetir la misma pregunta:
    - retrieval (embed_text y query a schema_embeddings) se ejecuta 1 sola vez.
    - generate_sql (llamada a Ollama) se ejecuta 1 sola vez.
    - execute_select se ejecuta 2 VECES (nunca se cachea la consulta a la DB).
    """
    question = "¿cuántas facturas están vencidas?"

    with patch("app.core.retrieval.embed_text") as mock_embed, \
         patch("app.core.retrieval._engine") as mock_engine, \
         patch("app.core.sql_generator._client") as mock_client, \
         patch("app.api.routes.execute_select") as mock_exec:

        mock_embed.return_value = [0.05] * 384
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.mappings.return_value.all.return_value = [
            {
                "object_name": "invoices",
                "object_type": "table",
                "description": "Tabla de facturas",
            }
        ]

        mock_client.generate.return_value = {
            "response": "SELECT count(*) FROM invoices WHERE status = 'overdue';"
        }
        # Simulamos resultados que podrían cambiar entre llamadas
        mock_exec.side_effect = [
            [{"count": 5}],
            [{"count": 6}],  # Segunda llamada devuelve datos frescos
        ]

        # Primera petición
        res1 = client.post("/query", json={"question": question})
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["rows"] == [{"count": 5}]

        # Segunda petición con la misma pregunta exacta
        res2 = client.post("/query", json={"question": question})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["rows"] == [{"count": 6}]

        # Ambas tienen el mismo SQL generado
        assert data1["sql"] == data2["sql"]

        # Verificaciones de llamadas caras vs base de datos:
        # 1. Retrieval (embeddings) ejecutado solo 1 vez
        assert mock_embed.call_count == 1
        assert mock_engine.connect.call_count == 1

        # 2. Generación LLM ejecutado solo 1 vez
        assert mock_client.generate.call_count == 1

        # 3. Ejecución de base de datos ejecutado 2 veces (NUNCA CACHEADO)
        assert mock_exec.call_count == 2
