"""Formatos de fecha ISO en la sesión de Oracle (leader-authored, failing by design).

Con los formatos por defecto (DD-MON-RR) fallan dos cosas muy habituales: `CAST('2026-01-01 00:00:00' AS TIMESTAMP)`
(en lo que el firewall convierte `TIMESTAMP '...'`) con ORA-01843 y `fecha >= '2026-07-01'` con ORA-01861.
"""

import contextlib
from unittest.mock import MagicMock

from app.config import settings
from app.core import db

EXPECTED = (
    "ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD'",
    "ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF'",
)


def test_the_iso_session_statements_are_the_documented_ones():
    assert db.ORACLE_SESSION_FORMATS == EXPECTED


def test_every_new_oracle_connection_runs_them(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    monkeypatch.setattr(settings, "target_database_url", "oracle+oracledb://u:p@127.0.0.1:1521/?service_name=X")
    monkeypatch.setattr(settings, "allowed_schema", "SALES")
    db.reset_target_engine()
    try:
        engine = db._target_engine()
        executed = []
        for listener in list(engine.pool.dispatch.connect):
            connection = MagicMock()
            connection.cursor.return_value.execute.side_effect = lambda sql, *a, **k: executed.append(sql)
            with contextlib.suppress(Exception):  # los oyentes propios del dialecto esperan una conexión real
                listener(connection, MagicMock())
        for statement in EXPECTED:
            assert statement in executed, executed
        assert any(s.startswith("ALTER SESSION SET CURRENT_SCHEMA") for s in executed)  # lo anterior se conserva
    finally:
        db.reset_target_engine()
