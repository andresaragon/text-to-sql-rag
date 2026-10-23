"""Cortafuegos con dialecto Oracle (`dialect="oracle"` / TARGET_DIALECT=oracle).

Escritas antes de implementar (rojas por diseño); no se editan para hacerlas pasar.
Cada caso se comprobó contra sqlglot 25.24.0: parsea (y el firewall debe decidir) o no parsea
(y se rechaza por fail-closed). Las pruebas de Postgres existentes no cambian.

Amenazas propias de Oracle que NO existen en Postgres:
- Paquetes: UTL_HTTP/UTL_INADDR/UTL_FILE/DBMS_LOCK/DBMS_PIPE/DBMS_XMLGEN... se llaman como
  `PAQUETE.FUNCION(...)`; sqlglot conserva el calificador en un nodo Dot, así que la regla
  es sobre el calificador, no sobre el nombre de la función.
- Secuencias (`s.NEXTVAL`) cambian estado y parsean como columna, no como Dot.
- Funciones de tabla (TABLE(), XMLTABLE, JSON_TABLE), db links (`tabla@enlace`), hints
  (`/*+ PARALLEL */`), FETCH FIRST ... PERCENT / WITH TIES (no acotan filas).
"""

import re

import pytest

from app.config import settings
from app.core.safety import (
    DangerousFunctionError,
    TableNotAllowedError,
    UnsafeQueryError,
    validate_and_prepare,
)


def oracle(sql, max_rows=100, **kwargs):
    return validate_and_prepare(sql, max_rows, dialect="oracle", **kwargs)


# ---------------------------------------------------------------- llamadas peligrosas
REJECT_QUALIFIED_CALLS = [
    "SELECT UTL_HTTP.REQUEST('http://evil.example/x') FROM customers",
    "SELECT utl_http.request('http://evil.example/x') FROM customers",
    "SELECT UTL_INADDR.GET_HOST_ADDRESS('evil.example') FROM customers",
    "SELECT UTL_FILE.FOPEN('/tmp', 'x', 'r') FROM customers",
    "SELECT DBMS_LOCK.SLEEP(10) FROM customers",
    "SELECT dbms_lock.sleep(10) FROM customers",
    "SELECT SYS.DBMS_LOCK.SLEEP(10) FROM customers",
    'SELECT "SYS"."DBMS_LOCK"."SLEEP"(5) FROM customers',
    "SELECT DBMS_LOCK . SLEEP(5) FROM customers",
    "SELECT UTL_HTTP/**/.REQUEST('http://evil.example/x') FROM customers",
    "SELECT DBMS_PIPE.RECEIVE_MESSAGE('p', 10) FROM customers",
    "SELECT DBMS_XMLGEN.GETXML('select 1 from dual') FROM customers",
    "SELECT DBMS_RANDOM.STRING('U', 8) FROM customers",
    "SELECT DBMS_CRYPTO.HASH(UTL_RAW.CAST_TO_RAW('a'), 2) FROM customers",
    "SELECT HTTPURITYPE('http://evil.example/x').GETCLOB() FROM customers",
    "SELECT other.my_func(1) FROM customers",
    "SELECT * FROM customers WHERE DBMS_LOCK.SLEEP(5) = 0",
    "SELECT * FROM customers ORDER BY DBMS_PIPE.RECEIVE_MESSAGE('x', 5)",
    "SELECT SUM(DBMS_LOCK.SLEEP(1)) FROM customers",
    "SELECT CASE WHEN 1 = 1 THEN UTL_HTTP.REQUEST('http://evil.example/x') END FROM customers",
    "SELECT (SELECT UTL_INADDR.GET_HOST_ADDRESS('x') FROM customers FETCH FIRST 1 ROWS ONLY) FROM customers",
    "WITH x AS (SELECT DBMS_LOCK.SLEEP(5) AS s FROM customers) SELECT * FROM x",
    "SELECT * FROM customers c JOIN invoices i ON DBMS_LOCK.SLEEP(1) = 0",
    "SELECT status FROM invoices GROUP BY status HAVING DBMS_LOCK.SLEEP(1) = 0",
    "SELECT customer_id FROM customers UNION ALL SELECT DBMS_LOCK.SLEEP(1) FROM customers",
]

