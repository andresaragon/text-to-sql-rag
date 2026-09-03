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
from pydantic import BaseModel

from app.core.retrieval import retrieve_relevant_schema
from app.core.sql_generator import generate_sql
from app.core.safety import validate_and_prepare, UnsafeQueryError
from app.core.db import execute_select
from app.config import settings

router = APIRouter()


class QuestionRequest(BaseModel):
    question: str


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

    rows = execute_select(safe_sql)
    return QueryResponse(sql=safe_sql, rows=rows, row_count=len(rows))
