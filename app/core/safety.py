"""
Valida el SQL generado por el LLM antes de ejecutarlo contra la base
de datos real. Implementa un Cortafuegos Semántico AST (Guardrail Determinístico).

Reglas duras de seguridad:
1. Solo se permite una única sentencia SELECT (o WITH ... SELECT).
2. Prohibido: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, GRANT, cualquier DDL/DML.
3. Se debe poder parsear con sqlglot en dialecto postgres (si no parsea, se rechaza).
4. Lista blanca de tablas y esquema: solo se permiten tablas autorizadas sin calificar
   o en el esquema configurado; las referencias con catálogo se rechazan.
   Bloquea acceso a catálogos del sistema (pg_shadow, pg_authid, information_schema, etc.)
   y tablas internas del sistema RAG (schema_embeddings).
5. Lista negra de funciones peligrosas: bloquea funciones de exfiltración o DoS (pg_sleep,
   pg_read_file, dblink, etc.).
6. Se agrega un LIMIT si el modelo no lo incluyó, o se recorta si el que trae supera max_rows.

Fuera de alcance, por diseño: este módulo valida seguridad sintáctica y
estructural (tipo de sentencia, tablas autorizadas y funciones del sistema), no
corrección semántica de si un filtro literal responde a la pregunta de negocio
(ej. umbrales o fechas alucinadas). Ver app/core/sql_generator.py.
"""



import sqlglot
from sqlglot import exp

from app.config import settings

DEFAULT_ALLOWED_TABLES: set[str] = {
    "customers",
    "invoices",
    "payments",
    "collection_actions",
}

DANGEROUS_FUNCTIONS: set[str] = {
    "pg_sleep",
    "pg_read_file",
    "pg_write_file",
    "pg_read_binary_file",
    "query_to_xml",
    "current_setting",
    "set_config",
    "dblink",
    "dblink_exec",
    "pg_terminate_backend",
    "pg_reload_conf",
    "pg_tablespace_location",
    "version",
    "current_version",
    # Funciones de información del entorno: revelan identidad, base y red del servidor
    # (fuga de datos de entorno útil para ataques posteriores).
    "current_database",
    "current_user",
    "session_user",
    "current_schema",
    "current_schemas",
    "inet_server_addr",
    "inet_server_port",
    "inet_client_addr",
    "inet_client_port",
}

# Formas de palabra clave sin paréntesis que sqlglot parsea como columnas sin calificar
# (p. ej. "SELECT session_user"). Se bloquean igual que sus llamadas con paréntesis.
DANGEROUS_KEYWORD_COLUMNS: set[str] = {
    "current_user",
    "session_user",
    "current_schema",
}

# Se bloquean familias de funciones PostgreSQL peligrosas por prefijo o patrón,
# para cubrir variantes de acceso al sistema, large objects y ejecución remota.
DANGEROUS_FUNCTION_PREFIXES = ("pg_", "lo_", "txid_", "dblink")
DANGEROUS_FUNCTION_PATTERNS = ("_to_xml",)

# Tope para OFFSET: un desplazamiento enorme fuerza escaneos largos sobre la tabla
# (DoS leve). Se aplica a todos los nodos OFFSET del AST, incluidas subconsultas y CTEs.
MAX_OFFSET = 10_000


class UnsafeQueryError(Exception):
    """Se lanza cuando el SQL generado no pasa las validaciones de seguridad."""


class NonSelectQueryError(UnsafeQueryError):
    """Se lanza cuando la consulta no es una única sentencia SELECT o intenta DDL/DML."""


class TableNotAllowedError(UnsafeQueryError):
    """Se lanza cuando la consulta intenta acceder a tablas fuera de la lista blanca."""


class DangerousFunctionError(UnsafeQueryError):
    """Se lanza cuando la consulta intenta invocar funciones de sistema peligrosas."""