REJECT_SIDE_EFFECT_AND_INFO_FUNCTIONS = [
    # Secuencias: cambian estado; sqlglot las parsea como columna (no hay Dot).
    "SELECT s.NEXTVAL FROM customers",
    "SELECT s.CURRVAL FROM customers",
    "SELECT sales.s.NEXTVAL FROM customers",
    # Revelan información del servidor o de la sesión.
    "SELECT SYS_CONTEXT('USERENV', 'IP_ADDRESS') FROM customers",
    "SELECT USERENV('SESSIONID') FROM customers",
    "SELECT USER FROM customers",
    "SELECT UID FROM customers",
    # XML con entidades externas / consultas indirectas.
    "SELECT XMLTYPE('<a/>') FROM customers",
    "SELECT EXTRACTVALUE(XMLTYPE('<a/>'), '/a') FROM customers",
    "SELECT XMLQUERY('/a' PASSING XMLTYPE('<a/>') RETURNING CONTENT) FROM customers",
    # XMLTYPE también se puede construir con CAST; ORA_* revelan la base y el usuario.
    "SELECT CAST('<a/>' AS XMLTYPE) FROM customers",
    "SELECT ORA_DATABASE_NAME FROM customers",
    "SELECT ORA_LOGIN_USER FROM customers",
]


@pytest.mark.parametrize("sql", REJECT_QUALIFIED_CALLS)
def test_reject_package_and_schema_qualified_calls(sql):
    with pytest.raises(DangerousFunctionError):
        oracle(sql)


@pytest.mark.parametrize("sql", REJECT_SIDE_EFFECT_AND_INFO_FUNCTIONS)
def test_reject_sequences_and_information_functions(sql):
    with pytest.raises(UnsafeQueryError):
        oracle(sql)


# ------------------------------------------------- calificadores no declarados (sin paréntesis)
# En Oracle una función de paquete sin argumentos se llama SIN paréntesis, y sqlglot la parsea
# como una columna calificada: `UTL_INADDR.GET_HOST_NAME` -> Column(table=UTL_INADDR). Un
# calificador de columna que no es una tabla ni un alias declarados en la consulta no es una
# columna: es un paquete. (Los alias de COLUMNA no cuentan: `SELECT 1 AS pkg, pkg.f` seguiría
# llamando al paquete.)
REJECT_UNDECLARED_QUALIFIERS = [
    "SELECT UTL_INADDR.GET_HOST_NAME FROM customers",
    "SELECT UTL_INADDR.GET_HOST_ADDRESS FROM customers",
    "SELECT DBMS_RANDOM.VALUE FROM customers",
    "SELECT SYS.DBMS_UTILITY.GET_TIME FROM customers",
    "SELECT DBMS_SESSION.UNIQUE_SESSION_ID FROM customers",
    "SELECT UTL_INADDR.GET_HOST_NAME FROM customers c",
    "SELECT * FROM customers WHERE UTL_INADDR.GET_HOST_NAME IS NOT NULL",
    "SELECT * FROM customers ORDER BY DBMS_RANDOM.VALUE",
    (
        "SELECT c.full_name FROM customers c WHERE c.customer_id IN "
        "(SELECT customer_id FROM invoices WHERE DBMS_RANDOM.VALUE > 0)"
    ),
    # Un alias de columna con el nombre del paquete no lo declara como tabla.
    "SELECT 1 AS UTL_INADDR, UTL_INADDR.GET_HOST_NAME FROM customers",
]


@pytest.mark.parametrize("sql", REJECT_UNDECLARED_QUALIFIERS)
def test_reject_qualifiers_that_are_not_declared_tables_or_aliases(sql):
    with pytest.raises(UnsafeQueryError):
        oracle(sql)


