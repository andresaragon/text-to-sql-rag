"""
Genera embeddings de texto (descripciones del esquema, ejemplos de queries)
para poder buscar por similitud semántica antes de generar SQL.
"""

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import settings


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model)


def embed_text(text: str) -> list[float]:
    """Convierte un texto en un vector de embeddings."""
    return _get_model().encode(
        text, convert_to_numpy=True, normalize_embeddings=True
    ).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Versión batch de embed_text, más eficiente para indexar el esquema completo."""
    if not texts:
        return []
    return _get_model().encode(
        texts, convert_to_numpy=True, normalize_embeddings=True
    ).tolist()
