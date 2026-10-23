"""Dataset sintético y determinista para el benchmark A/B (mismos datos en Postgres y Oracle).

Con la semilla por defecto (42) siempre produce 300 clientes, 2000 facturas, 1486 pagos y 1117
acciones de cobranza; `checksums()` las fija con un SHA-256 por tabla. La "fecha de hoy" del
dataset es REFERENCE_DATE: las facturas sin pagar vencidas antes de esa fecha están `overdue`.

Uso (desde la raíz, con las bases levantadas):

    python -m scripts.gen_dataset --load both          # postgres, oracle o both
    python -m scripts.gen_dataset --checksums          # imprime conteos y sumas de control
"""

import argparse
import datetime as dt
import hashlib
import os
import random
from dataclasses import dataclass
from decimal import Decimal

SEED = 42
REFERENCE_DATE = dt.date(2026, 10, 1)

PG_URL = os.getenv("BENCH_PG_URL", "postgresql://postgres:postgres@127.0.0.1:5432/postgres")
ORACLE_DSN = os.getenv("BENCH_ORACLE_DSN", "127.0.0.1:1521/FREEPDB1")
ORACLE_USER = os.getenv("BENCH_ORACLE_USER", "sales")
ORACLE_PASSWORD = os.getenv("BENCH_ORACLE_PASSWORD", "sales-demo-pw")

_FIRST = ["Ana", "Luis", "Marco", "Sofia", "Diego", "Camila", "Pablo", "Elena", "Juan", "Laura", "Carlos", "Marta", "Andres", "Paula", "Jorge", "Lucia", "Mateo", "Valeria", "Sergio", "Daniela"]
_LAST = ["Torres", "Rossi", "Fernandez", "Gomez", "Lopez", "Martinez", "Perez", "Rojas", "Silva", "Diaz", "Vargas", "Castro", "Romero", "Herrera", "Morales", "Ortiz", "Ramos", "Suarez", "Mejia", "Cruz"]
_COUNTRIES = ["Colombia", "Colombia", "Colombia", "Mexico", "Mexico", "Italy", "Spain", "Chile", "Peru", "Argentina"]
_METHODS = ["bank_transfer", "bank_transfer", "credit_card", "credit_card", "cash", "paypal"]
_ACTIONS = ["email_reminder", "email_reminder", "call", "negotiation", "letter"]
_NOTES = [None, "Contacto realizado", "Sin respuesta", "Promesa de pago"]

TABLES = ("customers", "invoices", "payments", "collection_actions")


@dataclass(frozen=True)
class Dataset:
    customers: list
    invoices: list
    payments: list
    actions: list

    def table(self, name: str) -> list:
        return {"customers": self.customers, "invoices": self.invoices,
                "payments": self.payments, "collection_actions": self.actions}[name]


def generate(seed: int = SEED) -> Dataset:
    rng = random.Random(seed)
    names, customers = set(), []
    while len(customers) < 300:
        name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
        if name in names:
            name = f"{name} {len(customers)}"
        names.add(name)
        number = len(customers) + 1
        created = dt.datetime(2024, 1, 1) + dt.timedelta(seconds=rng.randrange(0, 900 * 86400))
        customers.append((number, name, f"user{number}@example.com", rng.choice(_COUNTRIES), created.replace(microsecond=0)))
    active = [c[0] for c in customers if rng.random() > 0.2]

    invoices, payments, actions = [], [], []
    for number in range(1, 2001):
        customer_id = rng.choice(active)
        amount = Decimal(str(round(rng.lognormvariate(6.2, 0.8), 2))).quantize(Decimal("0.01"))
        amount = max(amount, Decimal("40.00"))
        issued = dt.date(2025, 1, 1) + dt.timedelta(days=rng.randrange(0, 638))
        due = issued + dt.timedelta(days=rng.choice([30, 30, 45, 60]))
        paid = rng.random() < 0.55
        status = "paid" if paid else ("overdue" if due < REFERENCE_DATE else "pending")
        currency = rng.choice(["USD"] * 8 + ["COP", "EUR"])
        invoices.append((number, customer_id, amount, currency, issued, due, status))
        if paid:
            left = amount
            parts = rng.choice([1, 1, 2])
            for part_number in range(parts):
                if part_number == parts - 1:
                    part = left
                else:
                    part = (left * Decimal(rng.choice([0.4, 0.5, 0.6]))).quantize(Decimal("0.01"))
                left -= part
                day = issued + dt.timedelta(days=rng.randrange(1, (due - issued).days + 25))
                paid_at = dt.datetime.combine(day, dt.time(rng.randrange(8, 19), rng.randrange(60), rng.randrange(60)))
                payments.append((len(payments) + 1, number, part, paid_at, rng.choice(_METHODS)))
        elif status == "overdue":
            for _ in range(rng.choice([0, 1, 1, 2, 3])):
                actions.append((len(actions) + 1, number, rng.choice(_ACTIONS),
                                due + dt.timedelta(days=rng.randrange(1, 60)), rng.choice(_NOTES)))
    return Dataset(customers, invoices, payments, actions)


