"""
Política de funciones del firewall: lista negra (por defecto, sin cambios) o lista blanca (opt-in).

NOTES.md documenta la limitación de la lista negra: una función nueva o poco común puede pasar. Con
`FUNCTION_POLICY=allowlist` solo se aceptan las funciones de `ALLOWED_FUNCTIONS` (más las de
`ALLOWED_FUNCTIONS_EXTRA`, separadas por comas). La lista negra SIGUE corriendo primero, también en este modo.
El valor por defecto (`denylist`) no cambia ningún comportamiento actual.
"""

import pytest

from app.core import safety
from app.core.safety import (
    DangerousFunctionError,
    UnsafeQueryError,
    validate_and_prepare,
    validate_ast,
)
from tests.test_safety_adversarial import REPORT_FUNCTIONS

# Construcciones estructurales de SQL que sqlglot modela como funciones (Cast, Case, If, Exists, Any...) o que
# acompañan a las funciones de reportes. El modo allowlist NO debe estorbarlas.
ESTRUCTURALES = [
    "SELECT CASE WHEN amount > 100 THEN 'alto' ELSE 'bajo' END FROM invoices",
    "SELECT CAST(amount AS numeric) FROM invoices",
    "SELECT amount::numeric FROM invoices",
    "SELECT amount::text || '-' || status FROM invoices",
    "SELECT * FROM invoices WHERE EXISTS (SELECT 1 FROM payments WHERE payments.invoice_id = invoices.id)",
    "SELECT * FROM invoices WHERE customer_id IN (SELECT id FROM customers)",
    "SELECT * FROM invoices WHERE amount BETWEEN 10 AND 20",
    "SELECT * FROM invoices WHERE due_date IS NULL",
    "SELECT * FROM invoices WHERE status LIKE 'pa%'",
    "SELECT * FROM invoices WHERE status ILIKE 'PA%'",
    "SELECT * FROM invoices WHERE due_date < now() - interval '30 days'",
    "SELECT * FROM invoices WHERE due_date < current_date",
    "SELECT * FROM invoices WHERE amount > ANY (ARRAY[1, 2, 3])",
    "SELECT date '2024-01-01' FROM invoices",
    "SELECT count(*) FILTER (WHERE amount > 100) FROM invoices",
    "WITH t AS (SELECT customer_id, sum(amount) AS total FROM invoices GROUP BY customer_id) SELECT * FROM t",
    "SELECT id FROM invoices UNION SELECT id FROM payments",
    "SELECT customer_id, sum(amount) AS total FROM invoices GROUP BY customer_id HAVING sum(amount) > 100 ORDER BY total DESC",
    # generate_series en FROM (series de fechas de los reportes): sqlglot la nombra «exploding_generate_series».
    "SELECT * FROM generate_series(1, 3)",
    "SELECT d::date FROM generate_series('2024-01-01'::date, '2024-03-01'::date, interval '1 month') AS d",
    "SELECT i.id, g FROM invoices i CROSS JOIN generate_series(1, 3) AS g",
]

DESCONOCIDAS = [
    "SELECT mi_funcion_rara(1) FROM invoices",
    "SELECT MI_FUNCION_RARA(1) FROM invoices",
    "SELECT public.mi_funcion_rara(1) FROM invoices",
    "SELECT * FROM invoices WHERE mi_funcion_rara(amount) > 1",
    "SELECT * FROM (SELECT mi_funcion_rara(amount) AS x FROM invoices) t",
    "WITH t AS (SELECT mi_funcion_rara(amount) AS x FROM invoices) SELECT * FROM t",
    "SELECT sum(mi_funcion_rara(amount)) FROM invoices",
    "SELECT id FROM invoices UNION SELECT mi_funcion_rara(id) FROM payments",
    "SELECT amount FROM invoices ORDER BY mi_funcion_rara(amount)",
]


# Funciones que sqlglot TIPA (no son Anonymous) y que una lista mínima de reportes no incluye: la lista blanca no puede
# mirar solo las funciones anónimas.
TIPADAS_NO_PERMITIDAS = ["ln(amount)", "chr(65)", "exp(amount)"]


@pytest.fixture
def allowlist(monkeypatch):
    monkeypatch.setenv("FUNCTION_POLICY", "allowlist")
    monkeypatch.delenv("ALLOWED_FUNCTIONS_EXTRA", raising=False)


@pytest.fixture(autouse=True)
def sin_politica_por_defecto(monkeypatch):
    monkeypatch.delenv("FUNCTION_POLICY", raising=False)
    monkeypatch.delenv("ALLOWED_FUNCTIONS_EXTRA", raising=False)


# ----------------------------------------------------------------------------------- por defecto: nada cambia

@pytest.mark.parametrize("sql", DESCONOCIDAS)
def test_por_defecto_una_funcion_desconocida_sigue_pasando(sql):
    assert validate_ast(sql) is not None


@pytest.mark.parametrize("valor", ["denylist", "DENYLIST", " denylist "])
def test_denylist_explicito_es_lo_mismo_que_el_defecto(monkeypatch, valor):
    monkeypatch.setenv("FUNCTION_POLICY", valor)
    assert validate_ast("SELECT mi_funcion_rara(1) FROM invoices") is not None
    with pytest.raises(DangerousFunctionError):
        validate_ast("SELECT pg_sleep(1) FROM invoices")


# ----------------------------------------------------------------------------------- allowlist

@pytest.mark.parametrize("sql", DESCONOCIDAS)
def test_allowlist_rechaza_una_funcion_desconocida_donde_este(allowlist, sql):
    with pytest.raises(DangerousFunctionError, match="mi_funcion_rara"):
        validate_ast(sql)


