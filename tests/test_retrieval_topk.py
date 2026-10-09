"""Pruebas del parámetro top_k en retrieval y su clave de caché."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.retrieval import retrieve_relevant_schema


@pytest.fixture(autouse=True)
def reset_retrieval_cache():
    retrieve_relevant_schema.cache_clear()
    yield
    retrieve_relevant_schema.cache_clear()


def _mock_retrieval_rows(mock_conn):
    mock_conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "object_name": "invoices",
            "object_type": "table",
            "description": "Tabla de facturas del sistema",
        }
    ]


def test_retrieve_relevant_schema_passes_requested_top_k():
    with patch("app.core.retrieval.embed_text") as mock_embed, patch(
        "app.core.retrieval._engine"
    ) as mock_engine:
        mock_embed.return_value = [0.05] * 384
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        _mock_retrieval_rows(mock_conn)

        retrieve_relevant_schema("pregunta", top_k=2)

        assert mock_conn.execute.call_args[0][1]["top_k"] == 2


def test_retrieve_relevant_schema_uses_default_top_k():
    with patch("app.core.retrieval.embed_text") as mock_embed, patch(
        "app.core.retrieval._engine"
    ) as mock_engine:
        mock_embed.return_value = [0.05] * 384
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        _mock_retrieval_rows(mock_conn)

        retrieve_relevant_schema("pregunta")

        assert mock_conn.execute.call_args[0][1]["top_k"] == 4


def test_retrieve_relevant_schema_top_k_values_have_distinct_cache_keys():
    with patch("app.core.retrieval.embed_text") as mock_embed, patch(
        "app.core.retrieval._engine"
    ) as mock_engine:
        mock_embed.return_value = [0.05] * 384
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        _mock_retrieval_rows(mock_conn)

        retrieve_relevant_schema("pregunta", top_k=2)
        retrieve_relevant_schema("pregunta", top_k=3)

        assert retrieve_relevant_schema.cache_info().misses == 2
        assert mock_embed.call_count == 2
