"""
Endpoint principal: recibe una pregunta en lenguaje natural y devuelve
el SQL generado, junto con el resultado de ejecutarlo.

Flujo:
  0. QuestionRequest                      -> normaliza espacios; vacía o larga = 422
  1. retrieve_relevant_schema(question)   -> contexto de esquema (RAG) + distancia;
                                             base caída o índice vacío = 503,
                                             fuera del dominio = 422 (sin llamar al LLM)
  2. generate_sql(question, contexto)     -> SQL generado por el LLM
  3. validate_and_prepare(sql)            -> validación de seguridad (400)
  4. execute_select(sql)                  -> ejecución contra Postgres (timeout 504, error 400)

Un pool de conexiones agotado (sqlalchemy.exc.TimeoutError) responde 503 en
las etapas 1 y 4.

Cada respuesta 200 lleva un header Server-Timing con la duración de las 4 etapas.
"""

import re
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.config import settings
from app.core.db import QueryExecutionError, QueryTimeoutError, execute_select
from app.core.retrieval import retrieve_relevant_schema
from app.core.safety import UnsafeQueryError, validate_and_prepare
from app.core.sql_generator import generate_sql

router = APIRouter()

_WHITESPACE_RE = re.compile(r"\s+")


class QuestionRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        # Colapsa espacios para que variantes de la misma pregunta compartan
        # cache; no toca mayúsculas ni acentos porque los literales llegan al SQL.
        normalized = _WHITESPACE_RE.sub(" ", v.strip())
        if not normalized:
            raise ValueError("La pregunta no puede estar vacía")
        if len(normalized) > settings.max_question_chars:
            raise ValueError(
                f"La pregunta excede el máximo de {settings.max_question_chars} caracteres"
            )
        return normalized


class QueryResponse(BaseModel):
    sql: str
    rows: list[dict]
    row_count: int


@router.post("/query", response_model=QueryResponse)
def query(request: QuestionRequest, response: Response) -> QueryResponse:
    t0 = time.perf_counter()
    try:
        schema = retrieve_relevant_schema(request.question)
    except (OperationalError, PoolTimeoutError) as exc:
        # Base caída o pool agotado. El detalle de psycopg2 (host, puerto) no se
        # devuelve al cliente.
        raise HTTPException(
            status_code=503, detail="Base de datos no disponible."
        ) from exc
    t_retrieval = (time.perf_counter() - t0) * 1000

    if schema.best_distance is None:
        raise HTTPException(
            status_code=503,
            detail="No se encontraron esquemas relevantes (índice vacío).",
        )
    if schema.best_distance > settings.max_schema_distance:
        raise HTTPException(
            status_code=422,
            detail="Pregunta fuera del dominio de la base de datos.",
        )

    t0 = time.perf_counter()
    raw_sql = generate_sql(request.question, schema.context)
    t_llm = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        safe_sql = validate_and_prepare(raw_sql, settings.max_rows_returned)
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    t_validate = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        rows = execute_select(safe_sql)
    except PoolTimeoutError as e:
        raise HTTPException(
            status_code=503, detail="Base de datos no disponible."
        ) from e
    except QueryTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e)) from e
    except QueryExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    t_db = (time.perf_counter() - t0) * 1000

    response.headers["Server-Timing"] = (
        f"retrieval;dur={t_retrieval:.1f}, "
        f"llm;dur={t_llm:.1f}, "
        f"validate;dur={t_validate:.1f}, "
        f"db;dur={t_db:.1f}"
    )
    return QueryResponse(sql=safe_sql, rows=rows, row_count=len(rows))
