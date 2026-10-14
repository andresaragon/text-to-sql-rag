"""
Endpoint principal: recibe una pregunta en lenguaje natural y devuelve
el SQL generado, junto con el resultado de ejecutarlo.

Flujo:
  1. retrieve_relevant_schema(question)   -> contexto de esquema (RAG)
  2. generate_sql(question, contexto)     -> SQL generado por el LLM
  3. validate_and_prepare(sql)            -> validación de seguridad
  4. execute_select(sql)                  -> ejecución contra Postgres
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.config import settings
from app.core.db import QueryExecutionError, QueryTimeoutError, execute_select
from app.core.retrieval import retrieve_relevant_schema
from app.core.safety import UnsafeQueryError, validate_and_prepare
from app.core.sql_generator import generate_sql

router = APIRouter()


class QuestionRequest(BaseModel):
    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("La pregunta no puede estar vacía")
        if len(trimmed) > settings.max_question_chars:
            raise ValueError(
                f"La pregunta excede el máximo de {settings.max_question_chars} caracteres"
            )
        return trimmed


class QueryResponse(BaseModel):
    sql: str
    rows: list[dict]
    row_count: int


@router.post("/query", response_model=QueryResponse)
def query(request: QuestionRequest) -> QueryResponse:
    schema_context = retrieve_relevant_schema(request.question)
    raw_sql = generate_sql(request.question, schema_context)

    try:
        safe_sql = validate_and_prepare(raw_sql, settings.max_rows_returned)
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        rows = execute_select(safe_sql)
    except QueryTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except QueryExecutionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return QueryResponse(sql=safe_sql, rows=rows, row_count=len(rows))
