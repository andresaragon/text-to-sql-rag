"""
Mide cómo responde la capa de ejecución contra Oracle cuando la base falla o la
consulta se desboca. Pasa por el pipeline completo (cortafuegos y luego
execute_select): llamar a execute_select sin el tope de filas del cortafuegos
da otra cosa (ver docs/articles/query-timeouts.md).

Casos: base alcanzable (referencia), host inalcanzable y consultas recursivas
(ORDER BY y COUNT, que ningún tope de filas corta) con cada timeout pedido.

Uso (desde la raíz del repo, con Oracle de docker-compose.oracle.yml arriba):

    TARGET_DIALECT=oracle ALLOWED_SCHEMA=SALES \\
    TARGET_DATABASE_URL='oracle+oracledb://app_ro:app-ro-demo-pw@127.0.0.1:1521/?service_name=FREEPDB1' \\
    python -m scripts.bench_timeouts --timeouts 2,10 --out timeouts.json
"""

import argparse
import json
import time

from app.config import settings
from app.core import db
from app.core.db import DatabaseUnavailableError, QueryExecutionError, QueryTimeoutError
from app.core.safety import validate_and_prepare

TABLES = {"customers", "invoices", "payments", "collection_actions"}
UNREACHABLE_URL = "oracle+oracledb://app_ro:x@10.255.255.1:1521/?service_name=FREEPDB1"
RECURSIVE = (
    "WITH r(n) AS (SELECT 1 FROM customers WHERE customer_id = 1 "
    "UNION ALL SELECT n + 1 FROM r WHERE n < 100000000) {tail}"
)
QUERIES = {
    "reference": "SELECT COUNT(*) AS c FROM customers",
    "recursive_order_by": RECURSIVE.format(tail="SELECT n FROM r ORDER BY n DESC"),
    "recursive_count": RECURSIVE.format(tail="SELECT COUNT(*) AS c FROM r"),
    "recursive_stream": RECURSIVE.format(tail="SELECT n FROM r"),
}


def run(name: str, sql: str, timeout: int) -> dict:
    settings.query_timeout_seconds = timeout
    db.reset_target_engine()
    prepared = validate_and_prepare(
        sql,
        100,
        allowed_tables=TABLES,
        allowed_schema=settings.allowed_schema,
        dialect="oracle",
    )
    started = time.monotonic()
    try:
        rows = len(db.execute_select(prepared))
        outcome = f"ok, {rows} rows"
    except (
        QueryTimeoutError,
        DatabaseUnavailableError,
        QueryExecutionError,
    ) as exc:  # el tipo fija el HTTP
        outcome = type(exc).__name__
    return {
        "case": name,
        "timeout_s": timeout,
        "seconds": round(time.monotonic() - started, 2),
        "outcome": outcome,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--timeouts", default="2,10", help="segundos, separados por coma"
    )
    parser.add_argument("--out", help="archivo JSON de salida")
    args = parser.parse_args()
    timeouts = [int(t) for t in args.timeouts.split(",")]

    results = []
    good_url = settings.target_database_url
    settings.target_database_url = UNREACHABLE_URL
    results.append(run("unreachable_host", QUERIES["reference"], timeouts[0]))
    settings.target_database_url = good_url
    for timeout in timeouts:
        for name, sql in QUERIES.items():
            results.append(run(name, sql, timeout))
    for row in results:
        print(row)
    if args.out:
        with open(args.out, "w") as handle:
            json.dump(results, handle, indent=2)


if __name__ == "__main__":
    main()
