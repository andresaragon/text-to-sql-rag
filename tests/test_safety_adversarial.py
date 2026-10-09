"""
Tests adversariales del cortafuegos SQL (app/core/safety.py).

Complementan tests/test_safety.py (que no se toca). Dos listas parametrizadas:
- REJECT_*: ataques (tablas, funciones, sentencias, entrada) que deben lanzar la excepcion hija indicada.
- MUST_ACCEPT: SELECT legitimos complejos que NO deben bloquearse (evitan
  que el firewall se vuelva inutil por exceso de celo).
Mas tests de LIMIT y de fail-closed.
"""

import pytest

from app.core import safety
from app.core.safety import (
    DangerousFunctionError,
    NonSelectQueryError,
    TableNotAllowedError,
    UnsafeQueryError,
    enforce_limit,
    validate_and_prepare,
)

T = TableNotAllowedError
F = DangerousFunctionError
N = NonSelectQueryError
U = UnsafeQueryError

REJECT_TABLES = [
    ("SELECT * FROM pg_catalog.pg_shadow", T),
    ("SELECT * FROM public.pg_shadow", T),
    ('SELECT * FROM "PG_SHADOW"', T),
    ('SELECT * FROM "pg_catalog"."pg_authid"', T),
    ("SELECT * FROM information_schema.columns", T),
    ("SELECT * FROM PG_SHADOW", T),
    ("SELECT * FROM pg_shadow AS customers", T),
    ("SELECT * FROM pg_shadow customers", T),
    ("WITH pg_shadow AS (SELECT 1) SELECT * FROM pg_shadow, pg_authid", T),
    ("WITH c AS (SELECT * FROM pg_shadow) SELECT * FROM c", T),
    ("SELECT * FROM customers WHERE id IN (SELECT usesysid FROM pg_shadow)", T),
    ("SELECT (SELECT passwd FROM pg_shadow LIMIT 1) FROM customers", T),
    ("SELECT * FROM customers c JOIN LATERAL (SELECT * FROM pg_shadow) s ON true", T),
    ("SELECT * FROM schema_embeddings", T),
]

REJECT_FUNCTIONS = [
    ("SELECT pg_sleep(10)", F),
    ("SELECT pg_catalog.pg_sleep(10)", F),
    ("SELECT PG_SLEEP(10)", F),
    ('SELECT "pg_sleep"(10)', F),
    ("SELECT * FROM customers WHERE id = 1 AND (SELECT pg_sleep(5)) IS NULL", F),
    # --- Funciones en FROM ---
    ("SELECT * FROM pg_read_file('/etc/passwd')", F),
    ("SELECT * FROM pg_ls_dir('/')", F),
    ("SELECT * FROM dblink('host=x', 'select 1') AS t(a int)", F),
    ("SELECT * FROM pg_catalog.pg_read_file('/etc/passwd') AS t", F),
    # --- Funciones que ejecutan SQL arbitrario o tocan el servidor ---
    ("SELECT query_to_xml('select * from pg_shadow', true, true, '')", F),
    ("SELECT table_to_xml('pg_shadow', true, true, '')", F),
    ("SELECT query_to_xml_and_xmlschema('select 1', true, true, '')", F),
    ("SELECT cursor_to_xml('c', 1, true, true, '')", F),
    ("SELECT current_setting('is_superuser')", F),
    ("SELECT set_config('log_statement', 'all', false)", F),
    ("SELECT lo_import('/etc/passwd')", F),
    ("SELECT lo_export(1, '/tmp/x')", F),
    ("SELECT lo_get(1)", F),
    ("SELECT pg_ls_dir('/')", F),
    ("SELECT pg_stat_file('/etc/passwd')", F),
    ("SELECT pg_read_binary_file('/etc/passwd')", F),
    ("SELECT pg_terminate_backend(1)", F),
    ("SELECT pg_cancel_backend(1)", F),
    ("SELECT txid_current()", F),
    ("SELECT pg_advisory_lock(1)", F),
    ("SELECT pg_backend_pid()", F),
    ("SELECT version()", F),
]

REJECT_STATEMENTS = [
    ("SELECT * FROM customers FOR UPDATE", U),
    ("SELECT * FROM customers FOR SHARE", U),
    ("SELECT * FROM customers FOR NO KEY UPDATE", U),
    ("SELECT * FROM customers FOR UPDATE NOWAIT", U),
    ("SELECT id INTO newtable FROM customers", U),
    ("SELECT * INTO TEMP t FROM customers", U),
    ("EXPLAIN ANALYZE SELECT * FROM customers", N),
    ("EXPLAIN SELECT * FROM customers", N),
    ("SHOW ALL", N),
    ("SET statement_timeout = 0", N),
    ("COPY customers TO '/tmp/x'", N),
    ("CALL do_something()", N),
    ("DO $$ BEGIN PERFORM 1; END $$", N),
    ("WITH d AS (DELETE FROM customers RETURNING *) SELECT * FROM d", U),
    ("WITH i AS (INSERT INTO payments VALUES (1) RETURNING *) SELECT * FROM i", U),
    ("WITH u AS (UPDATE invoices SET status='x' RETURNING *) SELECT * FROM u", U),
]

