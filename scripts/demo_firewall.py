"""Demostración local y determinista del cortafuegos SQL.

Ejecutar con ``python -m scripts.demo_firewall``. No usa base de datos, LLM ni red:
pasa SQL fijo por ``validate_and_prepare`` y muestra qué se permite y qué se bloquea.
"""

from app.core.safety import UnsafeQueryError, validate_and_prepare

MAX_ROWS = 100

# (label, sql). Las columnas son las del esquema real de db/schema.sql.
LEGITIMATE = (
    ("Valid SELECT (row cap injected)",
     "SELECT customer_id, full_name FROM customers WHERE country = 'CO'"),
    ("Valid SELECT with explicit LIMIT",
     "SELECT invoice_id, amount FROM invoices WHERE status = 'overdue' LIMIT 25"),
)

MALICIOUS = (
    ("Stacked statements", "SELECT * FROM customers; DROP TABLE invoices"),
    ("DELETE", "DELETE FROM customers WHERE customer_id = 1"),
    ("UPDATE", "UPDATE invoices SET amount = 0"),
    ("System catalog table", "SELECT * FROM pg_shadow"),
    ("Time-based blind injection", "SELECT pg_sleep(10) FROM customers"),
    ("Server-side file read", "SELECT pg_read_file('/etc/passwd') FROM customers"),
    ("Second statement hidden after a comment",
     "SELECT * FROM customers /* harmless */; -- second statement\nDROP TABLE invoices"),
    ("UNION into the catalog",
     "SELECT full_name FROM customers UNION SELECT tablename FROM pg_catalog.pg_tables"),
)

LEGITIMATE_QUERIES = tuple(sql for _, sql in LEGITIMATE)
MALICIOUS_QUERIES = tuple(sql for _, sql in MALICIOUS)


def _one_line(sql: str) -> str:
    return " ".join(sql.split())


def _show(label: str, sql: str) -> None:
    try:
        prepared = validate_and_prepare(sql, max_rows=MAX_ROWS)
        status, detail = "ALLOWED", prepared
    except UnsafeQueryError as error:
        status, detail = "BLOCKED", str(error)
    print(f"[{status}] {label}")
    print(f"    SQL:    {_one_line(sql)}")
    print(f"    Result: {detail}")
    print()


def main() -> None:
    print("AST safety firewall demo (no database, no LLM)\n")
    for label, sql in LEGITIMATE + MALICIOUS:
        _show(label, sql)


if __name__ == "__main__":
    main()
