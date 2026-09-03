"""
Dada una pregunta en lenguaje natural, busca en `schema_embeddings` los
fragmentos de esquema (tablas, columnas, ejemplos) más relevantes por
similitud de embeddings (distancia coseno con pgvector).

Maneja su propia conexión (no pasa por app.core.db.execute_select):
esa función está pensada para SQL crudo generado por el LLM, mientras
que esto es una query interna, fija y parametrizada con un tipo
pgvector — responsabilidades distintas.

top_k=4 validado empíricamente con scripts/check_retrieval.py: con
top_k=3, la pregunta "¿qué acciones de cobranza se hicieron sobre
facturas vencidas?" dejaba a collection_actions al borde de quedar
afuera del top-3 (superada por payments, que no aplica). Mejora futura
pendiente: curar data/schema_docs/tables.md con más señal semántica de
dominio (ej. mencionar "cobranza", "gestión de deuda" explícitamente
en la descripción de collection_actions) para que el retrieval sea
robusto sin depender de subir top_k.
"""

from sqlalchemy import bindparam, create_engine, text
from pgvector.sqlalchemy import Vector

from app.config import settings
from app.core.embeddings import embed_text

_engine = create_engine(settings.database_url)

# Debe coincidir con schema_embeddings.embedding vector(384) en db/schema.sql
_EMBEDDING_DIM = 384


def retrieve_relevant_schema(question: str, top_k: int = 4) -> str:
    """
    Devuelve un string con el contexto de esquema más relevante para
    la pregunta dada, para usar como contexto en el prompt del LLM.
    """
    question_embedding = embed_text(question)

    stmt = text(
        """
        SELECT object_name, object_type, description
        FROM schema_embeddings
        ORDER BY embedding <=> :question_embedding
        LIMIT :top_k
        """
    ).bindparams(bindparam("question_embedding", type_=Vector(_EMBEDDING_DIM)))

    with _engine.connect() as conn:
        rows = conn.execute(
            stmt,
            {"question_embedding": question_embedding, "top_k": top_k},
        ).mappings().all()

    return "\n\n".join(
        f"### {row['object_type']}: {row['object_name']}\n{row['description']}"
        for row in rows
    )
