# Notas técnicas — Text-to-SQL Assistant with RAG

Diario de implementación. El objetivo de este archivo no es documentar
el código (para eso está el README), sino registrar **decisiones y
razonamiento** mientras se implementa con Claude Code — para poder
explicar el proyecto de memoria en una entrevista técnica, sin depender
de releer el código.

Regla: llenar cada sección con tus propias palabras, después de haber
implementado y probado el módulo (no antes, no copiando la explicación
de la IA tal cual).

---

## Módulo 1 — `app/core/embeddings.py`

**Pregunta guía:** ¿Qué es un embedding y por qué una pregunta en
lenguaje natural "se parece" numéricamente a una descripción de tabla?

- Decisión tomada:
- Alternativas consideradas y por qué las descarté:
- Cómo lo probé / cómo confirmé que funciona:
- Qué le respondería a un entrevistador si me pregunta "¿por qué este
  modelo de embeddings y no otro?":
Decisión tomada: Usé sentence-transformers con paraphrase-multilingual-MiniLM-L12-v2 en vez del modelo en inglés por defecto (all-MiniLM-L6-v2), con normalize_embeddings=True para que la similitud coseno sea directa.

Alternativas consideradas: Probé primero all-MiniLM-L6-v2 (más liviano, ~90MB) pero medí una brecha débil de solo 0.22 entre frases parecidas y distintas en español. Cambié al modelo multilingüe (~470MB, algo más lento) porque está entrenado explícitamente para paráfrasis en español, y la brecha subió a 0.91 — una mejora medible, no solo teórica.

Cómo lo probé: Script exploratorio (scripts/check_embeddings.py) comparando similitud coseno entre pares de frases parecidas vs. distintas, antes y después del cambio de modelo.
---

## Módulo 2 — `scripts/index_schema.py`

## Módulo 2 — `scripts/index_schema.py`

**Pregunta guía:** ¿Por qué indexar el esquema en vez de meterlo todo
en el prompt siempre?

- Decisión tomada:
  Parseo `tables.md` por headings `##` (regex con flag multilínea),
  tratando cada bloque de tabla como un fragmento, y sub-partiendo el
  bloque de ejemplos por cada ocurrencia de "Pregunta:" para no mezclar
  varios ejemplos en un solo fragmento. Antes de reindexar, borro todo
  el contenido de `schema_embeddings` (no uso upsert) para evitar
  duplicados en corridas repetidas.

- Alternativas consideradas y por qué las descarté:
  Para el object_type "column" (contemplado en el schema pero no usado
  todavía) decidí no generar fragmentos por columna individual — el
  esquema es chico y las columnas ya están descritas en prosa dentro
  de cada fragmento de tabla. Queda como mejora futura si el retrieval
  a nivel de tabla resulta insuficiente. Para evitar duplicados,
  descarté upsert (ON CONFLICT) y verificación previa (SELECT antes de
  insertar) a favor de borrar-y-reindexar completo: es un script de
  desarrollo de un solo usuario, sin concurrencia, así que la solución
  más simple es la correcta.

- Cómo lo probé / cómo confirmé que funciona:
  Corrí el script contra la tabla vacía (6 fragmentos insertados: 4
  tablas + 2 ejemplos), y lo volví a correr sobre esos mismos datos
  para confirmar que borra los 6 anteriores y regenera 6 nuevos, sin
  duplicar. También encontré y corregí un bug de formato (un espacio
  perdido en el `.strip()` al reconstruir el texto de cada ejemplo).

- Qué le respondería a un entrevistador:
  "Indexar el esquema en vez de meterlo completo en cada prompt permite
  que el retrieval traiga solo el contexto relevante a la pregunta —
  con un esquema grande, mandar todo el esquema en cada prompt
  desperdiciaría contexto y diluiría la relevancia. Probé el ciclo de
  reindexado repetido para confirmar que editar el esquema y volver a
  correr el script no genera duplicados."

1. SET LOCAL vs SET — esto es una trampa clásica con pools de conexiones que mucha gente no conoce. Si usaras SET a secas, el timeout se quedaría "pegado" a la conexión física del pool y podría filtrarse a la siguiente función que reutilice esa misma conexión con otro timeout esperado. SET LOCAL limita el efecto a la transacción actual — se resetea solo. Este es exactamente el tipo de detalle que un entrevistador senior nota si le explicas tu diseño.