REJECT_INPUT = [
    ("SELECT 1; SELECT 2", N),
    ("SELECT * FROM customers; DROP TABLE customers", N),
    ("SELECT * FROM customers; /* x */ DELETE FROM customers", N),
    ("SELECT * FROM customers -- x\n; DROP TABLE customers", N),
    ("SELECT * FROM customers /* x */ ; UPDATE customers SET name='x'", N),
    ("", U),
    ("   ", U),
    (";", U),
    ("-- solo comentario", U),
    ("/* solo comentario */", U),
    ("SELECT * FROM customers WHERE", U),
    ("SELECT ​* FROM pg_shadow", U),
    ("SELECT * FROM pg_shadow ", U),
    ("SELECT * FROM ｐｇ_shadow", U),
    ("SELECT * FROM pg_shаdow", U),
    ("SELECT * FROM customers WHERE name = 'a'; SELECT pg_sleep(1)", N),
]

MUST_ACCEPT = [
    "SELECT * FROM customers",
    "SELECT c.id, c.name, SUM(i.amount) AS total FROM customers c "
    "JOIN invoices i ON i.customer_id = c.id GROUP BY c.id, c.name HAVING SUM(i.amount) > 1000",
    "SELECT * FROM customers c LEFT JOIN invoices i ON i.customer_id = c.id "
    "LEFT JOIN payments p ON p.invoice_id = i.id",
    "WITH overdue AS (SELECT * FROM invoices WHERE status = 'overdue') "
    "SELECT c.name, COUNT(*) FROM overdue o JOIN customers c ON c.id = o.customer_id GROUP BY c.name",
    "WITH a AS (SELECT id FROM customers), b AS (SELECT id FROM a) SELECT * FROM b",
    "SELECT id, amount, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY amount DESC) rn FROM invoices",
    "SELECT customer_id, SUM(amount) OVER (PARTITION BY customer_id ORDER BY due_date "
    "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM invoices",
    "SELECT * FROM customers WHERE id IN (SELECT customer_id FROM invoices WHERE status = 'overdue')",
    "SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM invoices i WHERE i.customer_id = c.id)",
    "SELECT * FROM customers WHERE NOT EXISTS (SELECT 1 FROM payments p WHERE p.customer_id = customers.id)",
    "SELECT * FROM (SELECT customer_id, SUM(amount) s FROM invoices GROUP BY customer_id) t WHERE s > 10",
    "SELECT id FROM customers UNION SELECT id FROM invoices",
    "SELECT id FROM customers UNION ALL SELECT customer_id FROM invoices",
    "SELECT * FROM (SELECT id FROM customers UNION SELECT id FROM invoices) u",
    "SELECT id FROM customers INTERSECT SELECT customer_id FROM invoices",
    "SELECT id FROM customers EXCEPT SELECT customer_id FROM invoices",
    "SELECT COALESCE(SUM(amount), 0), COUNT(*), AVG(amount), MAX(due_date), MIN(due_date) FROM invoices",
    "SELECT CASE WHEN status = 'overdue' THEN 1 ELSE 0 END FROM invoices",
    "SELECT DATE_TRUNC('month', due_date) m, COUNT(*) FROM invoices GROUP BY 1 ORDER BY 1",
    "SELECT EXTRACT(YEAR FROM due_date), COUNT(*) FROM invoices GROUP BY 1",
    "SELECT CAST(amount AS INT), amount::numeric, UPPER(status), LOWER(status), LENGTH(status) FROM invoices",
    "SELECT * FROM invoices WHERE due_date < CURRENT_DATE - INTERVAL '30 days'",
    "SELECT * FROM invoices WHERE due_date < NOW()",
    "SELECT * FROM generate_series(1, 10)",
    "SELECT d::date FROM generate_series('2024-01-01'::date, '2024-12-01'::date, '1 month') AS d",
    "SELECT * FROM customers c JOIN LATERAL (SELECT * FROM invoices i WHERE i.customer_id = c.id "
    "ORDER BY due_date DESC LIMIT 1) l ON true",
    "SELECT * FROM customers WHERE name ILIKE '%pg_shadow%'",
    "SELECT * FROM customers WHERE name = 'pg_sleep(10)'",
    "SELECT 'SELECT * FROM pg_shadow' AS note FROM customers",
    "SELECT * FROM customers /* comentario inocente */",
    "SELECT * FROM customers -- comentario inocente",
    "SELECT * FROM customers;",
    "  SELECT * FROM customers  ;  ",
    "SELECT * FROM public.customers",
    'SELECT * FROM "customers"',
    "SELECT * FROM CUSTOMERS",
    "SELECT * FROM customers LIMIT 5 OFFSET 10",
    "SELECT * FROM customers ORDER BY name NULLS LAST",
    "SELECT STRING_AGG(name, ', ') FROM customers",
    "SELECT ARRAY_AGG(id) FROM customers",
    "SELECT COUNT(DISTINCT customer_id) FILTER (WHERE status = 'overdue') FROM invoices",
]


