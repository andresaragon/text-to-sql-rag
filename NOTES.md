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