def checksums(dataset: Dataset) -> dict[str, str]:
    """`{tabla: 'filas:sha256'}` calculado sobre la representación de cada fila, en orden."""
    result = {}
    for name in TABLES:
        rows = dataset.table(name)
        digest = hashlib.sha256("\n".join(repr(r) for r in rows).encode("utf-8")).hexdigest()
        result[name] = f"{len(rows)}:{digest}"
    return result


def load_postgres(dataset: Dataset, url: str = PG_URL) -> None:
    import psycopg2
    import psycopg2.extras

    with psycopg2.connect(url) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE collection_actions, payments, invoices, customers RESTART IDENTITY CASCADE")
        psycopg2.extras.execute_values(cur, "INSERT INTO customers (customer_id, full_name, email, country, created_at) VALUES %s", dataset.customers)
        psycopg2.extras.execute_values(cur, "INSERT INTO invoices (invoice_id, customer_id, amount, currency, issued_date, due_date, status) VALUES %s", dataset.invoices)
        psycopg2.extras.execute_values(cur, "INSERT INTO payments (payment_id, invoice_id, amount_paid, paid_at, payment_method) VALUES %s", dataset.payments)
        psycopg2.extras.execute_values(cur, "INSERT INTO collection_actions (action_id, invoice_id, action_type, action_date, notes) VALUES %s", dataset.actions)
        for table, column in (("customers", "customer_id"), ("invoices", "invoice_id"),
                              ("payments", "payment_id"), ("collection_actions", "action_id")):
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), (SELECT MAX({column}) FROM {table}))")


def load_oracle(dataset: Dataset) -> None:
    """Solo DML (DELETE e INSERT). Un DDL aquí provocaría ORA-01466 en las lecturas READ ONLY siguientes."""
    import oracledb

    with oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN) as conn:
        cur = conn.cursor()
        for table in ("collection_actions", "payments", "invoices", "customers"):
            cur.execute(f"DELETE FROM {table}")
        cur.executemany("INSERT INTO customers (customer_id, full_name, email, country, created_at) VALUES (:1, :2, :3, :4, :5)", dataset.customers)
        cur.executemany("INSERT INTO invoices (invoice_id, customer_id, amount, currency, issued_date, due_date, status) VALUES (:1, :2, :3, :4, :5, :6, :7)", dataset.invoices)
        cur.executemany("INSERT INTO payments (payment_id, invoice_id, amount_paid, paid_at, payment_method) VALUES (:1, :2, :3, :4, :5)", dataset.payments)
        cur.executemany("INSERT INTO collection_actions (action_id, invoice_id, action_type, action_date, notes) VALUES (:1, :2, :3, :4, :5)", dataset.actions)
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--load", choices=["none", "postgres", "oracle", "both"], default="none")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--checksums", action="store_true", help="imprime conteos y sumas de control")
    args = parser.parse_args()
    dataset = generate(args.seed)
    if args.checksums or args.load == "none":
        for name, value in checksums(dataset).items():
            print(f"{name}: {value}")
    if args.load in ("postgres", "both"):
        load_postgres(dataset)
        print("cargado en Postgres")
    if args.load in ("oracle", "both"):
        load_oracle(dataset)
        print("cargado en Oracle")


if __name__ == "__main__":
    main()
