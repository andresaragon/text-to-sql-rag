"""
Genera una consulta SQL a partir de una pregunta en lenguaje natural
y el contexto de esquema recuperado por RAG (retrieval.py).

Limitación conocida, confirmada empíricamente con scripts/prompts de
prueba manual contra `ollama run sqlcoder`: el LLM puede copiar valores
literales de los ejemplos few-shot recuperados (fechas, umbrales,
montos) que no corresponden a la pregunta actual, incluso con una
instrucción explícita en el prompt pidiéndole que no lo haga. safety.py
garantiza que el SQL sea sintácticamente seguro (solo SELECT), pero no
garantiza que el resultado sea semánticamente correcto — este es un
riesgo real de fallo silencioso (la query corre y devuelve datos, solo
que con un filtro de más). Mitigación futura posible: filtrar ejemplos
por compatibilidad de literales antes de incluirlos en el contexto.

temperature=0 al llamar a Ollama: no elimina este riesgo, pero hace que
la salida sea determinística/reproducible para la misma pregunta y el
mismo contexto, en vez de variar de una corrida a otra.
"""

import re

from ollama import Client

from app.config import settings

PROMPT_TEMPLATE = """You are a SQL assistant. Given the database schema
context below and a question, generate a single valid PostgreSQL SELECT
query that answers the question. Only output the SQL query, nothing else.
Never generate INSERT, UPDATE, DELETE, DROP or any statement other than
SELECT.

Some schema context blocks are labeled example_query: these show a past
question with its SQL, purely to illustrate structure (how to join
tables, which columns to use, the general shape of the query). Do NOT
copy specific literal values from them (dates, thresholds, numbers,
intervals) unless the current question explicitly mentions those same
values. Base every literal in your SQL only on the current question.

### Schema context:
{schema_context}

### Question:
{question}

### SQL:
"""

_SQL_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_SELECT_RE = re.compile(r"SELECT\b.*", re.IGNORECASE | re.DOTALL)

_client = Client(host=settings.ollama_host)


def _extract_sql(raw_response: str) -> str:
    """Limpia la respuesta cruda del LLM: saca el SQL de un fence de markdown
    si existe, o busca desde el primer SELECT en adelante como fallback."""
    fence_match = _SQL_FENCE_RE.search(raw_response)
    if fence_match:
        return fence_match.group(1).strip()

    select_match = _SELECT_RE.search(raw_response)
    if select_match:
        return select_match.group(0).strip()

    return raw_response.strip()


def generate_sql(question: str, schema_context: str) -> str:
    """
    Genera SQL a partir de la pregunta y el contexto de esquema.
    Devuelve el SQL crudo, sin ejecutar (eso lo hace safety.py + db.py).
    """
    prompt = PROMPT_TEMPLATE.format(schema_context=schema_context, question=question)

    response = _client.generate(
        model=settings.ollama_model,
        prompt=prompt,
        options={"temperature": 0},
    )

    return _extract_sql(response["response"])