2. El bindparam con Vector(384) para el INSERT — este es el punto más delicado del módulo, y con razón: sin ese cast explícito, psycopg2 metería la lista como un ARRAY genérico de Postgres, no como vector, y el INSERT fallaría. Es un buen ejemplo de "la integración entre dos librerías no es automática solo porque ambas existen" — algo que solo se descubre leyendo documentación o, como en este caso, pidiendo la explicación antes de aceptar el código a ciegas.

3. La nota de fragilidad sobre el bind param en SET LOCAL — que te haya avisado que esto depende de un comportamiento específico de psycopg2 (sustitución del lado del cliente, no el protocolo extendido de Postgres) es una señal de honestidad técnica que vale la pena que imites tú también cuando documentes decisiones: no solo "funciona", sino "funciona por esta razón específica, y sería frágil si cambiara X".

psycopg2-binary==2.9.10  # 2.9.9 no compila en Python 3.14: usa _PyInterpreterState_G
et, removida de la API interna de CPython
---

## Módulo 3 — `app/core/retrieval.py`

## Módulo 3 — `app/core/retrieval.py`

**Pregunta guía:** ¿Cómo mide pgvector "similitud"? ¿Qué pasa si
`top_k` es muy alto o muy bajo?

- Decisión tomada:
  Usé el operador `<=>` de pgvector (distancia coseno) directamente en
  el `ORDER BY`, con `top_k=4` como default. retrieval.py maneja su
  propio engine de SQLAlchemy (separado del de db.py) porque su caso
  de uso es distinto: una query fija y controlada por mí, no SQL
  arbitrario del LLM — por eso tampoco le apliqué statement_timeout.

- Alternativas consideradas y por qué las descarté:
  Empecé con top_k=3, pero un script exploratorio con 4 preguntas
  representativas del dominio mostró que era frágil: en el caso
  "¿qué acciones de cobranza se han hecho sobre facturas vencidas?",
  collection_actions casi quedaba fuera del top-3. Subí a top_k=4,
  que resuelve los casos ambiguos sin volver a un no-op de retrieval
  (con solo 6 fragmentos totales, top_k muy alto devuelve el corpus
  completo y el RAG deja de filtrar nada).

- Cómo lo probé / cómo confirmé que funciona:
  Script exploratorio con 4 preguntas: dos casos ambiguos entre varias
  tablas, un caso donde el nombre de la tabla casi no aparece en la
  pregunta, y un caso irrelevante al dominio. Con top_k=4, los 3 casos
  reales traen las tablas correctas; el caso irrelevante mantiene
  distancias >0.81, muy separadas del rango 0.37–0.53 de las preguntas
  reales — una brecha clara y medible.

- Qué le respondería a un entrevistador:
  "No fijé top_k a ojo — lo validé con preguntas representativas del
  dominio y ajusté cuando encontré un caso donde el valor inicial
  dejaba fuera una tabla necesaria. Además descubrí que la distancia
  coseno da una señal clara para detectar preguntas sin relación al
  esquema, que podría usarse como guardrail antes de generar SQL."

---

## Módulo 4 — `app/core/sql_generator.py`

**Pregunta guía:** ¿Qué controla que el LLM no alucine una tabla que
no existe?

Nota técnica (para completar abajo con tus propias palabras): se llama
a Ollama con `options={"temperature": 0}` para generación determinística
(greedy decoding) — mismo prompt siempre da la misma respuesta, en vez
de variar entre corridas. Esto NO elimina el riesgo de que el LLM copie
valores literales (fechas, umbrales) de los ejemplos few-shot recuperados
que no corresponden a la pregunta actual — confirmado empíricamente
probando manualmente contra `ollama run sqlcoder` antes y después de
agregar una instrucción explícita en el prompt pidiéndole que no lo
haga (no lo resolvió de forma confiable). safety.py garantiza SQL
sintácticamente seguro, no semánticamente correcto — es un riesgo de
fallo silencioso documentado, no resuelto.

