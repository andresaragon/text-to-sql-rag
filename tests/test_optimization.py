"""
Tests de aceptación de SPEC.md (optimización del pipeline POST /query).

Cada test lleva el criterio que cubre (CA1..CA12). Ninguno necesita
Postgres ni Ollama: la base y el LLM se reemplazan con mocks.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.config import settings
from app.core import db, embeddings, retrieval
from app.core.db import QueryExecutionError, QueryTimeoutError
from app.core.retrieval import RetrievedSchema, retrieve_relevant_schema
from app.core.sql_generator import generate_sql
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[1]

NEW_ENV_VARS = [
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_TIMEOUT_SECONDS",
    "DB_CONNECT_TIMEOUT_SECONDS",
    "MAX_QUESTION_CHARS",
    "MAX_SCHEMA_DISTANCE",
    "WARMUP_ON_STARTUP",
]

GOOD_SQL = "SELECT count(*) FROM invoices WHERE status = 'overdue';"


@pytest.fixture(autouse=True)
def reset_caches():
    retrieve_relevant_schema.cache_clear()
    generate_sql.cache_clear()
    yield
    retrieve_relevant_schema.cache_clear()
    generate_sql.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def _row(name, distance, object_type="table", description="desc"):
    return {
        "object_name": name,
        "object_type": object_type,
        "description": description,
        "distance": distance,
    }


@pytest.fixture
def pipeline():
    """Mocks de embeddings, pgvector, Ollama y execute_select.

    Devuelve un objeto con los mocks; `set_rows` cambia lo que devuelve pgvector.
    """
    with patch("app.core.retrieval.embed_text") as mock_embed, \
         patch("app.core.retrieval._engine") as mock_engine, \
         patch("app.core.sql_generator._client") as mock_client, \
         patch("app.api.routes.execute_select") as mock_exec:
        mock_embed.return_value = [0.05] * 384
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_client.generate.return_value = {"response": GOOD_SQL}
        mock_exec.return_value = [{"count": 5}]

        class P:
            embed = mock_embed
            engine = mock_engine
            llm = mock_client
            exec = mock_exec

            @staticmethod
            def set_rows(rows):
                mock_conn.execute.return_value.mappings.return_value.all.return_value = rows

        P.set_rows([_row("invoices", 0.4)])
        yield P


# --- CA1-CA3: engine único y pool -------------------------------------------


def test_ca1_retrieval_shares_db_engine():
    assert retrieval._engine is db._engine


def test_ca2_pool_is_configured_from_settings():
    pool = db._engine.pool
    assert pool.size() == settings.db_pool_size
    assert pool._max_overflow == settings.db_max_overflow
    assert pool._timeout == settings.db_pool_timeout_seconds
    assert pool._pre_ping is True


def test_ca3_connect_timeout_reaches_psycopg2():
    captured = {}

    class _Stop(Exception):
        pass

    def on_connect(dialect, conn_rec, cargs, cparams):
        captured.update(cparams)
        raise _Stop

    event.listen(db._engine, "do_connect", on_connect)
    try:
        with pytest.raises(_Stop):
            db._engine.connect()
    finally:
        event.remove(db._engine, "do_connect", on_connect)

    assert captured.get("connect_timeout") == settings.db_connect_timeout_seconds


# --- CA4: settings desde el entorno ------------------------------------------


def _settings_in_subprocess(extra_env):
    env = {k: v for k, v in os.environ.items() if k not in NEW_ENV_VARS}
    env.update(extra_env)
    code = (
        "import json; from app.config import settings as s; print(json.dumps({"
        "'db_pool_size': s.db_pool_size, 'db_max_overflow': s.db_max_overflow, "
        "'db_pool_timeout_seconds': s.db_pool_timeout_seconds, "
        "'db_connect_timeout_seconds': s.db_connect_timeout_seconds, "
        "'max_question_chars': s.max_question_chars, "
        "'max_schema_distance': s.max_schema_distance, "
        "'warmup_on_startup': s.warmup_on_startup}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_ca4_settings_defaults():
    assert _settings_in_subprocess({}) == {
        "db_pool_size": 5,
        "db_max_overflow": 10,
        "db_pool_timeout_seconds": 10,
        "db_connect_timeout_seconds": 3,
        "max_question_chars": 500,
        "max_schema_distance": 0.7,
        "warmup_on_startup": True,
    }


def test_ca4_settings_read_from_env():
    values = _settings_in_subprocess(
        {"DB_POOL_SIZE": "7", "MAX_SCHEMA_DISTANCE": "0.55", "WARMUP_ON_STARTUP": "false"}
    )
    assert values["db_pool_size"] == 7
    assert values["max_schema_distance"] == 0.55
    assert values["warmup_on_startup"] is False


def test_ca4_warmup_accepts_zero_as_false():
    assert _settings_in_subprocess({"WARMUP_ON_STARTUP": "0"})["warmup_on_startup"] is False


# --- CA5: errores de infraestructura a HTTP ----------------------------------


def test_ca5_db_down_during_retrieval_returns_503(client, pipeline):
    pipeline.engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, Exception("connection refused")
    )
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 503
    pipeline.llm.generate.assert_not_called()


def test_ca5_pool_exhausted_during_retrieval_returns_503(client, pipeline):
    pipeline.engine.connect.side_effect = PoolTimeoutError("QueuePool limit reached")
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 503
    assert "QueuePool" not in res.text
    pipeline.llm.generate.assert_not_called()


def test_ca5_pool_exhausted_during_execution_returns_503(client, pipeline):
    pipeline.exec.side_effect = PoolTimeoutError("QueuePool limit reached")
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 503
    assert "QueuePool" not in res.text


def test_ca5_query_timeout_returns_504(client, pipeline):
    pipeline.exec.side_effect = QueryTimeoutError("tardó demasiado")
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 504


def test_ca5_query_execution_error_returns_400(client, pipeline):
    pipeline.exec.side_effect = QueryExecutionError("columna inexistente")
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    # 400 y no 422: contrato de PR #4 (tests/test_routes_errors.py), ver SPEC.md.
    assert res.status_code == 400


# --- CA6-CA7: normalización y límites de la pregunta -------------------------


def test_ca6_whitespace_variants_share_cache(client, pipeline):
    normalized = "¿cuántas facturas vencidas?"
    r1 = client.post("/query", json={"question": "  ¿cuántas   facturas\n vencidas? "})
    r2 = client.post("/query", json={"question": normalized})
    assert r1.status_code == 200
    assert r2.status_code == 200

    assert pipeline.embed.call_count == 1
    assert pipeline.embed.call_args.args[0] == normalized
    assert pipeline.llm.generate.call_count == 1
    assert normalized in str(pipeline.llm.generate.call_args)
    assert pipeline.exec.call_count == 2


def test_ca6_case_and_accents_are_preserved(client, pipeline):
    question = "¿Facturas de  José   Pérez?"
    res = client.post("/query", json={"question": question})
    assert res.status_code == 200
    assert pipeline.embed.call_args.args[0] == "¿Facturas de José Pérez?"


def test_ca7_blank_question_rejected_without_embedding(client, pipeline):
    res = client.post("/query", json={"question": "   \n\t "})
    assert res.status_code == 422
    pipeline.embed.assert_not_called()


def test_ca7_too_long_question_rejected_without_embedding(client, pipeline):
    question = "a" * (settings.max_question_chars + 1)
    res = client.post("/query", json={"question": question})
    assert res.status_code == 422
    pipeline.embed.assert_not_called()


def test_ca7_length_is_measured_after_normalization(client, pipeline):
    question = "  " + "a" * settings.max_question_chars + "   "
    res = client.post("/query", json={"question": question})
    assert res.status_code == 200


# --- CA8: contrato de retrieval -----------------------------------------------


def test_ca8_retrieved_schema_has_context_and_best_distance(pipeline):
    pipeline.set_rows([
        _row("invoices", 0.42, description="Tabla de facturas"),
        _row("payments", 0.55, description="Pagos"),
    ])
    result = retrieve_relevant_schema("¿cuántas facturas hay?")

    assert isinstance(result, RetrievedSchema)
    assert result.context == (
        "### table: invoices\nTabla de facturas\n\n### table: payments\nPagos"
    )
    assert result.best_distance == pytest.approx(0.42)
    hash(result)


def test_ca8_best_distance_is_the_minimum_not_the_first(pipeline):
    pipeline.set_rows([_row("payments", 0.6), _row("invoices", 0.3)])
    assert retrieve_relevant_schema("x").best_distance == pytest.approx(0.3)


def test_ca8_no_rows_gives_none_distance(pipeline):
    pipeline.set_rows([])
    result = retrieve_relevant_schema("¿cuántas facturas hay?")
    assert result.best_distance is None


def test_ca8_query_selects_distance(pipeline):
    retrieve_relevant_schema("¿cuántas facturas hay?")
    sql_sent = str(pipeline.engine.connect.return_value.__enter__.return_value
                   .execute.call_args.args[0])
    assert re.search(r"<=>\s*:question_embedding\s+AS\s+distance", sql_sent, re.IGNORECASE)


def test_ca8_retrieval_is_still_cached(pipeline):
    retrieve_relevant_schema("¿cuántas facturas hay?")
    retrieve_relevant_schema("¿cuántas facturas hay?")
    assert pipeline.embed.call_count == 1
    assert retrieve_relevant_schema.cache_info().hits == 1


# --- CA9: rechazo temprano fuera de dominio ----------------------------------


def test_ca9_off_domain_question_skips_llm_and_db(client, pipeline):
    pipeline.set_rows([_row("invoices", 0.85), _row("payments", 0.9)])
    res = client.post("/query", json={"question": "¿cuál es la capital de Francia?"})
    assert res.status_code == 422
    pipeline.llm.generate.assert_not_called()
    pipeline.exec.assert_not_called()


def test_ca9_threshold_is_inclusive(client, pipeline):
    pipeline.set_rows([_row("invoices", 0.5)])
    with patch.object(settings, "max_schema_distance", 0.5):
        res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 200


def test_ca9_threshold_comes_from_settings(client, pipeline):
    pipeline.set_rows([_row("invoices", 0.6)])
    with patch.object(settings, "max_schema_distance", 0.5):
        res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 422
    pipeline.llm.generate.assert_not_called()


def test_ca9_empty_index_returns_503_without_llm(client, pipeline):
    pipeline.set_rows([])
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 503
    pipeline.llm.generate.assert_not_called()


# --- CA10: Server-Timing -----------------------------------------------------


def test_ca10_server_timing_has_all_stages(client, pipeline):
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert res.status_code == 200
    header = res.headers.get("server-timing", "")
    for stage in ("retrieval", "llm", "validate", "db"):
        assert re.search(rf"(^|,)\s*{stage};dur=\d+(\.\d+)?\s*(,|$)", header), header


def test_ca10_response_body_contract_unchanged(client, pipeline):
    res = client.post("/query", json={"question": "¿cuántas facturas hay?"})
    assert set(res.json()) == {"sql", "rows", "row_count"}


# --- CA11: warm-up -----------------------------------------------------------


@pytest.mark.parametrize("enabled, expected_calls", [(True, 1), (False, 0)])
def test_ca11_embedding_model_warmup(enabled, expected_calls):
    embeddings._get_model.cache_clear()
    try:
        with patch("app.core.embeddings.SentenceTransformer") as mock_st, \
             patch.object(settings, "warmup_on_startup", enabled), \
             TestClient(app):
            assert mock_st.call_count == expected_calls
    finally:
        embeddings._get_model.cache_clear()


# --- CA12: documentación -----------------------------------------------------


@pytest.mark.parametrize("readme", ["README.md", "README.es.md", ".env.example"])
def test_ca12_new_env_vars_documented(readme):
    text = (REPO_ROOT / readme).read_text(encoding="utf-8")
    missing = [var for var in NEW_ENV_VARS if var not in text]
    assert not missing, f"{readme} no menciona: {missing}"