ACCEPT_DECLARED_QUALIFIERS = [
    "SELECT customers.full_name FROM customers",
    "SELECT c.full_name, i.amount FROM customers c JOIN invoices i ON i.customer_id = c.customer_id",
    "SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM invoices i WHERE i.customer_id = c.customer_id)",
    "WITH o AS (SELECT * FROM invoices) SELECT o.status FROM o",
    "SELECT t.n FROM (SELECT COUNT(*) AS n FROM customers) t",
    "SELECT c.full_name FROM customers c, invoices i WHERE c.customer_id = i.customer_id(+)",
]


@pytest.mark.parametrize("sql", ACCEPT_DECLARED_QUALIFIERS)
def test_accept_qualifiers_that_are_declared_tables_or_aliases(sql):
    assert oracle(sql)


def test_schema_qualified_column_of_a_declared_table_is_accepted():
    assert oracle("SELECT sales.customers.full_name FROM sales.customers", allowed_schema="SALES")


# ----------------------------------------------------------- tablas, diccionario, dblinks
REJECT_TABLES = [
    "SELECT * FROM all_tables",
    "SELECT * FROM all_tab_columns",
    "SELECT * FROM dba_users",
    "SELECT * FROM dba_role_privs",
    "SELECT * FROM user_tables",
    "SELECT * FROM user_source",
    "SELECT * FROM v$session",
    "SELECT * FROM v$parameter",
    "SELECT * FROM gv$session",
    "SELECT * FROM dictionary",
    "SELECT * FROM session_privs",
    "SELECT * FROM sys.user$",
    "SELECT * FROM schema_embeddings",
    "SELECT 1 FROM dual",
    "SELECT SYSDATE FROM dual",
    "SELECT level FROM dual CONNECT BY level <= 1000000000",
    # Enlaces de base de datos: el nombre calificado por @ nunca coincide con la lista blanca.
    "SELECT * FROM customers@remote c",
    'SELECT * FROM invoices@"x.y"',
    "SELECT * FROM customers@",
    "SELECT * FROM customers WHERE customer_id IN (SELECT customer_id FROM invoices@lnk)",
]


@pytest.mark.parametrize("sql", REJECT_TABLES)
def test_reject_dictionary_views_dual_and_db_links(sql):
    with pytest.raises(TableNotAllowedError):
        oracle(sql)


def test_dual_can_be_allowed_explicitly():
    assert oracle("SELECT 1 FROM dual", allowed_tables={"customers", "dual"})


REJECT_TABLE_FUNCTIONS = [
    "SELECT * FROM TABLE(DBMS_XPLAN.DISPLAY)",
    "SELECT * FROM TABLE(my_pkg.f())",
    "SELECT * FROM XMLTABLE('/a' PASSING XMLTYPE('<a/>'))",
    "SELECT * FROM JSON_TABLE('[1]', '$[*]' COLUMNS (x NUMBER PATH '$'))",
]


@pytest.mark.parametrize("sql", REJECT_TABLE_FUNCTIONS)
def test_reject_table_valued_functions(sql):
    with pytest.raises(UnsafeQueryError):
        oracle(sql)


