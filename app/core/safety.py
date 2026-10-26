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

ORACLE_DANGEROUS_FUNCTIONS = {
    "sys_context", "userenv", "xmltype", "extractvalue", "xmlquery",
    "xmlsequence", "httpuritype", "uritype", "dburitype", "xdburitype",
    "dbms_random", "rand",
}
ORACLE_SEQUENCE_PSEUDOCOLUMNS = {"nextval", "currval"}
ORACLE_IDENTITY_PSEUDOCOLUMNS = {
    "user", "uid", "ora_database_name", "ora_login_user", "ora_instance_num", "ora_client_ip_address",
}

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


def _resolve_dialect(dialect: str | None) -> str:
    resolved = settings.target_dialect if dialect is None else dialect
    if isinstance(resolved, str) and resolved.lower() in {"postgres", "oracle"}:
        return resolved.lower()
    raise ValueError(f"Dialecto no soportado: {resolved!r}")


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


def check_oracle_safety(statement: exp.Expression) -> None:
    """Aplica restricciones específicas del dialecto Oracle."""
    for dot in statement.find_all(exp.Dot):
        if isinstance(dot.expression, exp.Func):
            raise DangerousFunctionError("No se permiten llamadas a funciones calificadas en Oracle")

    for func in statement.find_all(exp.Func):
        raw_name = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        func_name = (raw_name or "").strip('"').lower()
        if func_name in ORACLE_DANGEROUS_FUNCTIONS:
            raise DangerousFunctionError(f"Función bloqueada por seguridad: '{func_name}'")

    # Tablas y alias de tabla declarados. Los alias de COLUMNA no cuentan: `SELECT 1 AS pkg, pkg.f`
    # seguiría llamando al paquete `pkg`.
    declared: set[str] = set()
    for node in statement.walk():
        if isinstance(node, exp.Table) and node.name:
            declared.add(node.name.lower())
            declared.add(node.alias_or_name.lower())
        elif isinstance(node, (exp.Subquery, exp.CTE)) and node.alias:
            declared.add(node.alias.lower())

    for column in statement.find_all(exp.Column):
        # Una función de paquete sin argumentos se llama sin paréntesis (UTL_INADDR.GET_HOST_NAME) y
        # sqlglot la parsea como columna calificada: si el calificador no es una tabla ni un alias
        # declarados en la consulta, es un paquete.
        if column.table and column.table.lower() not in declared:
            raise DangerousFunctionError(
                f"Función bloqueada por seguridad: calificador no declarado '{column.table}'"
            )
        column_name = (column.name or "").strip('"').lower()
        if column_name in ORACLE_SEQUENCE_PSEUDOCOLUMNS:
            raise DangerousFunctionError(f"Pseudocolumna bloqueada por seguridad: '{column_name}'")
        if not column.table and column_name in ORACLE_IDENTITY_PSEUDOCOLUMNS:
            raise DangerousFunctionError(f"Pseudocolumna bloqueada por seguridad: '{column_name}'")

    for table in statement.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeQueryError("No se permiten funciones de tabla en Oracle")

    # XMLTYPE también se puede construir con CAST(... AS XMLTYPE), sin pasar por la función.
    for data_type in statement.find_all(exp.DataType):
        if data_type.sql(dialect="oracle").upper().startswith("XMLTYPE"):
            raise DangerousFunctionError("Tipo bloqueado por seguridad: 'xmltype'")

    # CONNECT BY LEVEL <= N es un generador de filas (bomba de recursos) y ninguna tabla de la lista
    # blanca es jerárquica: se rechaza por defecto.
    if statement.find(exp.Connect) is not None:
        raise UnsafeQueryError("No se permiten consultas jerárquicas (CONNECT BY) en Oracle")

    if any(True for _ in statement.find_all((exp.Placeholder, exp.Parameter))):
        raise UnsafeQueryError("No se permiten variables ligadas en Oracle")


def check_offset_limit(statement: exp.Expression) -> None:
    """Verifica que todo OFFSET del AST sea un entero no negativo menor o igual a MAX_OFFSET."""
    for offset in statement.find_all(exp.Offset):
        value = offset.expression
        # Un valor negativo (Neg), un parámetro o una expresión no literal se rechaza
        # porque no se puede acotar de forma determinística.
        if not (isinstance(value, exp.Literal) and value.is_int and 0 <= int(value.this) <= MAX_OFFSET):
            raise UnsafeQueryError(f"OFFSET excede el máximo permitido ({MAX_OFFSET})")