@pytest.mark.parametrize("sql,exc", REJECT_TABLES)
def test_reject_tables(sql, exc):
    with pytest.raises(exc):
        validate_and_prepare(sql, max_rows=100)


@pytest.mark.parametrize("sql,exc", REJECT_FUNCTIONS)
def test_reject_functions(sql, exc):
    with pytest.raises(exc):
        validate_and_prepare(sql, max_rows=100)


@pytest.mark.parametrize("sql,exc", REJECT_STATEMENTS)
def test_reject_statements(sql, exc):
    with pytest.raises(exc):
        validate_and_prepare(sql, max_rows=100)


@pytest.mark.parametrize("sql,exc", REJECT_INPUT)
def test_reject_input(sql, exc):
    with pytest.raises(exc):
        validate_and_prepare(sql, max_rows=100)


@pytest.mark.parametrize("sql", MUST_ACCEPT)
def test_accept_legitimate_select(sql):
    out = validate_and_prepare(sql, max_rows=100)
    assert "LIMIT" in out.upper()


# ----------------------------------------------------------------------
# LIMIT
# ----------------------------------------------------------------------

def _limit_value(sql):
    import sqlglot

    node = sqlglot.parse_one(sql, dialect="postgres")
    return int(node.args["limit"].expression.this)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM customers LIMIT 1000000",
        "SELECT * FROM customers LIMIT ALL",
        "SELECT * FROM customers LIMIT NULL",
        "SELECT * FROM customers LIMIT 10 + 5000",
        "SELECT * FROM customers FETCH FIRST 1000000 ROWS ONLY",
    ],
)
def test_limit_is_capped_to_max_rows(sql):
    out = validate_and_prepare(sql, max_rows=100)
    assert _limit_value(out) <= 100


def test_limit_inside_union_cannot_bypass_cap():
    out = validate_and_prepare(
        "SELECT id FROM customers UNION ALL SELECT customer_id FROM invoices LIMIT 99999",
        max_rows=100,
    )
    assert _limit_value(out) <= 100


def test_union_without_limit_gets_top_level_limit():
    out = validate_and_prepare(
        "SELECT id FROM customers UNION SELECT customer_id FROM invoices", max_rows=100
    )
    assert _limit_value(out) == 100


def test_huge_offset_is_rejected():
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare("SELECT * FROM customers OFFSET 999999999999", max_rows=100)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM (SELECT * FROM customers OFFSET 99999999) t",
        "WITH c AS (SELECT * FROM customers OFFSET 99999999) SELECT * FROM c",
        "SELECT * FROM customers WHERE id IN (SELECT id FROM invoices OFFSET 99999999)",
        "SELECT id FROM customers OFFSET -1",
    ],
)
def test_nested_or_negative_offset_is_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare(sql, max_rows=100)


def test_offset_at_the_cap_is_accepted():
    out = validate_and_prepare(
        f"SELECT * FROM customers OFFSET {safety.MAX_OFFSET}", max_rows=100
    )
    assert "OFFSET" in out.upper()


def test_enforce_limit_negative_or_zero_is_not_silently_unbounded():
    out = enforce_limit("SELECT * FROM customers LIMIT -1", max_rows=100)
    assert _limit_value(out) <= 100


# ----------------------------------------------------------------------
# Fail-closed
# ----------------------------------------------------------------------

def test_unexpected_parser_exception_is_rejected(monkeypatch):
    def boom(*a, **k):
        raise RecursionError("boom")

    monkeypatch.setattr(safety.sqlglot, "parse", boom)
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare("SELECT * FROM customers", max_rows=100)


def test_unexpected_parser_exception_in_is_safe_select_is_false(monkeypatch):
    def boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(safety.sqlglot, "parse", boom)
    assert safety.is_safe_select("SELECT 1") is False


def test_deeply_nested_query_is_rejected_not_crashed():
    sql = "SELECT " + "(" * 5000 + "1" + ")" * 5000
    try:
        validate_and_prepare(sql, max_rows=100)
    except UnsafeQueryError:
        pass


@pytest.mark.parametrize("bad", [None, 123, b"SELECT 1"])
def test_non_string_input_is_rejected(bad):
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare(bad, max_rows=100)


