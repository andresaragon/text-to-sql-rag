# Text-to-SQL Assistant with RAG

Asistente que traduce preguntas en lenguaje natural a consultas SQL seguras,
usando RAG (Retrieval-Augmented Generation) para darle al LLM el contexto
real del esquema de base de datos — en vez de dejar que "adivine" nombres
de tablas y columnas.

Proyecto personal para conectar experiencia de 5+ años en bases de datos
relacionales (PL/SQL / Oracle / SQL Server) con desarrollo práctico de
aplicaciones basadas en LLMs.

## Por qué este proyecto

Uno de los mayores cuellos de botella al llevar LLMs a empresas reales no
es entrenar modelos, sino conectarlos de forma segura y precisa con datos
estructurados ya existentes (SQL, ERPs, pipelines de datos). Este proyecto
es un ejemplo end-to-end de ese problema, resuelto con herramientas propias:

- **LLM local** vía Ollama (GPU-acelerado, CUDA) — sin depender de APIs pagas.
- **RAG sobre el esquema**: embeddings de tablas, columnas, relaciones y
  ejemplos de queries, para que el modelo genere SQL con contexto real.
- **Capa de seguridad**: solo `SELECT`, sin DDL/DML, con límites y timeout.

## Estado del proyecto

🚧 En construcción — desarrollo personal, no producción.

- [ ] Fase 1 — Base de datos de práctica (dominio: facturación/cobranza)
- [ ] Fase 2 — Indexado del esquema (embeddings + pgvector)
- [ ] Fase 3 — Generación de SQL con Ollama
- [ ] Fase 4 — Capa de validación y seguridad
- [ ] Fase 5 — API mínima (FastAPI) / CLI

## Stack

| Componente          | Herramienta                          |
|---------------------|---------------------------------------|
| Base de datos        | PostgreSQL + `pgvector`              |
| LLM local            | Ollama (ej. `sqlcoder`, `codellama`) |
| Embeddings           | Modelo local vía Ollama o `sentence-transformers` |
| Backend / API        | Python + FastAPI                     |
| Validación de SQL    | `sqlglot` (parseo y verificación de que solo sea SELECT) |

## Estructura del repo

```
text-to-sql-rag/
├── app/
│   ├── core/          # lógica de RAG, embeddings, generación de SQL
│   ├── api/           # endpoints FastAPI
│   └── main.py         # punto de entrada
├── db/
│   ├── schema.sql       # esquema de la base de práctica
│   └── seed.sql         # datos de ejemplo
├── data/
│   └── schema_docs/     # descripciones de tablas/columnas para indexar (RAG)
├── scripts/
│   └── index_schema.py  # genera embeddings del esquema y los guarda
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

## Setup rápido (cuando el código esté implementado)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Levantar Postgres con pgvector (ejemplo con Docker)
docker run --name pg-vector -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d ankane/pgvector

# Cargar esquema y datos de ejemplo
psql -h localhost -U postgres -f db/schema.sql
psql -h localhost -U postgres -f db/seed.sql

# Indexar el esquema para RAG
python scripts/index_schema.py

# Levantar la API
uvicorn app.main:app --reload
```

## Ejemplo de uso (objetivo)

```
POST /query
{
  "question": "¿Cuántos clientes tienen facturas vencidas hace más de 30 días?"
}

Respuesta:
{
  "sql": "SELECT COUNT(DISTINCT customer_id) FROM invoices WHERE due_date < NOW() - INTERVAL '30 days' AND status = 'overdue';",
  "explanation": "Cuenta clientes distintos con al menos una factura vencida hace más de 30 días.",
  "rows_returned": 1
}
```

## Nota sobre seguridad

Este proyecto ejecuta SQL generado por un LLM contra una base de datos real.
Por diseño:
- Solo se permiten consultas `SELECT`.
- Se valida el SQL con un parser (`sqlglot`) antes de ejecutar, no solo con
  un filtro de texto.