# ------------------------------------------------------------ sentencias no permitidas
REJECT_STATEMENTS = [
    "SELECT 1 FROM customers; DROP TABLE customers",
    "SELECT * FROM customers; SELECT * FROM invoices",
    "BEGIN EXECUTE IMMEDIATE 'DROP TABLE customers'; END;",
    "DECLARE v NUMBER; BEGIN v := 1; END;",
    "WITH FUNCTION f RETURN NUMBER IS BEGIN RETURN 1; END; SELECT f FROM customers",
    "CALL my_proc()",
    "ALTER SESSION SET CURRENT_SCHEMA = SYS",
    "COMMIT",
    "INSERT ALL INTO customers (customer_id) VALUES (1) SELECT 1 FROM customers",
    "MERGE INTO customers c USING dual d ON (1 = 1) WHEN MATCHED THEN UPDATE SET c.full_name = 'x'",
    "DELETE FROM customers",
    "UPDATE customers SET full_name = 'x'",
    "TRUNCATE TABLE customers",
    "DROP TABLE customers",
    "CREATE TABLE x AS SELECT * FROM customers",
    "GRANT SELECT ON customers TO PUBLIC",
    "LOCK TABLE customers IN EXCLUSIVE MODE",
    "SELECT * FROM customers FOR UPDATE",
    "SELECT * FROM customers FOR UPDATE NOWAIT",
    "SELECT * FROM customers FOR UPDATE SKIP LOCKED",
    "SELECT * FROM customers c FOR UPDATE OF c.customer_id",
    # No parsean con sqlglot: se rechazan por fail-closed (limitación documentada).
    "SELECT * FROM customers AS OF TIMESTAMP SYSTIMESTAMP - INTERVAL '1' DAY",
    "SELECT q'[x]' FROM customers",
    "SELECT * FROM customers VERSIONS BETWEEN SCN 1 AND 2",
    "SELECT * FROM customers WHERE customer_id = &1",
]


@pytest.mark.parametrize("sql", REJECT_STATEMENTS)
def test_reject_non_select_and_unparseable(sql):
    with pytest.raises(UnsafeQueryError):
        oracle(sql)


REJECT_BIND_VARIABLES = [
    "SELECT * FROM customers WHERE customer_id = :id",
    "SELECT * FROM customers WHERE customer_id = :1",
    "SELECT * FROM customers FETCH FIRST :n ROWS ONLY",
    "SELECT * FROM customers OFFSET :n ROWS",
]


@pytest.mark.parametrize("sql", REJECT_BIND_VARIABLES)
def test_reject_bind_variables(sql):
    # El modelo debe incrustar literales; una variable ligada no se puede acotar ni auditar.
    with pytest.raises(UnsafeQueryError):
        oracle(sql)


def test_huge_offset_is_rejected():
    with pytest.raises(UnsafeQueryError):
        oracle("SELECT * FROM customers ORDER BY 1 OFFSET 999999999 ROWS FETCH NEXT 5 ROWS ONLY")


REJECT_ROW_GENERATORS = [
    # CONNECT BY LEVEL <= N genera N filas (o N x filas de la tabla): bomba de recursos clásica.
    "SELECT * FROM customers CONNECT BY LEVEL <= 1000000000",
    "SELECT * FROM customers START WITH customer_id = 1 CONNECT BY PRIOR customer_id = customer_id",
]


@pytest.mark.parametrize("sql", REJECT_ROW_GENERATORS)
def test_reject_hierarchical_queries(sql):
    # Ninguna tabla de la lista blanca es jerárquica; se rechaza por defecto.
    with pytest.raises(UnsafeQueryError):
        oracle(sql)


