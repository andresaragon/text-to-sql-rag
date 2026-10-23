"""Fixtures de integración contra Oracle real. Se activan solo con ORACLE_INTEGRATION=1
(lo hace `bash tests/run_acceptance.sh`, que levanta Oracle con el override de compose)."""

import os
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.core import db

READER_URL = "oracle+oracledb://app_ro:app-ro-demo-pw@127.0.0.1:1521/?service_name=FREEPDB1"
OWNER_URL = "oracle+oracledb://sales:sales-demo-pw@127.0.0.1:1521/?service_name=FREEPDB1"
ENABLED = os.getenv("ORACLE_INTEGRATION") == "1"


@pytest.fixture(scope="session", autouse=True)
def oracle_ready():
    """Espera a que terminen los scripts de db/oracle (la imagen no avisa de ello) y a que
    una lectura READ ONLY sobre las tablas recién creadas deje de dar ORA-01466."""
    if not ENABLED:
        return
    engine = create_engine(READER_URL)
    deadline, last = time.time() + 240, None
    while time.time() < deadline:
        try:
            with engine.connect() as conn, conn.begin():
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                if conn.execute(text("SELECT COUNT(*) FROM sales.customers")).scalar() >= 3:
                    return
        except SQLAlchemyError as exc:  # se reintenta hasta que Oracle esté listo
            last = exc
        time.sleep(3)
    pytest.fail(f"Oracle no quedó listo en 240 s: {last}")


@pytest.fixture
def oracle(monkeypatch):
    """Configura la app para Oracle; `oracle(url=..., timeout=...)` reconfigura dentro del test."""

    def configure(url=READER_URL, timeout=2):
        monkeypatch.setattr(settings, "target_dialect", "oracle")
        monkeypatch.setattr(settings, "target_database_url", url)
        monkeypatch.setattr(settings, "allowed_schema", "SALES")
        monkeypatch.setattr(settings, "query_timeout_seconds", timeout)
        db.reset_target_engine()

    configure()
    yield configure
    db.reset_target_engine()