- Hay límite de filas devueltas y timeout de ejecución.
- Nunca se ejecuta contra una base de datos de producción real.

## Cómo escalaría este proyecto a un esquema de producción real

Este proyecto usa un esquema de 4 tablas a propósito, para poder validar
cada decisión de diseño de punta a punta sin la complejidad de una base
real. Escalar a un esquema de empresa mediana/grande (decenas o cientos
de tablas) requeriría cambios concretos en dos frentes distintos:

### 1. Índices para que el SQL generado corra rápido

Con tablas de millones de filas, `statement_timeout` deja de ser
suficiente — mata queries lentas, pero no las hace rápidas. Haría falta:

- Índices explícitos en cada columna FK (Postgres no los crea
  automáticamente, a diferencia de las PK) — es la optimización más
  básica y más fácil de pasar por alto.
- Índices compuestos sobre los patrones de filtro reales que aparezcan
  en producción (por ejemplo, `(status, due_date)` en `invoices`, dado
  que varias de mis preguntas de prueba filtraban por ambas columnas a
  la vez).
- Estos patrones no se pueden adivinar de antemano — requieren
  loggear el SQL generado en producción y analizar qué se ejecuta
  realmente antes de decidir qué indexar.

### 2. Usar las foreign keys para mejorar el retrieval, no solo la ejecución

En este proyecto, `retrieval.py` busca cada tabla de forma
independiente por similitud semántica — funciona con 4 tablas porque
el LLM puede inferir los JOINs correctos solo por los nombres de
columna. A mayor escala esto se rompe: dos tablas relevantes pueden
aparecer en el contexto sin ninguna pista de cómo conectarlas.

La mejora sería un retrieval híbrido (semántico + estructural):

1. El retrieval semántico actual encuentra la tabla más relevante a
   la pregunta.
2. Antes de armar el contexto, se consulta el catálogo de Postgres
   (`information_schema.key_column_usage`) para encontrar qué tablas
   están conectadas por FK a esa tabla.
3. Esas tablas conectadas se agregan al contexto aunque su similitud
   semántica con la pregunta sea baja — la razón de incluirlas no es
   "se parecen a la pregunta", es "son alcanzables por JOIN".
4. El camino de JOIN explícito (`invoices.customer_id →
   customers.customer_id`) se pasa al LLM en el prompt, no solo las
   descripciones sueltas — reduce la alucinación de JOINs incorrectos.

### Por qué esto no es solo teoría

En un sistema de producción con el que tuve contacto, se le pidió a un
LLM afinar un conjunto de queries SQL ya existentes. El resultado fue
inconsistente: la mayoría de las veces devolvía resultados distintos
a los originales al "afinar" la query, y en varios casos no utilizaba
los índices más adecuados disponibles. Esto es consistente con lo que
encontré en este proyecto (`sql_generator.py`): un LLM puede generar
SQL sintácticamente válido y con apariencia razonable, sin que eso
garantice que sea semánticamente equivalente a la intención original
ni óptimo en su plan de ejecución — porque el modelo no tiene
visibilidad real del planificador de queries ni del estado de los
índices, solo genera texto plausible basado en patrones de
entrenamiento.

La mitigación real en un caso así no es "confiar más" en el LLM, sino
tratarlo como una fuente de sugerencias que se valida siempre contra
`EXPLAIN ANALYZE` y contra los resultados de la query original —
nunca como una fuente de verdad por sí sola.

## Notas de implementación

Ver [`NOTES.md`](./NOTES.md) — diario técnico con las decisiones tomadas
en cada módulo, pensado para poder explicar el proyecto de memoria en
una entrevista técnica.

## Autor

Santiago Andrés Aragón Guzmán — Backend Engineer (PL/SQL, Oracle) en
transición hacia AI Engineering.
[LinkedIn](https://linkedin.com/in/santiagoaragonguzman) ·
[GitHub](https://github.com/santiagoaragong)
