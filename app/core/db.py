"""
Maneja la conexión a PostgreSQL y la ejecución segura de queries,
incluyendo timeout de ejecución (settings.query_timeout_seconds).
"""

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from pgvector.sqlalchemy import Vector

from app.config import settings

_engine = create_engine(settings.database_url)

# Debe coincidir con schema_embeddings.embedding vector(384) en db/schema.sql
_EMBEDDING_DIM = 384

# SQLSTATE que Postgres devuelve cuando statement_timeout cancela una query.
_QUERY_CANCELED_SQLSTATE = "57014"


class QueryTimeoutError(Exception):
    """La consulta excedió settings.query_timeout_seconds y fue cancelada."""


class QueryExecutionError(Exception):
    """La consulta falló contra la base (SQL inválido, columna inexistente, etc.)."""


def execute_select(sql: str) -> list[dict]:
    """Ejecuta un SELECT ya validado y devuelve las filas como lista de dicts."""
    try:
        with _engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("SET LOCAL statement_timeout = :timeout_ms"),
                    {"timeout_ms": settings.query_timeout_seconds * 1000},
                )
                result = conn.execute(text(sql))
                return [dict(row) for row in result.mappings()]
    except OperationalError as exc:
        if getattr(exc.orig, "pgcode", None) == _QUERY_CANCELED_SQLSTATE:
            raise QueryTimeoutError(
                "La consulta tardó demasiado, intenta ser más específico."
            ) from exc
        raise QueryExecutionError(f"No se pudo ejecutar la consulta: {exc.orig}") from exc
    except DBAPIError as exc:
        raise QueryExecutionError(f"No se pudo ejecutar la consulta: {exc.orig}") from exc


def save_schema_embedding(
    object_name: str, object_type: str, description: str, embedding: list[float]
) -> None:
    """Guarda un embedding de esquema en la tabla schema_embeddings."""
    stmt = text(
        """
        INSERT INTO schema_embeddings (object_name, object_type, description, embedding)
        VALUES (:object_name, :object_type, :description, :embedding)
        """
    ).bindparams(bindparam("embedding", type_=Vector(_EMBEDDING_DIM)))

    with _engine.begin() as conn:
        conn.execute(
            stmt,
            {
                "object_name": object_name,
                "object_type": object_type,
                "description": description,
                "embedding": embedding,
            },
        )