- Decisión tomada:
  El control real contra alucinar una tabla inexistente no está en el
  LLM, está en el RAG: `sql_generator.py` solo recibe el `schema_context`
  que trajo `retrieval.py` (top_k=4 fragmentos relevantes), nunca el
  esquema completo, así que el modelo no tiene "espacio" para nombrar
  algo fuera de ese contexto. Además, el prompt (`PROMPT_TEMPLATE`) es
  explícito en dos reglas: solo `SELECT` (nunca INSERT/UPDATE/DELETE/DROP)
  y no copiar valores literales de los bloques `example_query` salvo que
  la pregunta actual los mencione. La extracción del SQL de la respuesta
  cruda (`_extract_sql`) intenta primero un fence de markdown y, si no
  hay, cae a "desde el primer SELECT en adelante" como fallback.

- Alternativas consideradas y por qué las descarté:
  Consideré pasarle el esquema completo al LLM y confiar en que "elija"
  bien las tablas relevantes, sin pasar por retrieval — lo descarté
  porque no escala: con más tablas se diluye el contexto y sube la
  probabilidad de que el modelo alucine un nombre. También consideré
  pedirle salida estructurada (JSON con el SQL) en vez de parsear texto
  con regex, pero `sqlcoder` vía Ollama no da soporte confiable a tool
  calling/structured output, así que un regex robusto con fallback fue
  la opción más simple que realmente funcionaba.

- Cómo lo probé / cómo confirmé que funciona:
  Probé manualmente contra `ollama run sqlcoder` con el mismo par
  pregunta+contexto, antes y después de agregar la instrucción explícita
  de no copiar literales de los ejemplos few-shot. El LLM seguía
  copiando valores (p. ej. el mismo intervalo de fecha del ejemplo) en
  varios casos incluso con la instrucción — no reporté esto como
  "resuelto", lo dejé documentado como limitación conocida en el
  docstring del módulo.

- Qué le respondería a un entrevistador:
  "Lo que evita que el LLM invente una tabla que no existe no es el LLM
  en sí, es el RAG: solo le paso el esquema recuperado y relevante a la
  pregunta, así que no tiene contexto para alucinar un nombre fuera de
  eso. Pero encontré un riesgo distinto que no logré eliminar del todo:
  el modelo puede copiar un valor literal de un ejemplo few-shot que no
  corresponde a la pregunta actual. Lo probé manualmente, agregué una
  instrucción explícita en el prompt, y no lo resolvió de forma
  confiable — preferí dejarlo documentado como limitación conocida en
  vez de fingir que estaba resuelto."

- **Contexto adicional (caso real de producción):** este mismo patrón
  de comportamiento — inconsistencia y falta de uso óptimo de índices —
  lo he visto en un sistema de producción real donde se usó un LLM para
  afinar queries SQL existentes. Confirma que la limitación que
  encontré en este proyecto no es una rareza de un modelo chico como
  sqlcoder corriendo local: es una limitación de categoría, presente
  incluso cuando el modelo usado es más grande o especializado.
---

## Módulo 5 — `app/core/safety.py`

**Pregunta guía:** ¿Por qué un parser real (sqlglot) es más seguro que
un filtro de texto?

- Decisión tomada:
  `is_safe_select()` parsea el SQL con `sqlglot` (dialecto `postgres`) y
  exige dos cosas sobre el árbol resultante: que haya exactamente un
  statement, y que ese statement sea una instancia de `exp.Select`. Eso
  rechaza automáticamente cualquier intento de statement múltiple sin
  necesitar una lista de palabras prohibidas. `enforce_limit()` opera
  también sobre el AST: si no hay `LIMIT`, lo agrega; si el que trae
  supera `max_rows`, lo reemplaza. `validate_and_prepare()` es el único
  punto de entrada que combina ambas validaciones antes de ejecutar.

- Alternativas consideradas y por qué las descarté:
  La alternativa obvia es un filtro de texto (regex buscando `DROP`,
  `DELETE`, etc., o `.upper().startswith("SELECT")`). La descarté porque
  es trivialmente evadible: un `;` seguido de otro statement, o una
  palabra prohibida escondida después de un comentario `--`, rompen un
  filtro de texto pero no un parser real, que construye el árbol
  sintáctico completo y ve el segundo statement igual.

