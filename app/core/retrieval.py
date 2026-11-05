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

import logging
import time
from dataclasses import dataclass
from functools import lru_cache

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.core.db import _engine
from app.core.embeddings import embed_text

# Debe coincidir con schema_embeddings.embedding vector(384) en db/schema.sql
_EMBEDDING_DIM = 384
_last_fingerprint: str | None = None
_last_check_at: float | None = None
logger = logging.getLogger(__name__)


def schema_fingerprint() -> str:
    """Devuelve una huella barata del índice de esquema."""
    with _engine.connect() as conn:
        count, max_id = conn.execute(
            text("SELECT count(*), coalesce(max(id), 0) FROM schema_embeddings")
        ).one()
    return f"{count}:{max_id}"


def invalidate_if_reindexed(now: float | None = None) -> bool:
    """Limpia la caché de retrieval si cambió el índice desde el último chequeo."""
    global _last_fingerprint, _last_check_at

    interval = settings.schema_check_interval_seconds
    if interval <= 0:
        return False

    checked_at = time.monotonic() if now is None else now
    if _last_check_at is not None and checked_at - _last_check_at < interval:
        return False

    try:
        fingerprint = schema_fingerprint()
    except (SQLAlchemyError, OSError, ValueError, TypeError) as exc:
        logger.warning("No se pudo comprobar la huella del esquema (%s)", type(exc).__name__)
        return False

    changed = _last_fingerprint is not None and fingerprint != _last_fingerprint
    _last_check_at = checked_at
    _last_fingerprint = fingerprint
    if changed:
        retrieve_relevant_schema.cache_clear()
        return True
    return False


@dataclass(frozen=True)
class RetrievedSchema:
    context: str
    best_distance: float | None = None


@lru_cache(maxsize=256)
def retrieve_relevant_schema(question: str, top_k: int = 4) -> RetrievedSchema:
    """
    Devuelve un RetrievedSchema con el contexto de esquema más relevante para
    la pregunta dada y la menor distancia encontrada (best_distance).
    """
    question_embedding = embed_text(question)

    stmt = text(
        """
        SELECT object_name, object_type, description,
               embedding <=> :question_embedding AS distance
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

    context = "\n\n".join(
        f"### {row['object_type']}: {row['object_name']}\n{row['description']}"
        for row in rows
    )
    best_distance = min(float(row["distance"]) for row in rows) if rows else None

    return RetrievedSchema(context=context, best_distance=best_distance)
