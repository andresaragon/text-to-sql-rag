"""
Endpoint principal: recibe una pregunta en lenguaje natural y devuelve
el SQL generado, junto con el resultado de ejecutarlo.

Flujo:
  1. retrieve_relevant_schema(question)   -> contexto de esquema (RAG)
  2. generate_sql(question, contexto)     -> SQL generado por el LLM
  3. validate_and_prepare(sql)            -> validación de seguridad
  4. execute_select(sql)                  -> ejecución contra Postgres
"""

import re
import time

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.core.db import QueryExecutionError, QueryTimeoutError, execute_select
from app.core.retrieval import retrieve_relevant_schema
from app.core.safety import UnsafeQueryError, validate_and_prepare
from app.core.sql_generator import generate_sql

router = APIRouter()


class QuestionRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    sql: str
    rows: list[dict]
    row_count: int


@router.post("/query", response_model=QueryResponse)
def query(request: QuestionRequest, response: Response) -> QueryResponse:
    normalized_question = re.sub(r"\s+", " ", request.question.strip())
    if not normalized_question:
        raise HTTPException(status_code=422, detail="La pregunta no puede estar vacía.")
    if len(normalized_question) > settings.max_question_chars:
        raise HTTPException(
            status_code=422,
            detail=f"La pregunta excede el máximo de {settings.max_question_chars} caracteres.",
        )

    t0 = time.perf_counter()
    try:
        schema = retrieve_relevant_schema(normalized_question)
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Base de datos inalcanzable durante el retrieval: {exc}",
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
    raw_sql = generate_sql(normalized_question, schema.context)
    t_llm = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        safe_sql = validate_and_prepare(raw_sql, settings.max_rows_returned)
    except UnsafeQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    t_validate = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        rows = execute_select(safe_sql)
    except QueryTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except QueryExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    t_db = (time.perf_counter() - t0) * 1000

    response.headers["Server-Timing"] = (
        f"retrieval;dur={t_retrieval:.1f}, "
        f"llm;dur={t_llm:.1f}, "
        f"validate;dur={t_validate:.1f}, "
        f"db;dur={t_db:.1f}"
    )

    return QueryResponse(sql=safe_sql, rows=rows, row_count=len(rows))