- Cómo lo probé / cómo confirmé que funciona (¿qué casos rompiste a
  propósito?):
  `tests/test_safety.py` cubre explícitamente los dos bypass clásicos de
  un filtro de texto: `test_select_with_subquery_insert_is_rejected`
  (un `SELECT` válido seguido de `; INSERT ...` en la misma cadena) y
  `test_update_disguised_as_comment_is_rejected` (un `UPDATE` después de
  un comentario `--`). Ambos deben rechazarse aunque el primer statement
  sea un `SELECT` perfectamente válido. También probé `enforce_limit` en
  sus tres casos: sin `LIMIT` (debe agregarlo), con `LIMIT` por debajo
  del máximo (debe respetarlo tal cual), y con `LIMIT` por encima del
  máximo (debe recortarlo, sin dejar rastro del valor original en el SQL
  final).

- Qué le respondería a un entrevistador:
  "Un filtro de texto asume que el SQL peligroso se va a ver 'obvio'.
  Un parser real como sqlglot construye el árbol sintáctico completo,
  así que no importa si el statement destructivo viene después de un
  `;` o de un comentario `--` — sqlglot lo sigue viendo como un segundo
  statement en el árbol, y mi regla es tajante: solo se permite
  exactamente un `Select`. Lo probé rompiéndolo a propósito con esos dos
  bypasses clásicos para confirmar que el parser los atrapa donde un
  regex no lo haría."

> **Nota (2026-10-07):** este módulo describe la primera versión del
> validador (un único `Select`). La regla vigente es más amplia: acepta
> `SELECT`, `UNION`, `INTERSECT` y `EXCEPT` de solo lectura, y añade lista
> blanca de tablas, bloqueo de funciones y tope de `OFFSET`. Ver la sección
> "Endurecimiento del firewall SQL (2026-10-07)" al final de este archivo.

---

## Módulo 6 — `app/core/db.py`

**Pregunta guía:** ¿Por qué hay timeout y límite de filas — qué ataque
o error evita eso?

- Decisión tomada:
  Usé SQLAlchemy Core (no el ORM completo) con `create_engine` + `text()`
  para ejecutar SQL crudo de forma parametrizada. Configuré
  `statement_timeout` con `SET LOCAL` (no `SET`) dentro de una transacción
  explícita, para que el límite de tiempo no se filtre a otras funciones
  que reutilicen la misma conexión del pool. Para insertar embeddings,
  usé `bindparam` con el tipo `Vector(384)` de pgvector-python — sin eso,
  psycopg2 castea un `list[float]` como `ARRAY` genérico de Postgres, no
  como `vector`, y el INSERT falla con un error de tipos incompatibles.

- Alternativas consideradas y por qué las descarté:
  Consideré usar `SET` en vez de `SET LOCAL` para el timeout, pero lo
  descarté porque `SET` persiste en la conexión física del pool incluso
  después de devolverla — otra función podría heredar un timeout viejo
  por accidente. `SET LOCAL` se revierte solo al hacer commit/rollback
  de la transacción. También decidí capturar errores legibles solo en
  `execute_select()` (SQL generado por el LLM, de cara al usuario final)
  y no en `save_schema_embedding()` (script interno de desarrollo, donde
  el traceback crudo de SQLAlchemy es más útil que un mensaje traducido).

- Cómo lo probé / cómo confirmé que funciona:
  Levanté Postgres + pgvector en Docker (`ankane/pgvector`), cargué el
  esquema y datos de prueba, y corrí un script exploratorio
  (`scripts/check_db.py`) que genera un embedding real, lo guarda con
  `save_schema_embedding()`, lo lee de vuelta con `execute_select()`,
  confirma la dimensión con `vector_dims()` (función nativa de pgvector,
  más confiable que parsear el string del lado de Python), y borra la
  fila de prueba al final. Durante esto encontré que `psycopg2-binary`
  pineado no compilaba contra Python 3.14 (API interna de CPython
  removida) — actualicé el pin en `requirements.txt` con el motivo
  documentado en un comentario.

- Qué le respondería a un entrevistador:
  "El timeout evita que un SQL generado por el LLM — sintácticamente
  válido pero sin condiciones o con un JOIN costoso — se quede corriendo
  indefinidamente y consuma recursos del servidor. Usé `SET LOCAL` en vez
  de `SET` específicamente por el pool de conexiones: evita que el límite
  se filtre entre requests distintos. Lo verifiqué de punta a punta contra
  una base real, no solo en teoría."


---

## Caching — retrieval + generación de SQL

