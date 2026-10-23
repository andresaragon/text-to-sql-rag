"""Precondiciones: lo que ya existe en `main` y en lo que se apoyan las pruebas de aceptación de Oracle.

Deben pasar desde ya (SPEC.md). Si una falla, el problema es del repo o del test, no del maker.
"""

import re

from app.config import settings
from app.core import db
from app.core.safety import validate_and_prepare
from scripts.index_schema import load_schema_fragments


def test_the_firewall_already_validates_oracle_sql():
    out = validate_and_prepare("SELECT * FROM sales.customers", 100, dialect="oracle", allowed_schema="SALES")
    assert re.search(r"FETCH FIRST 100 ROWS ONLY\s*$", out)


def test_db_exception_classes_exist():
    for name in ("QueryTimeoutError", "QueryExecutionError", "DatabaseUnavailableError"):
        assert hasattr(db, name), name
    assert callable(db.execute_select)


def test_settings_fields_the_spec_builds_on_exist():
    for name in (
        "database_url",
        "target_dialect",
        "allowed_schema",
        "query_timeout_seconds",
        "db_connect_timeout_seconds",
        "db_pool_size",
        "db_max_overflow",
        "db_pool_timeout_seconds",
    ):
        assert hasattr(settings, name), name


def test_postgres_examples_use_the_sql_fence_format_the_tests_parse():
    examples = [f for f in load_schema_fragments() if f["object_type"] == "example_query"]
    assert examples
    for fragment in examples:
        assert re.search(r"```sql\s*.*?```", fragment["description"], re.DOTALL), fragment["object_name"]
