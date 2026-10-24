"""
Maneja la conexión a PostgreSQL y Oracle, y la ejecución segura de queries,
incluyendo timeout de ejecución (settings.query_timeout_seconds).
"""

import re
import time
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError

from app.config import settings

_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
)

# Debe coincidir con schema_embeddings.embedding vector(384) en db/schema.sql
_EMBEDDING_DIM = 384

# SQLSTATE que Postgres devuelve cuando statement_timeout cancela una query.
_QUERY_CANCELED_SQLSTATE = "57014"

# SQLSTATE de base no disponible: 08 = conexión (rechazada, perdida), 53 = sin
# recursos (too_many_connections, disco lleno), 57P01-57P03 = servidor apagándose
# o arrancando. Sin pgcode = el error es del cliente psycopg2 (no pudo conectar o
# perdió la conexión), así que también cuenta como base no disponible.
_UNAVAILABLE_SQLSTATE_PREFIXES = ("08", "53", "57P01", "57P02", "57P03")

_monotonic = time.monotonic

_ORACLE_SCHEMA_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
# DPY-4024: el driver agotó call_timeout. ORA-01013: la llamada fue cancelada; el único que cancela
# aquí es call_timeout (se vio al agotarse durante un fetch).
_ORACLE_TIMEOUT_CODES = {"DPY-4024", "ORA-01013"}
_ORACLE_UNAVAILABLE_CODES = {
    "ORA-01017",
    "ORA-01033",
    "ORA-01034",
    "ORA-01089",
    "ORA-03113",
    "ORA-03114",
    "ORA-03135",
    "ORA-12154",
    "ORA-12170",
    "ORA-12514",
    "ORA-12516",
    "ORA-12519",
    "ORA-12537",
    "ORA-12541",
    "DPY-4011",
}

# Formatos ISO para la sesión de Oracle. Con los valores por defecto (DD-MON-RR)
# fallan TIMESTAMP '2026-01-01 00:00:00' (ORA-01843) y fecha >= '2026-07-01' (ORA-01861).
ORACLE_SESSION_FORMATS = (
    "ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD'",
    "ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF'",
)

_cached_target_engine: Engine | None = None


class QueryTimeoutError(Exception):
    """La consulta excedió settings.query_timeout_seconds y fue cancelada."""


class QueryExecutionError(Exception):
    """La consulta falló contra la base (SQL inválido, columna inexistente, etc.)."""


class DatabaseUnavailableError(Exception):
    """Postgres u Oracle no responde, cortó la conexión o no acepta más conexiones."""


def _target_engine() -> Engine:
    """Devuelve el engine donde se ejecuta el SQL generado, cacheado."""
    global _cached_target_engine
    if _cached_target_engine is not None:
        return _cached_target_engine

    dialect = settings.target_dialect.strip().lower()
    if (
        dialect == "postgres"
        and settings.target_database_url == settings.database_url
    ):
        _cached_target_engine = _engine
        return _engine

    if dialect == "oracle":
        schema = settings.allowed_schema
        if (schema is None or schema.strip().lower() != "public") and (
            not schema or not _ORACLE_SCHEMA_REGEX.match(schema)
        ):
            raise ValueError(f"Invalid allowed_schema for Oracle: {schema!r}")

        engine = create_engine(
            settings.target_database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            connect_args={"tcp_connect_timeout": settings.db_connect_timeout_seconds},
        )

        @event.listens_for(engine, "connect")
        def _on_oracle_connect(dbapi_connection: Any, connection_record: Any) -> None:
            dbapi_connection.call_timeout = int(settings.query_timeout_seconds * 1000)
            statements = list(ORACLE_SESSION_FORMATS)
            current_schema = settings.allowed_schema
            if current_schema and current_schema.strip().lower() != "public":
                statements.append(f"ALTER SESSION SET CURRENT_SCHEMA = {current_schema}")
            cursor = dbapi_connection.cursor()
            try:
                for statement in statements:
                    cursor.execute(statement)
            finally:
                cursor.close()

        _cached_target_engine = engine
        return engine

    _cached_target_engine = create_engine(
        settings.target_database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )
    return _cached_target_engine


