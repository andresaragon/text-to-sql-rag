"""
Valida el SQL generado por el LLM antes de ejecutarlo contra la base
de datos real. Esta es la parte que demuestra criterio de ingeniería
backend, no solo "conectar un LLM y ya".

Reglas duras:
1. Solo se permite una única sentencia SELECT.
2. Prohibido: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, GRANT,
   cualquier DDL/DML.
3. Se debe poder parsear con sqlglot (si no parsea, se rechaza).
4. Se agrega un LIMIT si el modelo no lo incluyó, o se recorta si el
   que trae supera settings.max_rows_returned — max_rows_returned es
   un techo real, no solo un default que el LLM puede pisar poniendo
   un número más alto.

Fuera de alcance, por diseño: este módulo valida seguridad sintáctica/
estructural (qué tipo de sentencia es), no corrección semántica. No
puede detectar que el LLM haya alucinado un valor literal (ej. un
umbral de fecha) que no corresponde a la pregunta del usuario — eso
requeriría entender la pregunta en lenguaje natural, y is_safe_select()
ni siquiera la recibe como argumento. Ver la limitación documentada en
app/core/sql_generator.py.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


class UnsafeQueryError(Exception):
    """Se lanza cuando el SQL generado no pasa las validaciones de seguridad."""


def is_safe_select(sql: str) -> bool:
    """Verifica que el SQL sea una única sentencia SELECT, sin DDL/DML."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except SqlglotError:
        return False

    if len(statements) != 1:
        return False

    return isinstance(statements[0], exp.Select)


def enforce_limit(sql: str, max_rows: int) -> str:
    """Agrega un LIMIT si el SQL generado no tiene uno, o lo recorta si supera max_rows."""
    statement = sqlglot.parse_one(sql, dialect="postgres")

    existing_limit = statement.args.get("limit")
    if existing_limit is not None:
        current_value = int(existing_limit.expression.this)
        if current_value <= max_rows:
            return statement.sql(dialect="postgres")

    statement = statement.limit(max_rows)
    return statement.sql(dialect="postgres")


def validate_and_prepare(sql: str, max_rows: int) -> str:
    """Punto de entrada único: valida y prepara el SQL para ejecución segura."""
    if not is_safe_select(sql):
        raise UnsafeQueryError(f"Consulta rechazada por seguridad: {sql}")
    return enforce_limit(sql, max_rows)
