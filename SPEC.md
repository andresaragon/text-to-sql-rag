# SPEC — Optimización del pipeline `POST /query`

(Sustituye al SPEC.md de la tarea anterior —limpieza de ruff—, que sigue en el historial de git.) Delegado con `/delegar`; Claude es el checker.

Rama: `agent/agy/text-to-sql-rag` (base `feat/sql-firewall`), integrada en `main` vía `feat/optimizar-query`.

**Ajustes al integrar con `main`** (que ya traía PR #4 y la validación de `question`):
- `QueryExecutionError` → **400** (contrato de PR #4, `tests/test_routes_errors.py`), no 422 como decía CA5.
- La normalización de la pregunta vive en el `field_validator` de `QuestionRequest` (ya existía para recortar); se le agregó el colapso de espacios.
- Lint: `ruff check app tests scripts` completo (lo exige `tests/test_estilo_ruff.py`), no solo `--select F app`.

## Objetivo

Que `/query` falle rápido cuando falta infraestructura, no gaste una llamada al
LLM en preguntas que no se pueden responder, aproveche mejor el cache y deje
medir cada etapa desde afuera. Hoy:

- `db.py` y `retrieval.py` crean **dos** engines de SQLAlchemy distintos, sin
  configuración de pool.
- Si Postgres no responde, el request queda colgado ~138 s (timeout TCP del
  sistema operativo, medido en NOTES.md) y termina en HTTP 500.
- `QueryTimeoutError` / `QueryExecutionError` de `db.py` no se traducen a HTTP:
  salen como 500.
- El cache (`lru_cache`) usa la pregunta cruda: `"¿cuántas facturas?"` y
  `"  ¿cuántas   facturas? "` son dos entradas distintas.
- Una pregunta fuera del dominio (distancia coseno > 0.81 según NOTES.md, frente
  a 0.37–0.53 de las preguntas reales) igual paga la inferencia del LLM.
- No hay medición por etapa (NOTES.md, sección Load testing, lo deja pendiente).
- El modelo de embeddings (~470 MB) se carga en el primer request, no al arrancar.

## Alcance

1. **Engine único con pool configurable** (`app/core/db.py`): un solo `_engine`
   que también usa `retrieval.py` (`app.core.retrieval._engine` debe seguir
   existiendo como nombre del módulo, apuntando al mismo objeto). Con
   `pool_pre_ping=True`, `pool_size`, `max_overflow`, `pool_timeout` y
   `connect_timeout` de psycopg2 tomados de `settings`.
2. **Settings nuevos** en `app/config.py`, leídos de variables de entorno:

   | Atributo | Variable | Default |
   |---|---|---|
   | `db_pool_size` | `DB_POOL_SIZE` | `5` |
   | `db_max_overflow` | `DB_MAX_OVERFLOW` | `10` |
   | `db_pool_timeout_seconds` | `DB_POOL_TIMEOUT_SECONDS` | `10` |
   | `db_connect_timeout_seconds` | `DB_CONNECT_TIMEOUT_SECONDS` | `3` |
   | `max_question_chars` | `MAX_QUESTION_CHARS` | `500` |
   | `max_schema_distance` | `MAX_SCHEMA_DISTANCE` | `0.7` |
   | `warmup_on_startup` | `WARMUP_ON_STARTUP` | `True` (`"false"`/`"0"` → `False`) |

3. **Errores a HTTP** en `app/api/routes.py`: base caída o inalcanzable durante
   el retrieval → 503; `QueryTimeoutError` → 504; `QueryExecutionError` → 422.
4. **Normalización de la pregunta** antes de todo: `strip()` + colapsar todo
   bloque de espacios en blanco (espacios, tabs, saltos de línea) a un solo
   espacio. **No** cambiar mayúsculas ni acentos (los literales de la pregunta
   llegan al SQL). La pregunta normalizada es la que se pasa a `embed_text`, al
   prompt del LLM y a las claves de cache. Vacía tras normalizar → 422; más
   larga que `max_question_chars` tras normalizar → 422. En ambos casos no se
   llama a `embed_text`.
5. **Retrieval con distancia y rechazo temprano**:
   `retrieve_relevant_schema(question, top_k=4)` devuelve un
   `RetrievedSchema` (dataclass `frozen=True` en `app/core/retrieval.py`) con
   `context: str` (mismo formato `### {object_type}: {object_name}\n{description}`
   de hoy) y `best_distance: float | None`. La query a pgvector devuelve la
   distancia (`embedding <=> :question_embedding AS distance`). Sigue cacheada
   con `lru_cache` (expone `cache_info` / `cache_clear`).
   En `/query`: sin filas → 503 (índice vacío); `best_distance >
   settings.max_schema_distance` → 422 sin llamar al LLM ni a la base;
   `best_distance == max_schema_distance` se acepta.
6. **Header `Server-Timing`** en toda respuesta 200 de `/query`, con las métricas
   `retrieval`, `llm`, `validate` y `db`, cada una con `dur=<milisegundos>`
   (formato W3C, p. ej. `retrieval;dur=12.3, llm;dur=850.1, validate;dur=0.4, db;dur=3.2`).
7. **Warm-up al arrancar**: un `lifespan` de FastAPI en `app/main.py` que, si
   `settings.warmup_on_startup` es verdadero, carga el modelo de embeddings
   (`app.core.embeddings._get_model()`) antes de aceptar requests.
8. **Documentación**: las 7 variables nuevas, con su default y para qué sirven,
   en `README.md` y `README.es.md`.

## Fuera de alcance

- `app/core/safety.py` y sus tests: no se tocan.
- Redis o cualquier cache externo, reescritura async, cambio de modelos
  (embeddings u Ollama), índices HNSW/IVFFlat, cambios a `db/schema.sql` o a
  `data/schema_docs/tables.md`.
- `NOTES.md`: lo escribe Santiago con sus propias palabras. No editarlo.
- `scripts/load_test.py`: no se modifica.
- Cambiar el contrato JSON de `POST /query` (`sql`, `rows`, `row_count`).

## Criterios de aceptación

Todos se verifican sin Postgres ni Ollama (con mocks), en
`tests/test_optimization.py` salvo donde se indica.

- **CA1** `app.core.retrieval._engine is app.core.db._engine`.
- **CA2** `_engine.pool.size() == settings.db_pool_size`,
  `_engine.pool._max_overflow == settings.db_max_overflow`,
  `_engine.pool._timeout == settings.db_pool_timeout_seconds` y
  `_engine.pool._pre_ping is True`.
- **CA3** Al abrir una conexión, los parámetros que recibe psycopg2 incluyen
  `connect_timeout == settings.db_connect_timeout_seconds` (capturado con el
  evento `do_connect` de SQLAlchemy).
- **CA4** En un proceso sin esas variables de entorno, los defaults de la tabla
  se cumplen; con `DB_POOL_SIZE=7 MAX_SCHEMA_DISTANCE=0.55 WARMUP_ON_STARTUP=false`
  los atributos valen `7`, `0.55` y `False`.
- **CA5** Retrieval que lanza `sqlalchemy.exc.OperationalError` → `POST /query`
  responde 503. `execute_select` que lanza `QueryTimeoutError` → 504;
  `QueryExecutionError` → 422.
- **CA6** `"  ¿cuántas   facturas\n vencidas? "` y `"¿cuántas facturas vencidas?"`
  en dos requests seguidos → `embed_text` se llama 1 vez, con
  `"¿cuántas facturas vencidas?"`; el LLM se llama 1 vez y su prompt contiene esa
  cadena normalizada; `execute_select` se llama 2 veces.
- **CA7** Pregunta `"   \n\t "` → 422 y `embed_text` no se llama. Pregunta de
  `max_question_chars + 1` caracteres tras normalizar → 422 sin `embed_text`.
  Pregunta de exactamente `max_question_chars` caracteres → 200.
- **CA8** `retrieve_relevant_schema` devuelve `RetrievedSchema` con `context`
  en el formato actual y `best_distance` igual a la menor distancia de las filas;
  sin filas, `best_distance is None`. Es hashable y sigue cacheada.
- **CA9** Con distancias `[0.85, 0.9]` → 422, el LLM no se llama y
  `execute_select` no se llama. Con `max_schema_distance=0.5` y distancia `0.5`
  → 200. Sin filas → 503 sin LLM.
- **CA10** Respuesta 200 de `/query` trae `Server-Timing` con las cuatro métricas
  `retrieval`, `llm`, `validate`, `db`, cada una `nombre;dur=<número>`.
- **CA11** Con `warmup_on_startup=True`, `with TestClient(app):` instancia
  `SentenceTransformer` exactamente 1 vez antes del primer request; con `False`,
  0 veces.
- **CA12** `README.md` y `README.es.md` mencionan las 7 variables nuevas.
- **CA13** La suite completa existente pasa (incluye `tests/test_caching.py`,
  actualizado en esta spec al contrato `RetrievedSchema`, y los tests del firewall).

## Comandos

Venv compartido (no crear otro; ver `AGENTS.md`):
`VENV=/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin`

- Test: `$VENV/pytest -q`
- Lint: `$VENV/python -m ruff check --select F app` (el repo tiene deuda de
  estilo previa en E501/I001; solo se exige que `app/` quede sin errores F).
- Build: no hay paso de build.

## Tests protegidos

`tests/test_optimization.py`, `tests/test_caching.py` (y los del firewall,
`tests/test_safety.py`, `tests/test_safety_adversarial.py`).
