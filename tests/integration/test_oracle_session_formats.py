"""Formatos ISO contra Oracle real (leader-authored, failing by design). Solo con ORACLE_INTEGRATION=1."""

import pytest

from app.core import db
from app.core.safety import validate_and_prepare

from .conftest import ENABLED

pytestmark = pytest.mark.skipif(not ENABLED, reason="necesita Oracle: bash tests/run_acceptance.sh")


def test_an_iso_string_compared_with_a_date_column_works(oracle):
    # Los modelos escriben esto constantemente; con NLS_DATE_FORMAT por defecto da ORA-01861.
    rows = db.execute_select("SELECT COUNT(*) AS n FROM invoices WHERE issued_date >= '2026-07-01'")
    assert rows == [{"n": 2}]


def test_an_iso_string_cast_to_timestamp_works(oracle):
    rows = db.execute_select("SELECT COUNT(*) AS n FROM customers WHERE created_at < CAST('2030-01-01 00:00:00' AS TIMESTAMP)")
    assert rows == [{"n": 3}]


def test_a_timestamp_literal_survives_the_firewall_round_trip(oracle):
    # El firewall reserializa TIMESTAMP '...' como CAST('...' AS TIMESTAMP): antes daba ORA-01843.
    safe = validate_and_prepare(
        "SELECT COUNT(*) AS n FROM customers WHERE created_at < TIMESTAMP '2030-01-01 00:00:00'",
        100, dialect="oracle", allowed_schema="SALES",
    )
    assert "CAST(" in safe.upper()
    assert db.execute_select(safe) == [{"n": 3}]


def test_dates_still_come_back_as_python_values(oracle):
    row = db.execute_select("SELECT issued_date FROM invoices ORDER BY invoice_id FETCH FIRST 1 ROWS ONLY")[0]
    assert hasattr(row["issued_date"], "year")  # el formato NLS solo afecta a las conversiones de texto