**Pregunta guía:** ¿Dónde se va la mayor parte del tiempo en `/query` y qué partes del pipeline son seguras de cachear?

- **Qué se cachea y qué no (y por qué):**
  - **Se cachea:**
    - `retrieve_relevant_schema(question)`: Generación de embeddings con `sentence-transformers` y búsqueda por similitud coseno (`<=>`) en `pgvector`. Es una operación determinista para una misma pregunta y costosa en CPU/I/O.
    - `generate_sql(question, schema_context)`: Inferencia del LLM (`sqlcoder` en Ollama). Es por lejos la etapa más lenta del pipeline (latencia de segundos). Dado que usamos `temperature=0` (greedy decoding), la respuesta es determinista para el mismo par de pregunta y contexto de esquema.
  - **NO se cachea:**
    - `execute_select(sql)`: La ejecución contra Postgres. Los datos en las tablas (facturas, cobros, estados de clientes) son vivos y cambian continuamente. Cachear los resultados de filas devolvería datos desactualizados (*stale data*), lo cual es inaceptable en una base operativa.
    - `validate_and_prepare(sql)`: La validación sintáctica y AST con `sqlglot` toma microsegundos en memoria sin I/O, por lo que cachearla no ofrece una ganancia medible.

- **Decisión tomada:**
  Usé `functools.lru_cache(maxsize=256)` directamente sobre `retrieve_relevant_schema` y `generate_sql`. Es parte de la biblioteca estándar de Python (cero dependencias externas, cero infraestructura adicional), *thread-safe* en CPython y acotado a 256 entradas para evitar crecimiento desmedido de memoria (*unbounded memory leak*).

- **Alternativas consideradas y por qué las descarté:**
  - *Cache con TTL (Time-To-Live, ej. cachetools)*: Un TTL expira entradas en función del tiempo transcurrido. Lo descarté porque el esquema no muta periódicamente por tiempo, sino por eventos discretos (cuando el desarrollador reindexa). Un TTL causaría *cache misses* artificiales e innecesarios en preguntas frecuentes, y durante la ventana de tiempo seguiría sirviendo datos viejos de todos modos.
  - *Redis / KeyDB externo*: Introducir un servicio de cache externo en esta etapa violaría la restricción de simplicidad para desarrollo local de un solo proceso y agregaría sobrecarga de serialización y mantenimiento de infraestructura.

- **Política de invalidación y limitaciones conocidas:**
  - Al ser un cache en memoria del proceso, si se reindexa el esquema con `scripts/index_schema.py` o se modifica la documentación de tablas, las entradas cacheadas quedan desactualizadas (*stale*) hasta que se reinicie el proceso de Uvicorn (o se invoque explícitamente `.cache_clear()`).
  - Esta es una limitación conocida y aceptada para el entorno actual de desarrollo local.

- **Escalabilidad y próximo paso (por qué in-memory no escala a múltiples workers):**
  - *In-memory alcanza para este estadio*: Uvicorn corre como un único proceso worker en local, compartiendo el espacio de memoria de Python.
  - *Por qué no escala a múltiples workers o réplicas*: En producción con Uvicorn multi-worker (`--workers 4`) o réplicas en Kubernetes, cada worker tiene su propio proceso y memoria aislada. Requests idénticos distribuidos por un balanceador caerían en distintos workers con caches fríos (*cache duplication* y menor *hit ratio*), y limpiar el cache en un worker no limpiaría el de los demás (inconsistencia de estado).
  - *Próximo paso*: Migrar a un cache distribuido compartido (Redis) con claves compuestas basadas en hash de la pregunta y un hash de versión del esquema (`schema_version:question_hash`), invalidable ante despliegues o reindexaciones.

- **Cómo lo probé / cómo confirmé que funciona:**
  Escribí `tests/test_caching.py` con pruebas unitarias y de integración del endpoint `POST /query` usando `pytest` y `unittest.mock`. Con mocks sobre `embed_text`, `_engine.connect`, `_client.generate` y `execute_select`:
  - Se confirmó que al enviar la misma pregunta dos veces, `embed_text` y `_client.generate` se ejecutan exactamente 1 vez (cache hit), mientras que `execute_select` se ejecuta 2 veces (sin cachear).
  - Se confirmó que ante preguntas distintas el cache produce miss y recalcula ambas etapas.

---

## Resumen final (llenar al terminar todo el proyecto)