def test_custom_allowed_tables_are_respected_and_case_insensitive():
    assert validate_and_prepare("SELECT * FROM Orders", 10, allowed_tables={"orders"})
    with pytest.raises(TableNotAllowedError):
        validate_and_prepare("SELECT * FROM customers", 10, allowed_tables={"orders"})


def test_empty_allowed_tables_rejects_everything():
    with pytest.raises(TableNotAllowedError):
        validate_and_prepare("SELECT * FROM customers", 10, allowed_tables=set())


# ----------------------------------------------------------------------
# Funciones de informacion del entorno (identidad, base, red)
# ----------------------------------------------------------------------

ENV_INFO_FUNCTIONS = [
    "current_database()",
    "CURRENT_DATABASE()",
    "pg_catalog.current_database()",
    "current_user",
    "CURRENT_USER",
    "session_user",
    "SESSION_USER",
    "current_schema()",
    "current_schema",
    "current_schemas(true)",
    "inet_server_addr()",
    "inet_server_port()",
    "inet_client_addr()",
    "inet_client_port()",
]


@pytest.mark.parametrize("expr", ENV_INFO_FUNCTIONS)
@pytest.mark.parametrize("template", ["SELECT {}", "SELECT * FROM customers WHERE name = {}", "SELECT * FROM {}"])
def test_reject_env_info(expr, template):
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare(template.format(expr), max_rows=100)


def test_env_info_function_error_is_dangerous_function():
    with pytest.raises(DangerousFunctionError):
        validate_and_prepare("SELECT current_database()", max_rows=100)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT current_date",
        "SELECT current_timestamp",
        "SELECT * FROM invoices WHERE due_date < current_date",
        "SELECT * FROM customers WHERE name = 'current_user'",
        "SELECT * FROM customers WHERE name = 'current_database()'",
        "SELECT current_status FROM (SELECT status AS current_status FROM invoices) t",
    ],
)
def test_accept_similar_but_harmless(sql):
    assert validate_and_prepare(sql, max_rows=100)


# ----------------------------------------------------------------------
# Funciones comunes de SQL de reportes: el firewall no debe estorbarlas
# ----------------------------------------------------------------------

REPORT_FUNCTIONS = [
    "date_trunc('month', due_date)",
    "to_char(due_date, 'YYYY-MM')",
    "extract(year FROM due_date)",
    "extract(epoch FROM (now() - due_date))",
    "age(now(), due_date)",
    "coalesce(amount, 0)",
    "nullif(amount, 0)",
    "greatest(amount, 100)",
    "least(amount, 100)",
    "round(amount, 2)",
    "round(amount::numeric, 2)",
    "ceil(amount)",
    "floor(amount)",
    "abs(amount)",
    "power(amount, 2)",
    "sqrt(amount)",
    "mod(id, 2)",
    "sum(amount)",
    "avg(amount)",
    "count(*)",
    "count(DISTINCT customer_id)",
    "min(due_date)",
    "max(due_date)",
    "string_agg(status, ', ')",
    "array_agg(id)",
    "bool_or(amount > 100)",
    "row_number() OVER (ORDER BY due_date)",
    "rank() OVER (PARTITION BY customer_id ORDER BY amount DESC)",
    "dense_rank() OVER (ORDER BY amount)",
    "lag(amount) OVER (PARTITION BY customer_id ORDER BY due_date)",
    "lead(amount, 1, 0) OVER (PARTITION BY customer_id ORDER BY due_date)",
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY amount)",
    "ntile(4) OVER (ORDER BY amount)",
    "first_value(amount) OVER (PARTITION BY customer_id ORDER BY due_date)",
    "lower(status)",
    "upper(status)",
    "trim(status)",
    "ltrim(status)",
    "substring(status FROM 1 FOR 3)",
    "substr(status, 1, 3)",
    "left(status, 3)",
    "right(status, 3)",
    "length(status)",
    "replace(status, 'a', 'b')",
    "concat(status, '-', id)",
    "concat_ws('-', status, id)",
    "split_part(status, '_', 1)",
    "initcap(status)",
    "jsonb_build_object('id', id, 'status', status)",
    "jsonb_agg(status)",
    "to_date('2024-01-01', 'YYYY-MM-DD')",
    "to_timestamp(1700000000)",
    "date_part('month', due_date)",
    "make_date(2024, 1, 1)",
    "current_date",
    "now()",
    "md5(status)",
    "cast(amount AS integer)",
    "regexp_replace(status, '[0-9]+', '')",
    "unnest(ARRAY[1, 2, 3])",
]


@pytest.mark.parametrize("expr", REPORT_FUNCTIONS)
def test_accept_report_function(expr):
    sql = f"SELECT {expr} FROM invoices"
    assert validate_and_prepare(sql, max_rows=100)
