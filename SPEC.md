# SPEC — Validación de la pregunta en `POST /query`

Delegado a agy con `/delegar` (Claude es el checker). Rama `agent/agy/text-to-sql-rag`.

## Problema
`POST /query` acepta cualquier `question`: una cadena vacía, solo espacios o de miles de caracteres llega
igual al retrieval (embeddings + Postgres) y al LLM (Ollama). Es gasto inútil y abre la puerta a prompts
gigantes. Además, `"  ventas  "` y `"ventas"` ocupan entradas distintas en las cachés `lru_cache`.

## Alcance
- Validar `question` en la entrada del endpoint, antes de cualquier llamada a retrieval, LLM o base de datos.
- Recortar los espacios del inicio y del final antes de usarla.
- Tope de longitud configurable con la variable de entorno `MAX_QUESTION_CHARS` (por defecto 500), expuesto
  como `settings.max_question_chars` en `app/config.py`.

## Fuera de alcance
- Cambiar `safety.py`, el retrieval, el generador de SQL o el formato de la respuesta exitosa.
- Validar el idioma o el contenido semántico de la pregunta.
- Rate limiting, autenticación o cualquier otra cosa no listada aquí.
- `NOTES.md` (es el diario de Santiago: no se toca).

## Criterios de aceptación
Cada criterio tiene al menos un test en `tests/test_question_validation.py` (tests de aceptación: **no se modifican**).

1. **Vacía o solo espacios → 422.** `{"question": ""}`, `{"question": "   "}` y `{"question": "\n\t "}` responden 422
   y no se llama a `retrieve_relevant_schema`, `generate_sql` ni `execute_select`.
2. **Demasiado larga → 422.** Con el valor por defecto, una pregunta de 501 caracteres (después de recortar)
   responde 422 sin llamar a ninguna de esas tres funciones.
3. **Justo en el límite → aceptada.** Una pregunta de exactamente 500 caracteres responde 200.
4. **Se recorta antes de usarla.** Con `{"question": "  total de ventas  "}`, `retrieve_relevant_schema` y
   `generate_sql` reciben `"total de ventas"` (sin los espacios).
5. **El límite es configurable.** `settings.max_question_chars` existe, vale 500 por defecto y se lee en cada
   petición: si un test lo fija en 10, una pregunta de 11 caracteres da 422 y una de 10 da 200.
6. **El límite cuenta después de recortar.** 500 caracteres útiles rodeados de espacios responden 200.
7. **Sin regresiones.** La suite completa existente sigue pasando sin modificar ningún test existente.

## Comandos
- Build: `/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/python -m compileall -q app tests`
- Tests: `/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/pytest -q tests`
- Lint: no hay linter instalado en el venv compartido (pendiente de decisión de Santiago).