Esta sección es la que releo antes de una entrevista técnica.

**¿Qué problema real resuelve este proyecto, en 2-3 frases, sin jerga?**

Deja que alguien pregunte en lenguaje natural sobre datos que viven en
una base relacional (facturas, clientes, cobranza) sin que necesite
saber SQL — y sin exponer la base a que un LLM ejecute algo destructivo
o corra una query sin límites. El RAG es lo que le da al modelo el
esquema real (nombres de tablas y columnas reales) en vez de dejarlo
adivinar.

**¿Cuál fue la decisión de diseño más difícil y por qué?**

Aceptar que `safety.py` solo puede garantizar seguridad sintáctica
(que el SQL sea un `SELECT` válido y nada más), no corrección
semántica. Probé varias veces reforzar el prompt para que el LLM no
copiara valores literales de los ejemplos few-shot, y no lo resolví de
forma confiable (ver Módulo 4). La decisión difícil fue documentar eso
como una limitación conocida y abierta en vez de seguir iterando el
prompt buscando una solución que quizás no existe con este approach —
o peor, reportarlo como resuelto sin haberlo verificado a fondo.

**¿Qué haría diferente si lo rehiciera hoy?**

Implementaría desde el principio el retrieval híbrido (semántico +
foreign keys vía `information_schema.key_column_usage`) descrito en el
README, en vez de dejarlo como mejora futura — con solo 4 tablas el
LLM infiere los JOINs por los nombres de columna, pero es la primera
cosa que se rompe al escalar el esquema. También loggearía el SQL
generado desde el día 1 (aunque sea a un archivo plano), porque los
patrones de filtro reales no se pueden adivinar de antemano — hace
falta ver qué preguntas se hacen de verdad antes de decidir qué
indexar.

**¿Qué NO sé todavía de este proyecto (honestidad, no vender lo que no domino)?**

No probé el sistema bajo concurrencia real: `index_schema.py` borra y
reindexa todo sin locks, pensado para un solo desarrollador corriéndolo
localmente, no para múltiples procesos reindexando a la vez.
`retrieval.py` tampoco tiene `statement_timeout` propio (a diferencia
de `db.py`) porque asumí que su query es fija y controlada por mí, pero
no medí qué pasa si el esquema indexado crece mucho. Tampoco validé el
sistema contra un esquema con más de 4 tablas ni contra preguntas fuera
del dominio de facturación/cobranza — no sé qué tan bien generalizaría
el prompt template sin ajustes.

---

## Load testing — baseline

Script: `scripts/load_test.py` (Locust).
Dependencias: agregadas en `requirements-dev.txt` (`-r requirements.txt` + `locust==2.32.4`), separadas de `requirements.txt` para no contaminar el entorno de producción con herramientas de benchmarking.

### Diseño del test de carga
- **HttpUser (`TextToSqlUser`)**: Ejecuta peticiones a `POST /query` rotando aleatoriamente entre 10 preguntas realistas derivadas directamente del esquema de dominio documentado en `data/schema_docs/tables.md` (tablas `customers`, `invoices`, `payments`, `collection_actions`). Se descartaron preguntas genéricas para evaluar el retrieval y la generación sobre relaciones reales.
- **Aislamiento del cuello de botella (LLM vs DB vs Framework)**:
  El pipeline de `/query` ejecuta 4 etapas síncronas en cada request:
  1. Retrieval semántico con pgvector (`retrieve_relevant_schema`)
  2. Inferencia y generación de SQL vía Ollama (`generate_sql`, modelo `sqlcoder`)
  3. Validación sintáctica AST con sqlglot (`validate_and_prepare`)
  4. Ejecución SQL contra Postgres (`execute_select`)

  Medir la latencia exacta por etapa dentro del mismo request requeriría instrumentar `app/core/*` (lo cual violaría la restricción de cero cambios sobre el core). Para aislar el impacto del framework sin tocar el código interno, `load_test.py` incluye una tarea paralela `health_baseline` (10% del peso) que golpea `GET /health` (sin DB, RAG ni LLM). La diferencia entre la latencia de `/health` y `/query` evidencia el overhead del pipeline de IA y datos, dominado por la inferencia en Ollama.