def is_safe_select(sql: str) -> bool:
    """Verifica que el SQL sea una única sentencia SELECT (o UNION), sin DDL/DML."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except Exception:  # noqa: BLE001 - Cortafuegos fail-closed ante cualquier error del parser
        return False

    if len(statements) != 1:
        return False

    return isinstance(statements[0], (exp.Select, exp.SetOperation))



def check_table_whitelist(statement: exp.Expression, allowed_tables: set[str], allowed_schema: str) -> None:
    """Verifica que todas las tablas referenciadas en el AST pertenezcan a la lista blanca."""
    cte_names = {cte.alias.lower() for cte in statement.find_all(exp.CTE) if cte.alias}
    allowed_names = {t.lower() for t in allowed_tables}
    unauthorized = set()
    for table in statement.find_all(exp.Table):
        name = (table.name or "").lower()
        # Las funciones de tabla (generate_series, pg_read_file...) aparecen como Table sin
        # nombre: no son tablas físicas y las revisa check_dangerous_functions.
        if not name:
            continue
        # Catálogos (a.b.c) no se permiten, incluso si coinciden los otros componentes.
        if table.catalog:
            unauthorized.add(name)
            continue
        if not table.db and name in cte_names:
            continue
        if name not in allowed_names or (table.db and table.db.lower() != allowed_schema.lower()):
            unauthorized.add(name)
    if unauthorized:
        raise TableNotAllowedError(
            f"Acceso denegado a tablas no autorizadas: {sorted(unauthorized)}. "
            f"Tablas permitidas: {sorted(allowed_tables)}"
        )


def check_dangerous_functions(statement: exp.Expression) -> None:
    """Verifica que el AST no contenga llamadas a funciones de sistema bloqueadas."""
    for func in statement.find_all(exp.Func):
        # Anonymous conserva el identificador escrito en SQL; las funciones
        # tipadas de sqlglot exponen su nombre SQL mediante sql_name().
        raw_name = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        func_name = (raw_name or "").strip('"').lower().rsplit(".", 1)[-1]
        blocked = (
            func_name in DANGEROUS_FUNCTIONS
            or func_name.startswith(DANGEROUS_FUNCTION_PREFIXES)
            or any(pattern in func_name for pattern in DANGEROUS_FUNCTION_PATTERNS)
        )
        if blocked:
            raise DangerousFunctionError(
                f"Función bloqueada por seguridad: '{func_name}'"
            )

    # Las formas sin paréntesis llegan como columnas; una columna calificada (t.session_user)
    # es un identificador de tabla real y no la función del sistema.
    for column in statement.find_all(exp.Column):
        column_name = (column.name or "").lower()
        if not column.table and column_name in DANGEROUS_KEYWORD_COLUMNS:
            raise DangerousFunctionError(
                f"Función bloqueada por seguridad: '{column_name}'"
            )


def check_offset_limit(statement: exp.Expression) -> None:
    """Verifica que todo OFFSET del AST sea un entero no negativo menor o igual a MAX_OFFSET."""
    for offset in statement.find_all(exp.Offset):
        value = offset.expression
        # Un valor negativo (Neg), un parámetro o una expresión no literal se rechaza
        # porque no se puede acotar de forma determinística.
        if not (isinstance(value, exp.Literal) and value.is_int and 0 <= int(value.this) <= MAX_OFFSET):
            raise UnsafeQueryError(f"OFFSET excede el máximo permitido ({MAX_OFFSET})")


def validate_ast(sql: str, allowed_tables: set[str] | None = None, allowed_schema: str | None = None) -> exp.Select:
    """
    Parsea y valida el AST de la consulta contra todas las reglas del cortafuegos semántico.
    Devuelve el objeto AST parseado si pasa todas las validaciones.
    """
    if not isinstance(sql, str):
        raise UnsafeQueryError("La consulta debe ser texto (str)")

    if allowed_tables is None:
        allowed_tables = DEFAULT_ALLOWED_TABLES
    if allowed_schema is None:
        allowed_schema = settings.allowed_schema

    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except Exception as err:
        raise UnsafeQueryError(f"Error al parsear SQL: {type(err).__name__}") from err

    if len(statements) != 1:
        raise NonSelectQueryError(f"Se esperaba exactamente 1 sentencia, se recibieron {len(statements)}")

    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.SetOperation)):
        raise NonSelectQueryError(f"Solo se permiten sentencias SELECT o UNION. Tipo detectado: {type(statement).__name__}")

    try:
        for node in statement.walk():
            if isinstance(node, exp.Lock):
                raise NonSelectQueryError(
                    f"Solo se permiten consultas de solo lectura: se detectó {type(node).__name__}"
                )
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
                raise NonSelectQueryError(
                    f"Solo se permiten consultas de solo lectura: se detectó {type(node).__name__}"
                )
            if isinstance(node, exp.Select) and node.args.get("into") is not None:
                raise NonSelectQueryError(
                    "Solo se permiten consultas de solo lectura: se detectó SELECT INTO"
                )

        check_table_whitelist(statement, allowed_tables, allowed_schema)
        check_dangerous_functions(statement)
        check_offset_limit(statement)
    except UnsafeQueryError:
        raise
    except Exception as err:
        raise UnsafeQueryError(f"Error al parsear SQL: {type(err).__name__}") from err

    return statement


def enforce_limit(sql: str, max_rows: int) -> str:
    """Agrega un LIMIT si el SQL generado no tiene uno, o lo recorta si supera max_rows."""
    statement = sqlglot.parse_one(sql, dialect="postgres")

    existing_limit = statement.args.get("limit")
    if existing_limit is not None:
        try:
            current_value = int(existing_limit.expression.this)
            if current_value <= max_rows:
                return statement.sql(dialect="postgres")
        except (ValueError, TypeError, AttributeError):
            # Si el LIMIT es 'ALL', 'NULL' o una expresión no entera, se sobreescribe de forma segura
            pass

    statement = statement.limit(max_rows)
    return statement.sql(dialect="postgres")



def validate_and_prepare(
    sql: str, max_rows: int, allowed_tables: set[str] | None = None, allowed_schema: str | None = None
) -> str:
    """Punto de entrada único: valida el AST contra el cortafuegos y aplica el límite seguro."""
    statement = validate_ast(sql, allowed_tables, allowed_schema)
    try:
        return enforce_limit(statement.sql(dialect="postgres"), max_rows)
    except UnsafeQueryError:
        raise
    except Exception as err:
        raise UnsafeQueryError(f"Error al parsear SQL: {type(err).__name__}") from err
