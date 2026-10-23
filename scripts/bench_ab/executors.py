"""Ejecutor de consultas multi-dialecto para el benchmark A/B."""

from __future__ import annotations

import os
from collections.abc import Callable

from app.config import settings
from app.core.db import execute_select, reset_target_engine

_DEFAULT_ORACLE_RO_URL = (
    "oracle+oracledb://app_ro:app-ro-demo-pw@127.0.0.1:1521/?service_name=FREEPDB1"
)


def make_executor(
    timeout_s: int = 10,
    oracle_url: str | None = None,
) -> Callable[[str, str], list[dict]]:
    """Crea una función execute(dialect, sql) que conmuta la configuración y restaura el estado."""
    target_oracle_url = (
        oracle_url
        or os.getenv("BENCH_ORACLE_URL")
        or _DEFAULT_ORACLE_RO_URL
    )

    def execute(dialect: str, sql: str) -> list[dict]:
        orig_dialect = settings.target_dialect
        orig_url = settings.target_database_url
        orig_schema = settings.allowed_schema
        orig_timeout = settings.query_timeout_seconds

        try:
            if dialect == "oracle":
                settings.target_dialect = "oracle"
                settings.target_database_url = target_oracle_url
                settings.allowed_schema = "SALES"
            else:
                settings.target_dialect = "postgres"
                settings.target_database_url = settings.database_url

            settings.query_timeout_seconds = timeout_s

            reset_target_engine()
            return execute_select(sql)
        finally:
            settings.target_dialect = orig_dialect
            settings.target_database_url = orig_url
            settings.allowed_schema = orig_schema
            settings.query_timeout_seconds = orig_timeout
            reset_target_engine()

    return execute
