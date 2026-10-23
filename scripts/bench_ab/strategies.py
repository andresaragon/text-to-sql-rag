"""Estrategias de ejecución y evaluación para el benchmark A/B."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot.errors import SqlglotError

from app.core.db import DatabaseUnavailableError, QueryExecutionError, QueryTimeoutError
from app.core.safety import UnsafeQueryError, validate_and_prepare
from scripts.bench_ab.scoring import compare

STRATEGIES: tuple[str, ...] = ("pg_direct", "oracle_direct", "pg_transpiled")

PROMPT_DIALECT: dict[str, str] = {
    "pg_direct": "postgres",
    "oracle_direct": "oracle",
    "pg_transpiled": "postgres",
}

EXEC_DIALECT: dict[str, str] = {
    "pg_direct": "postgres",
    "oracle_direct": "oracle",
    "pg_transpiled": "oracle",
}

_GENERIC_DB_ERRORS = {"Error", "DatabaseError", "OperationalError", "ProgrammingError"}
_ORA_REGEX = re.compile(r"\b(ORA-\d+|DPY-\d+|PLS-\d+)\b")
_PG_REGEX = re.compile(r"psycopg2\.errors\.([A-Za-z0-9_]+)")


@dataclass(frozen=True)
class Evaluation:
    status: str
    strict: bool
    relaxed: bool
    final_sql: str | None
    error: str | None
    error_code: str | None


def transpile(sql: str) -> str:
    """Transpila una consulta SQL de Postgres a Oracle usando sqlglot."""
    return sqlglot.transpile(sql, read="postgres", write="oracle")[0]


def _extract_error_code(exc: Exception) -> str | None:
    if isinstance(exc, QueryTimeoutError):
        return "TIMEOUT"
    if isinstance(exc, DatabaseUnavailableError):
        return "UNAVAILABLE"

    msg = str(exc)
    m_ora = _ORA_REGEX.search(msg)
    if m_ora:
        return m_ora.group(1)

    m_pg = _PG_REGEX.search(msg)
    if m_pg:
        return m_pg.group(1)

    cause = getattr(exc, "__cause__", None)
    orig = getattr(cause, "orig", cause)
    if orig is not None:
        cls_name = type(orig).__name__
        if cls_name not in _GENERIC_DB_ERRORS:
            return cls_name

    return None


def evaluate_sql(
    strategy: str,
    raw_sql: str | None,
    gold_rows: Sequence[Any],
    ordered: bool,
    execute: Callable[[str, str], list[dict]],
    max_rows: int = 100,
) -> Evaluation:
    """
    Evalúa una consulta generada contra una estrategia dada y compara su resultado
    con las filas de referencia (gold_rows).
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Estrategia desconocida: {strategy!r}")

    if raw_sql is None or not raw_sql.strip():
        return Evaluation(
            status="generation_error",
            strict=False,
            relaxed=False,
            final_sql=None,
            error="Consulta vacía o no generada",
            error_code=None,
        )

    exec_dialect = EXEC_DIALECT[strategy]
    allowed_schema = "SALES" if exec_dialect == "oracle" else None

    if strategy == "pg_transpiled":
        try:
            current_sql = transpile(raw_sql)
        except SqlglotError as err:
            return Evaluation(
                status="execution_error",
                strict=False,
                relaxed=False,
                final_sql=None,
                error=str(err),
                error_code="TRANSPILE",
            )
    else:
        current_sql = raw_sql

    try:
        final_sql = validate_and_prepare(
            current_sql,
            max_rows=max_rows,
            dialect=exec_dialect,
            allowed_schema=allowed_schema,
        )
    except UnsafeQueryError as err:
        return Evaluation(
            status="firewall_rejected",
            strict=False,
            relaxed=False,
            final_sql=None,
            error=str(err),
            error_code=None,
        )

    try:
        got_rows = execute(exec_dialect, final_sql)
    except (QueryExecutionError, QueryTimeoutError, DatabaseUnavailableError) as err:
        code = _extract_error_code(err)
        return Evaluation(
            status="execution_error",
            strict=False,
            relaxed=False,
            final_sql=final_sql,
            error=str(err),
            error_code=code,
        )

    cmp = compare(gold_rows, got_rows, ordered)
    status = "correct" if cmp.strict else "wrong"
    return Evaluation(
        status=status,
        strict=cmp.strict,
        relaxed=cmp.relaxed,
        final_sql=final_sql,
        error=None,
        error_code=None,
    )
