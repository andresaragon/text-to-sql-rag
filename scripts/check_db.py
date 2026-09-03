"""
Script exploratorio (no es un test de pytest) para verificar el flujo
completo: generar un embedding, guardarlo en Postgres/pgvector, leerlo
de vuelta, y confirmar que todo coincide.

Uso:
    python scripts/check_db.py

Requiere que el contenedor de Postgres con pgvector esté corriendo
(ver docker ps) y que DATABASE_URL apunte a él.
"""

from app.core.db import execute_select, save_schema_embedding
from app.core.embeddings import embed_text

# Constante hardcodeada, no input de usuario -> es seguro interpolarla
# directamente en el SQL. execute_select() no acepta bind params porque
# está pensada para correr SQL ya validado (por safety.py) tal cual llega.
TEST_OBJECT_NAME = "test_check"


def main():
    print("=== 1. Generando embedding de prueba ===")
    texto = "prueba de conexión a la base de datos"
    embedding = embed_text(texto)
    print(f"  texto:      {texto!r}")
    print(f"  dimensión:  {len(embedding)}")
    print(f"  primeros 5: {embedding[:5]}\n")

    print("=== 2. Guardando en schema_embeddings ===")
    save_schema_embedding(
        object_name=TEST_OBJECT_NAME,
        object_type="test",
        description=texto,
        embedding=embedding,
    )
    print(f"  guardado con object_name={TEST_OBJECT_NAME!r}\n")

    print("=== 3. Leyendo de vuelta con execute_select() ===")
    rows = execute_select(
        f"""
        SELECT object_name, object_type, description, vector_dims(embedding) AS dim
        FROM schema_embeddings
        WHERE object_name = '{TEST_OBJECT_NAME}'
        """
    )
    print(f"  filas encontradas: {len(rows)}")
    for row in rows:
        print(f"  {row}")
    print()

    print("=== 4. Verificación ===")
    assert len(rows) == 1, f"esperaba exactamente 1 fila, encontré {len(rows)}"
    row = rows[0]
    print(f"  description guardada = {texto!r}")
    print(f"  description leída    = {row['description']!r}")
    print(f"  ¿coinciden?           = {row['description'] == texto}")
    print(f"  dimensión leída (dim) = {row['dim']} (debería ser 384)")
    print(f"  ¿dimensión correcta?  = {row['dim'] == 384}\n")

    print("=== 5. Borrando fila de prueba ===")
    deleted = execute_select(
        f"""
        DELETE FROM schema_embeddings
        WHERE object_name = '{TEST_OBJECT_NAME}'
        RETURNING object_name
        """
    )
    print(f"  filas borradas: {len(deleted)} -> {deleted}")


if __name__ == "__main__":
    main()