# --------------------------------------------------------------- consultas legítimas
MUST_ACCEPT = [
    "SELECT customer_id, full_name FROM customers WHERE country = 'CO'",
    "SELECT * FROM customers",
    "SELECT * FROM CUSTOMERS",
    'SELECT "CUSTOMER_ID" FROM "CUSTOMERS"',
    "SELECT * FROM customers WHERE ROWNUM <= 5",
    "SELECT TRUNC(issued_date, 'MM'), SUM(amount) FROM invoices GROUP BY TRUNC(issued_date, 'MM')",
    "SELECT NVL(country, 'N/A'), COUNT(*) FROM customers GROUP BY NVL(country, 'N/A')",
    "SELECT TO_CHAR(issued_date, 'YYYY-MM'), SUM(amount) FROM invoices GROUP BY TO_CHAR(issued_date, 'YYYY-MM')",
    "SELECT LISTAGG(full_name, ', ') WITHIN GROUP (ORDER BY full_name) FROM customers",
    "SELECT * FROM invoices WHERE due_date < TRUNC(SYSDATE) - 30",
    "SELECT ADD_MONTHS(SYSDATE, -1) FROM customers",
    "SELECT MONTHS_BETWEEN(SYSDATE, issued_date) FROM invoices",
    "SELECT c.full_name FROM customers c, invoices i WHERE c.customer_id = i.customer_id(+)",
    "SELECT c.full_name, i.amount FROM customers c JOIN invoices i ON i.customer_id = c.customer_id",
    "WITH o AS (SELECT * FROM invoices WHERE status = 'overdue') SELECT COUNT(*) FROM o",
    "SELECT EXTRACT(YEAR FROM issued_date) FROM invoices",
    "SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM invoices i WHERE i.customer_id = c.customer_id)",
    "SELECT SUBSTR(email, 1, 3), LENGTH(email) FROM customers",
    (
        "SELECT NVL2(country, 1, 0), DECODE(status, 'paid', 1, 0) FROM invoices i, customers c "
        "WHERE c.customer_id = i.customer_id"
    ),
    "SELECT COUNT(*) OVER (PARTITION BY country) FROM customers",
    "SELECT * FROM customers WHERE REGEXP_LIKE(email, '^a')",
    "SELECT * FROM customers MINUS SELECT * FROM customers",
    "SELECT status, COUNT(*) FROM invoices GROUP BY status HAVING COUNT(*) > 1",
    "SELECT CASE WHEN status = 'paid' THEN 1 ELSE 0 END FROM invoices",
    "SELECT * FROM customers ORDER BY full_name FETCH FIRST 10 ROWS ONLY",
    "SELECT * FROM customers WHERE full_name = 'a' || CHR(39) || 'b'",
    "SELECT * FROM customers -- comentario inocente",
    "SELECT * FROM customers /* comentario inocente */",
    "SELECT * FROM customers;",
]


@pytest.mark.parametrize("sql", MUST_ACCEPT)
def test_accept_legitimate_oracle_select(sql):
    out = oracle(sql)
    assert out.upper().lstrip().startswith(("SELECT", "WITH"))
    assert re.search(r"FETCH (FIRST|NEXT) \d+ ROWS ONLY\s*$", out), out
    assert "LIMIT" not in out.upper()


# -------------------------------------------------------------------- esquema (Oracle)
@pytest.mark.parametrize(
    "sql",
    ["SELECT * FROM sales.customers", "SELECT * FROM SALES.CUSTOMERS", 'SELECT * FROM "SALES"."CUSTOMERS"'],
)
def test_oracle_allowed_schema_is_accepted(sql):
    assert oracle(sql, allowed_schema="SALES")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM hr.customers",
        "SELECT * FROM sys.customers",
        "SELECT * FROM public.customers",
        "SELECT * FROM sales.hr.customers",
        "SELECT * FROM sales.customers@lnk",
    ],
)
def test_oracle_other_schemas_are_rejected(sql):
    with pytest.raises(TableNotAllowedError):
        oracle(sql, allowed_schema="SALES")


def test_oracle_qualified_names_need_an_explicit_schema():
    # Con el valor por defecto de ALLOWED_SCHEMA ('public') ningún esquema Oracle coincide.
    with pytest.raises(TableNotAllowedError):
        oracle("SELECT * FROM sales.customers")
    assert oracle("SELECT * FROM customers")


# --------------------------------------------------------------------- límite de filas
def test_fetch_first_is_added_when_missing():
    out = oracle("SELECT * FROM customers")
    assert re.search(r"FETCH FIRST 100 ROWS ONLY\s*$", out)
    assert "LIMIT" not in out.upper()


def test_custom_max_rows():
    assert re.search(r"FETCH FIRST 10 ROWS ONLY\s*$", oracle("SELECT * FROM customers", max_rows=10))