@pytest.mark.parametrize("expr", TIPADAS_NO_PERMITIDAS)
def test_allowlist_rechaza_tambien_las_funciones_tipadas_que_no_estan_en_la_lista(allowlist, expr):
    with pytest.raises(DangerousFunctionError):
        validate_ast(f"SELECT {expr} FROM invoices")


@pytest.mark.parametrize("expr", TIPADAS_NO_PERMITIDAS)
def test_las_tipadas_de_arriba_pasan_por_defecto(expr):
    # Control: sin la política allowlist siguen aceptándose.
    assert validate_ast(f"SELECT {expr} FROM invoices") is not None


@pytest.mark.parametrize("expr", REPORT_FUNCTIONS)
def test_allowlist_acepta_las_funciones_de_reportes(allowlist, expr):
    assert validate_ast(f"SELECT {expr} FROM invoices") is not None


@pytest.mark.parametrize("sql", ESTRUCTURALES)
def test_allowlist_acepta_las_construcciones_estructurales(allowlist, sql):
    assert validate_ast(sql) is not None


@pytest.mark.parametrize("sql", ESTRUCTURALES)
def test_las_construcciones_estructurales_ya_pasaban_por_defecto(sql):
    # Control: si esto fallara, el fallo del modo allowlist no sería de la lista blanca.
    assert validate_ast(sql) is not None


@pytest.mark.parametrize("function", ["pg_sleep", "pg_read_file", "dblink", "set_config", "lo_import", "version", "current_user"])
def test_allowlist_sigue_aplicando_la_lista_negra(allowlist, function):
    with pytest.raises(DangerousFunctionError):
        validate_ast(f"SELECT {function}(1) FROM invoices")


def test_allowlist_tambien_aplica_en_validate_and_prepare(allowlist):
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare("SELECT mi_funcion_rara(1) FROM invoices", max_rows=100)
    assert validate_and_prepare("SELECT sum(amount) FROM invoices", max_rows=100)


@pytest.mark.parametrize("valor", ["allowlist", "ALLOWLIST", "  AllowList  "])
def test_el_valor_de_la_politica_no_distingue_mayusculas_ni_espacios(monkeypatch, valor):
    monkeypatch.setenv("FUNCTION_POLICY", valor)
    with pytest.raises(DangerousFunctionError):
        validate_ast("SELECT mi_funcion_rara(1) FROM invoices")


# ----------------------------------------------------------------------------------- ALLOWED_FUNCTIONS_EXTRA

def test_extra_permite_las_funciones_nombradas_y_solo_esas(allowlist, monkeypatch):
    monkeypatch.setenv("ALLOWED_FUNCTIONS_EXTRA", "mi_funcion_rara, Otra_Funcion ,")
    assert validate_ast("SELECT mi_funcion_rara(1), otra_funcion(2) FROM invoices") is not None
    assert validate_ast("SELECT OTRA_FUNCION(2) FROM invoices") is not None
    with pytest.raises(DangerousFunctionError, match="tercera"):
        validate_ast("SELECT tercera(1) FROM invoices")


def test_extra_no_puede_reabrir_una_funcion_peligrosa(allowlist, monkeypatch):
    monkeypatch.setenv("ALLOWED_FUNCTIONS_EXTRA", "pg_sleep,dblink,version")
    for funcion in ("pg_sleep", "dblink", "version"):
        with pytest.raises(DangerousFunctionError):
            validate_ast(f"SELECT {funcion}(1) FROM invoices")


def test_extra_sin_la_politica_allowlist_no_hace_nada(monkeypatch):
    monkeypatch.setenv("ALLOWED_FUNCTIONS_EXTRA", "mi_funcion_rara")
    assert validate_ast("SELECT mi_funcion_rara(1) FROM invoices") is not None
    assert validate_ast("SELECT otra_cosa(1) FROM invoices") is not None


# ----------------------------------------------------------------------------------- falla cerrado

@pytest.mark.parametrize("valor", ["blocklist", "allow", "1", "true", "allowlist,denylist"])
def test_una_politica_invalida_rechaza_todo(monkeypatch, valor):
    monkeypatch.setenv("FUNCTION_POLICY", valor)
    with pytest.raises(UnsafeQueryError):
        validate_ast("SELECT 1 FROM invoices")
    with pytest.raises(UnsafeQueryError):
        validate_and_prepare("SELECT sum(amount) FROM invoices", max_rows=100)


def test_una_politica_vacia_es_el_defecto(monkeypatch):
    monkeypatch.setenv("FUNCTION_POLICY", "")
    assert validate_ast("SELECT mi_funcion_rara(1) FROM invoices") is not None


# ----------------------------------------------------------------------------------- la constante

def test_allowed_functions_es_un_frozenset_en_minusculas_y_sin_funciones_peligrosas():
    allowed = safety.ALLOWED_FUNCTIONS
    assert isinstance(allowed, frozenset)
    assert allowed and all(isinstance(n, str) and n == n.lower() and n == n.strip() for n in allowed)
    assert allowed.isdisjoint(safety.DANGEROUS_FUNCTIONS)
    assert not any(n.startswith(safety.DANGEROUS_FUNCTION_PREFIXES) for n in allowed)
    assert not any(patron in n for n in allowed for patron in safety.DANGEROUS_FUNCTION_PATTERNS)
    assert {"sum", "count", "coalesce", "date_trunc", "lower"} <= allowed
    assert allowed.isdisjoint({"ln", "chr", "exp"})  # a propósito fuera: lista mínima de reportes
