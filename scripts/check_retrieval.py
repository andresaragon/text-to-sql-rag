"""
Script exploratorio (no es un test de pytest) para ver qué trae el
retrieval por similitud para distintas preguntas, con top_k=3, y ver
la distancia coseno de cada resultado.

No usa retrieve_relevant_schema() directamente porque esa función solo
devuelve el string de contexto final ya concatenado -- acá necesitamos
ver el desglose (object_name, object_type, distancia) por candidato,
así que repetimos la misma query pero seleccionando también
`embedding <=> :question_embedding` en vez de descartarla.

Distancia coseno: 0 = idéntico, más alto = menos parecido. Cuanto más
baja, más "seguro" está el retrieval de que ese fragmento es relevante.

Uso:
    python scripts/check_retrieval.py
"""

from sqlalchemy import bindparam, create_engine, text
from pgvector.sqlalchemy import Vector

from app.config import settings
from app.core.embeddings import embed_text

TOP_K = 4

QUESTIONS = [
    "¿Cuántos clientes tienen facturas vencidas?",
    "¿Cuál es el monto total pagado por cada cliente?",
    "¿Qué acciones de cobranza se han hecho sobre facturas vencidas?",
    "¿Cuál es el color favorito de los empleados?",
]

_engine = create_engine(settings.database_url)
_EMBEDDING_DIM = 384

_STMT = text(
    """
    SELECT object_name, object_type, embedding <=> :question_embedding AS distance
    FROM schema_embeddings
    ORDER BY distance
    LIMIT :top_k
    """
).bindparams(bindparam("question_embedding", type_=Vector(_EMBEDDING_DIM)))


def check(question: str):
    embedding = embed_text(question)
    with _engine.connect() as conn:
        rows = conn.execute(
            _STMT, {"question_embedding": embedding, "top_k": TOP_K}
        ).mappings().all()

    print(f"Pregunta: {question!r}")
    for row in rows:
        print(
            f"  {row['object_type']:14s} {row['object_name']:20s} "
            f"distancia={row['distance']:.4f}"
        )
    print()


def main():
    for question in QUESTIONS:
        check(question)


if __name__ == "__main__":
    main()