def test_literal_fetch_within_the_cap_is_kept():
    assert re.search(r"FETCH (FIRST|NEXT) 5 ROWS ONLY\s*$", oracle("SELECT * FROM customers FETCH FIRST 5 ROWS ONLY"))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM customers FETCH FIRST 5000 ROWS ONLY",
        "SELECT * FROM customers FETCH FIRST 101 ROWS ONLY",
        "SELECT * FROM customers ORDER BY 1 OFFSET 10 ROWS FETCH NEXT 5000 ROWS ONLY",
        "SELECT customer_id FROM customers UNION ALL SELECT customer_id FROM invoices FETCH FIRST 5000 ROWS ONLY",
        "SELECT * FROM (SELECT * FROM customers FETCH FIRST 5000 ROWS ONLY)",
    ],
)
def test_fetch_above_the_cap_cannot_bypass_it(sql):
    assert re.search(r"FETCH (FIRST|NEXT) 100 ROWS ONLY\s*$", oracle(sql))


def test_percent_fetch_is_replaced_by_an_absolute_cap():
    # 10 PERCENT de un millón de filas serían 100.000: un porcentaje no acota nada.
    out = oracle("SELECT * FROM customers FETCH FIRST 10 PERCENT ROWS ONLY")
    assert "PERCENT" not in out.upper()
    assert re.search(r"FETCH (FIRST|NEXT) 100 ROWS ONLY\s*$", out)


def test_with_ties_is_replaced_by_rows_only():
    # WITH TIES devuelve más de N filas cuando hay empates.
    out = oracle("SELECT * FROM customers ORDER BY 1 FETCH FIRST 5 ROWS WITH TIES")
    assert "TIES" not in out.upper()
    assert re.search(r"FETCH (FIRST|NEXT) 5 ROWS ONLY\s*$", out)


def test_offset_is_preserved_next_to_the_fetch():
    out = oracle("SELECT * FROM customers ORDER BY 1 OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY")
    assert "OFFSET 10 ROWS" in out.upper()
    assert re.search(r"FETCH (FIRST|NEXT) 5 ROWS ONLY\s*$", out)


# ------------------------------------------------------------------------------ hints
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT /*+ PARALLEL(c,64) */ * FROM customers c",
        "SELECT /*+ FULL(c) RESULT_CACHE */ * FROM customers c",
        (
            "SELECT /*+ PARALLEL(c,64) */ COUNT(*) FROM customers c "
            "WHERE c.customer_id IN (SELECT /*+ FULL(i) */ customer_id FROM invoices i)"
        ),
    ],
)
def test_optimizer_hints_are_stripped(sql):
    out = oracle(sql)
    assert "/*+" not in out
    assert "PARALLEL" not in out.upper()
    assert "FULL(" not in out.upper()


# ------------------------------------------------------------------ selección de dialecto
def test_default_dialect_is_postgres_and_unchanged():
    assert settings.target_dialect == "postgres"
    assert re.search(r"LIMIT 100\s*$", validate_and_prepare("SELECT * FROM customers", 100))


def test_explicit_postgres_dialect_matches_the_default():
    assert re.search(
        r"LIMIT 100\s*$", validate_and_prepare("SELECT * FROM customers", 100, dialect="postgres")
    )


def test_dialect_comes_from_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    assert re.search(r"FETCH FIRST 100 ROWS ONLY\s*$", validate_and_prepare("SELECT * FROM customers", 100))
    with pytest.raises(DangerousFunctionError):
        validate_and_prepare("SELECT DBMS_LOCK.SLEEP(1) FROM customers", 100)


def test_explicit_dialect_overrides_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "target_dialect", "oracle")
    assert re.search(
        r"LIMIT 100\s*$", validate_and_prepare("SELECT * FROM customers", 100, dialect="postgres")
    )


@pytest.mark.parametrize("bad", ["mysql", "ORACLE ", "", "oracle;drop"])
def test_unknown_dialect_is_rejected(bad):
    with pytest.raises(ValueError):
        validate_and_prepare("SELECT * FROM customers", 100, dialect=bad)


def test_dialect_name_is_case_insensitive():
    assert re.search(r"FETCH FIRST 100 ROWS ONLY\s*$", validate_and_prepare("SELECT * FROM customers", 100, dialect="Oracle"))
