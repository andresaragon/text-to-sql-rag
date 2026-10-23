"""Generadores de SQL y reindexado para el benchmark A/B."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import scripts.index_schema
from app.config import settings
from app.core.retrieval import retrieve_relevant_schema
from app.core.sql_generator import generate_sql


class GoldGenerator:
    """Generador que devuelve la consulta SQL de referencia para el dialecto indicado."""

    def __init__(self, questions: Sequence[dict[str, Any]]) -> None:
        self.questions = questions

    def __call__(self, model: str, dialect: str, question: str) -> str | None:
        for q in self.questions:
            if q["question"] == question:
                return q["sql"][dialect]
        return None


class WrongGenerator:
    """Generador que siempre devuelve una consulta equivocada."""

    def __call__(self, model: str, dialect: str, question: str) -> str:
        return "SELECT 1"


class OllamaGenerator:
    """Generador basado en Ollama con RAG dinámico y limpieza de cachés."""

    def __call__(self, model: str, dialect: str, question: str) -> str | None:
        retrieve_relevant_schema.cache_clear()
        retrieved = retrieve_relevant_schema(question)

        if retrieved.best_distance is None or retrieved.best_distance > settings.max_schema_distance:
            return None

        before_model = settings.ollama_model
        try:
            settings.ollama_model = model
            generate_sql.cache_clear()
            return generate_sql(question, retrieved.context, dialect)
        finally:
            settings.ollama_model = before_model


def reindex(dialect: str) -> None:
    """Reindexa el esquema para el dialecto indicado y limpia la caché de retrieval."""
    before_dialect = settings.target_dialect
    try:
        settings.target_dialect = dialect
        scripts.index_schema.main()
    finally:
        settings.target_dialect = before_dialect
        retrieve_relevant_schema.cache_clear()