- **Ejecución headless**: Configurado con `host = "http://localhost:8000"` por defecto, ejecutable directamente con:
  ```bash
  locust -f scripts/load_test.py --headless -u 10 -r 2 -t 2m --csv=results
  ```

### Diagnóstico del entorno y resultados de la corrida inicial (2026-09-21)

Siguiendo la regla de no inventar números cuando la infraestructura base no responde, se verificó cada componente en orden antes de correr Locust. El venv del proyecto no tenía instaladas ni siquiera las dependencias core de `requirements.txt` (`fastapi`, `uvicorn`, `psycopg2`, `sentence-transformers`, `pgvector`, `sqlalchemy`, `sqlglot`) — se instalaron para poder levantar la app y así medir con datos reales en vez de reportar solo "no se pudo".

1. **Servidor FastAPI (`app.main:app`)**:
   - Inicialmente no estaba en ejecución.
   - Al lanzarlo con `uvicorn app.main:app --port 8000`, la aplicación inicia correctamente y el endpoint `/health` responde en **~2-4 ms** con código `200 OK` (`{"status":"ok"}`).
2. **Base de Datos (Postgres + pgvector en `localhost:5432`)**:
   - El contenedor Docker no está corriendo en el host (no se levantó uno nuevo — fuera de alcance de esta tarea).
   - Al recibir una solicitud `POST /query`, la etapa 1 (`retrieve_relevant_schema`) intenta conectar al socket `localhost:5432` vía SQLAlchemy/psycopg2. Al no haber servicio escuchando en dicho puerto, el intento se bloquea durante el timeout TCP del sistema operativo (**137.9 segundos**), fallando finalmente con:
     ```text
     psycopg2.OperationalError: connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection timed out
     ```
     y devolviendo un `HTTP 500 Internal Server Error`.
3. **Inferencia Local (Ollama en `localhost:11434`)**:
   - El daemon de Ollama responde en el puerto 11434, pero su registro está vacío (`GET /api/tags` devuelve `{"models":[]}`).
   - La prueba directa contra la API de inferencia (`POST /api/generate` con `{"model": "sqlcoder"}`) retorna:
     ```json
     {"error": "model 'sqlcoder' not found"}
     ```
   - No se hizo `ollama pull` — descargar un modelo nuevo también es infraestructura fuera de alcance de esta tarea.
4. **Resultados bajo carga con la infraestructura actual (10 usuarios concurrentes, corrida real de Locust contra el server levantado)**:
   - **Throughput efectivo exitoso**: `0.00 req/s` en `/query`.
   - **Tasa de error**: `100%` en `/query` (peticiones encoladas en timeout de socket de ~138s y HTTP 500).
   - **Latencias p50 / p95 / p99**: no representativas del pipeline de IA real — el bloqueo ocurre a nivel de socket TCP antes de llegar al retrieval o al LLM.

Estos números son reales (server y Locust corriendo de verdad), no simulados — pero reflejan el costo de una infraestructura incompleta (sin Postgres, sin modelo de Ollama), no el rendimiento del pipeline de IA en sí. Para eso hace falta la corrida con todo levantado (ver abajo).

### Requisitos previos para la siguiente fase de optimización (caching / pooling)
Para registrar los números de baseline definitivos del pipeline de IA (no solo del fallo de infraestructura) antes de implementar Redis o pooling de conexiones:
1. Iniciar el contenedor de PostgreSQL con pgvector (`docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres ankane/pgvector`).
2. Cargar el esquema e indexar vectores: `psql -f db/schema.sql && python scripts/index_schema.py`.
3. Descargar el modelo en Ollama: `ollama pull sqlcoder`.
4. Instalar dependencias completas en el venv: `pip install -r requirements.txt -r requirements-dev.txt`.
5. Levantar el servidor: `uvicorn app.main:app --port 8000`.
6. Ejecutar Locust en modo headless:
   ```bash
   locust -f scripts/load_test.py --headless -u 10 -r 2 -t 2m --host http://localhost:8000 --csv=results
   ```




---

## Endurecimiento del firewall SQL (2026-10-07)