def reset_target_engine() -> None:
    """Descarta el engine cacheado (y lo cierra con dispose())."""
    global _cached_target_engine
    if _cached_target_engine is not None:
        if _cached_target_engine is not _engine:
            _cached_target_engine.dispose()
        _cached_target_engine = None


def map_oracle_error(exc: Exception) -> Exception:
    """Mapea una excepción de SQLAlchemy o de oracledb a la excepción correspondiente."""
    orig = getattr(exc, "orig", exc)
    code = None
    if hasattr(orig, "args") and len(orig.args) > 0:
        first_arg = orig.args[0]
        if hasattr(first_arg, "full_code"):
            code = first_arg.full_code
    if code is None and hasattr(orig, "full_code"):
        code = orig.full_code

    if code in _ORACLE_TIMEOUT_CODES:
        return QueryTimeoutError("La consulta tardó demasiado, intenta ser más específico.")

    if code in _ORACLE_UNAVAILABLE_CODES or (isinstance(code, str) and code.startswith("DPY-6")):
        return DatabaseUnavailableError("Base de datos no disponible.")

    mensaje = None
    if hasattr(orig, "args") and len(orig.args) > 0 and hasattr(orig.args[0], "message"):
        mensaje = orig.args[0].message
    if not mensaje:
        mensaje = str(orig) if orig is not None else str(exc)

    return QueryExecutionError(f"No se pudo ejecutar la consulta: {mensaje}")


def clear_schema_embeddings() -> int:
    """Borra todas las filas de schema_embeddings usando siempre _engine (Postgres)."""
    with _engine.begin() as conn:
        result = conn.execute(text("DELETE FROM schema_embeddings"))
        return result.rowcount


def _is_unavailable(exc: OperationalError) -> bool:
    if exc.connection_invalidated:
        return True
    pgcode = getattr(exc.orig, "pgcode", None)
    return pgcode is None or pgcode.startswith(_UNAVAILABLE_SQLSTATE_PREFIXES)


def _oracle_is_reachable(engine: Engine) -> bool:
    """True si una conexión nueva responde: separa un corte por call_timeout de una caída."""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1 FROM dual")
        return True
    except SQLAlchemyError:
        return False


def execute_select(sql: str) -> list[dict]:
    """Ejecuta un SELECT ya validado y devuelve las filas como lista de dicts."""
    if settings.target_dialect.strip().lower() == "oracle":
        max_retries = 5
        for attempt in range(max_retries + 1):
            started = _monotonic()
            try:
                engine = _target_engine()
                with engine.connect() as conn, conn.begin():
                    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                    result = conn.execute(text(sql))
                    return [{str(k).lower(): v for k, v in row.items()} for row in result.mappings()]
            except DBAPIError as exc:
                orig = getattr(exc, "orig", exc)
                code = None
                if hasattr(orig, "args") and len(orig.args) > 0:
                    first_arg = orig.args[0]
                    if hasattr(first_arg, "full_code"):
                        code = first_arg.full_code
                if code is None and hasattr(orig, "full_code"):
                    code = orig.full_code

                if code == "ORA-01466" and attempt < max_retries:
                    time.sleep(1)
                    continue
                if (
                    code == "DPY-4011"
                    and _monotonic() - started >= settings.query_timeout_seconds
                    and _oracle_is_reachable(engine)
                ):
                    raise QueryTimeoutError(
                        "La consulta tardó demasiado, intenta ser más específico."
                    ) from exc
                mapped = map_oracle_error(exc)
                raise mapped from exc

    try:
        with _engine.connect() as conn, conn.begin():
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
        if _is_unavailable(exc):
            raise DatabaseUnavailableError("Base de datos no disponible.") from exc
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
