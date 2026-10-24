"""DPY-4011 con call_timeout vencido es un timeout (504), no una base caída (503).

El driver cierra la conexión cuando el cliente cancela una consulta que pasó de
`call_timeout` y no responde al corte: llega como DPY-4011, igual que una caída real.
Se distinguen por el tiempo transcurrido y por si la base responde a una conexión nueva.
"""

from unittest.mock import patch

import pytest

from app.config import settings
from app.core import db
from app.core.db import DatabaseUnavailableError, QueryTimeoutError
from tests.test_oracle_target import ORACLE_URL, _Conn, _Result, wrapped


class _ProbeEngine:
    """Primera conexión: la consulta falla con DPY-4011. Siguientes: `probe_ok` decide."""

    def __init__(self, probe_ok):
        self.connects, self.probe_ok = 0, probe_ok
        self.first = _Conn([wrapped("DPY-4011")])
        self.probe = _Conn([_Result([])])

    def connect(self):
        self.connects += 1
        if self.connects == 1:
            return self.first
        if not self.probe_ok:
            raise wrapped("DPY-6005")
        return self.probe


@pytest.fixture
def oracle_mode(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    monkeypatch.setattr(settings, "target_database_url", ORACLE_URL)
    monkeypatch.setattr(settings, "allowed_schema", "SALES")
    monkeypatch.setattr(settings, "query_timeout_seconds", 2)
    db.reset_target_engine()
    yield
    db.reset_target_engine()


def _run(engine, started, ended):
    with (
        patch("app.core.db._target_engine", return_value=engine),
        patch("app.core.db._monotonic", side_effect=[started, ended]),
    ):
        return db.execute_select("SELECT 1 FROM dual")


def test_dpy_4011_after_the_timeout_with_a_live_database_is_a_query_timeout(oracle_mode):
    engine = _ProbeEngine(probe_ok=True)
    with pytest.raises(QueryTimeoutError) as info:
        _run(engine, 0.0, 4.0)
    assert str(info.value) == "La consulta tardó demasiado, intenta ser más específico."
    assert engine.connects == 2


def test_dpy_4011_exactly_at_the_timeout_counts_as_timeout(oracle_mode):
    with pytest.raises(QueryTimeoutError):
        _run(_ProbeEngine(probe_ok=True), 0.0, 2.0)


def test_dpy_4011_before_the_timeout_is_database_unavailable_without_probing(oracle_mode):
    engine = _ProbeEngine(probe_ok=True)
    with pytest.raises(DatabaseUnavailableError):
        _run(engine, 0.0, 0.3)
    assert engine.connects == 1


def test_dpy_4011_after_the_timeout_with_a_dead_database_is_database_unavailable(oracle_mode):
    engine = _ProbeEngine(probe_ok=False)
    with pytest.raises(DatabaseUnavailableError) as info:
        _run(engine, 0.0, 4.0)
    assert str(info.value) == "Base de datos no disponible."
    assert engine.connects == 2