def validate_ast(
    sql: str, allowed_tables: set[str] | None = None, allowed_schema: str | None = None,
    dialect: str | None = None,
) -> exp.Select:
    """
    Parsea y valida el AST de la consulta contra todas las reglas del cortafuegos semántico.
    Devuelve el objeto AST parseado si pasa todas las validaciones.
    """
    if not isinstance(sql, str):
        raise UnsafeQueryError("La consulta debe ser texto (str)")

    dialect = _resolve_dialect(dialect)

    if allowed_tables is None:
        allowed_tables = DEFAULT_ALLOWED_TABLES
    if allowed_schema is None:
        allowed_schema = settings.allowed_schema

    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
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
        if dialect == "oracle":
            check_oracle_safety(statement)
        check_offset_limit(statement)
    except UnsafeQueryError:
        raise
    except Exception as err:
        raise UnsafeQueryError(f"Error al parsear SQL: {type(err).__name__}") from err

    return statement


def enforce_limit(sql: str, max_rows: int, dialect: str | None = None) -> str:
    """Agrega o normaliza el límite de filas usando el dialecto seleccionado."""
    dialect = _resolve_dialect(dialect)
    statement = sqlglot.parse_one(sql, dialect=dialect)

    if dialect == "oracle":
        for select in statement.find_all(exp.Select):
            select.set("hint", None)
        if isinstance(statement, exp.Select):
            statement.set("hint", None)
        existing_limit = statement.args.get("limit")
        if isinstance(existing_limit, exp.Fetch):
            count = existing_limit.args.get("count")
            usable = isinstance(count, exp.Literal) and count.is_int
            try:
                count_value = int(count.this) if usable else None
            except (ValueError, TypeError):
                count_value = None

            limit_options = existing_limit.args.get("limit_options")
            has_percent = bool(existing_limit.args.get("percent"))
            unrecognized_option = False

            if limit_options is not None:
                if isinstance(limit_options, exp.Expression):
                    if limit_options.args.get("percent"):
                        has_percent = True
                    known_lo_keys = {"percent", "rows", "with_ties"}
                    if any(
                        v is not None and v is not False
                        for k, v in limit_options.args.items()
                        if k not in known_lo_keys
                    ):
                        unrecognized_option = True
                else:
                    unrecognized_option = True

            known_fetch_keys = {"direction", "count", "percent", "with_ties", "limit_options"}
            if any(
                v is not None and v is not False
                for k, v in existing_limit.args.items()
                if k not in known_fetch_keys
            ):
                unrecognized_option = True

            if (
                not usable
                or count_value is None
                or count_value > max_rows
                or has_percent
                or unrecognized_option
            ):
                count = exp.Literal.number(max_rows)

            existing_limit.set("count", count)
            existing_limit.set("percent", False)
            existing_limit.set("with_ties", False)
            if isinstance(limit_options, exp.Expression):
                limit_options.set("percent", False)
                limit_options.set("with_ties", False)
        else:
            # Sin límite, o con uno que no es un FETCH reconocible: se aplica el tope (fail-closed).
            statement.set("limit", exp.Fetch(direction="FIRST", count=exp.Literal.number(max_rows)))
        return statement.sql(dialect=dialect)

    existing_limit = statement.args.get("limit")
    if existing_limit is not None:
        try:
            current_value = int(existing_limit.expression.this)
            if current_value <= max_rows:
                return statement.sql(dialect=dialect)
        except (ValueError, TypeError, AttributeError):
            # Si el LIMIT es 'ALL', 'NULL' o una expresión no entera, se sobreescribe de forma segura
            pass

    statement = statement.limit(max_rows)
    return statement.sql(dialect=dialect)



def validate_and_prepare(
    sql: str, max_rows: int, allowed_tables: set[str] | None = None, allowed_schema: str | None = None,
    dialect: str | None = None,
) -> str:
    """Punto de entrada único: valida el AST contra el cortafuegos y aplica el límite seguro."""
    dialect = _resolve_dialect(dialect)
    statement = validate_ast(sql, allowed_tables, allowed_schema, dialect)
    try:
        return enforce_limit(statement.sql(dialect=dialect), max_rows, dialect)
    except UnsafeQueryError:
        raise
    except Exception as err:
        raise UnsafeQueryError(f"Error al parsear SQL: {type(err).__name__}") from err