### Quién hizo qué
- **Decisiones de diseño:** el líder (Claude Sonnet 5.5) las propuso y yo las revisé y aprobé. Confirmé explícitamente dos: INTERSECT/EXCEPT aceptados y `MAX_OFFSET = 10_000`. La lista blanca de cuatro tablas se mantiene como decisión de diseño.
- **Tests y contratos de cada issue:** los escribió el líder (Claude Sonnet 5.5) a partir de esas decisiones, antes de que se escribiera el código.
- **Código de `app/core/safety.py`:** lo escribieron agentes delegados a través del orquestador. Codex (`gpt-6-luna`) resolvió los issues 001, 002 y 004; Claude Haiku (invocado con el alias `haiku`; los logs no registran la versión exacta) resolvió el 003 y el 005.
- **Auditoría externa:** Codex hizo 5 auditorías de diff como segunda opinión, y el líder verificó cada hallazgo contra el diff.

### Método
El líder escribió primero los tests adversariales y los corrió contra la implementación existente: de 132 casos, 29 fallaban. El resto ya resistía (tablas con esquema o comillas, alias, CTEs que sombrean tablas, varias sentencias, comentarios, `pg_read_file` y `dblink` en FROM, `SELECT INTO`, `EXPLAIN`). Durante la revisión se añadieron más tests:
- **Huecos hallados:** OFFSET dentro de subconsultas y CTEs, y funciones de información del entorno (`current_user`, `current_database`, `inet_*`). Ambos pasaban el firewall y se cerraron.
- **Guarda de regresión:** un bloque de 60 expresiones con funciones comunes de SQL de reportes (`date_trunc`, `coalesce`, `row_number`, `string_agg`, etc.) que el firewall debe seguir aceptando. No encontró ningún rechazo; protege contra que futuros bloqueos por patrón rompan consultas legítimas.

Resultado final: 245 tests en `tests/test_safety_adversarial.py` y 269 en la suite completa.

### Qué se cerró
- DML y bloqueos dentro de un SELECT, incluido `WITH x AS (DELETE ... RETURNING *) SELECT ...` (pasaba como un SELECT inocente) y `FOR UPDATE/SHARE`.
- Familias de funciones de sistema por patrón: `pg_*`, `lo_*`, `txid_*`, `dblink*`, `*_to_xml*`, más `version`, `current_setting` y `set_config`.
- Funciones de identidad y red: `current_user`, `session_user`, `current_database`, `current_schema(s)` e `inet_server/client_addr/port`.
- Tope de OFFSET (`MAX_OFFSET = 10_000`) aplicado a todos los nodos del AST, no solo a la consulta raíz.
- Fail-closed: entrada que no es `str` y cualquier excepción inesperada del parser salen como `UnsafeQueryError`.
- INTERSECT y EXCEPT pasan a aceptarse: era un falso positivo, no un hueco, porque la lista blanca de tablas ya recorre todo el AST.

### Limitación conocida: la lista negra de funciones
Una lista negra solo bloquea lo que nombra o cubre por patrón; una función nueva o poco común puede pasar. La alternativa es una **lista blanca de funciones** (agregados, fechas, texto, ventanas, `generate_series`): es más segura, pero rompe SQL legítimo que el LLM invente y obliga a mantener un catálogo. Se eligieron patrones de familia como equilibrio. Un efecto lateral aceptado: las formas sin paréntesis (`current_user`, `session_user`, `current_schema`) se bloquean como columna sin calificar, de modo que una columna de negocio con ese nombre exacto también se rechazaría; ninguna tabla actual la tiene.

### Defensa en profundidad
El firewall es una capa, no la única. En producción hay que sumar:
- un usuario de BD de solo lectura con `GRANT SELECT` únicamente sobre las cuatro tablas;
- `statement_timeout` y `lock_timeout` en ese rol;
- ejecución dentro de una transacción de solo lectura (`SET TRANSACTION READ ONLY`);
- límites de filas (`LIMIT`, ya implementado) y de conexiones.

Así, un fallo del validador no se convierte en un incidente.

### Observaciones del proceso
- El auditor externo no encontró ningún hallazgo real: de 5 auditorías, 3 coincidieron con la revisión del líder y 2 fueron falsos positivos. El hueco real del issue 003 (OFFSET en subconsultas) lo halló el sondeo del líder.
- Barrido de consultas legítimas del proyecto: sin regresiones. Se rechazan las consultas internas del RAG sobre `schema_embeddings` y las de un esquema grande de pruebas, que usan tablas fuera de la lista blanca; con las 19 tablas de ese esquema como `allowed_tables`, pasan 6 de 6.
