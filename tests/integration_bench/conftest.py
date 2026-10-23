"""Fixtures del benchmark contra bases reales. Solo con BENCH_LIVE=1 (lo hace tests/run_bench_acceptance.sh,
que levanta Postgres y Oracle con compose). Carga el dataset completo: no mezclar con tests/integration."""

import os
import time

import oracledb
import pytest

from scripts import gen_dataset

ENABLED = os.getenv("BENCH_LIVE") == "1"
READER = {"user": "app_ro", "password": "app-ro-demo-pw", "dsn": gen_dataset.ORACLE_DSN}


def oracle_reader():
    conn = oracledb.connect(**READER)
    conn.cursor().execute("ALTER SESSION SET CURRENT_SCHEMA = SALES")
    return conn


@pytest.fixture(scope="session", autouse=True)
def loaded_dataset():
    """Espera a que Oracle termine sus scripts de inicio y carga el mismo dataset en las dos bases."""
    if not ENABLED:
        return None
    deadline, last = time.time() + 240, None
    while time.time() < deadline:
        try:
            with oracledb.connect(**READER) as conn:
                conn.cursor().execute("SELECT COUNT(*) FROM sales.customers")
            break
        except oracledb.Error as exc:
            last = exc
            time.sleep(3)
    else:
        pytest.fail(f"Oracle no quedó listo en 240 s: {last}")
    dataset = gen_dataset.generate()
    gen_dataset.load_postgres(dataset)
    gen_dataset.load_oracle(dataset)
    return dataset
