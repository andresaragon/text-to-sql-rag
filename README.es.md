# Asistente Text-to-SQL con RAG y Guardrails AST

[![CI](https://github.com/andresaragon/text-to-sql-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/andresaragon/text-to-sql-rag/actions/workflows/ci.yml)

> **[🇬🇧 Read in English](README.md)**

Asistente que traduce preguntas en lenguaje natural a consultas SQL seguras, usando RAG (Retrieval-Augmented Generation) para darle al LLM el contexto real del esquema de base de datos — en vez de dejar que "adivine" nombres de tablas y columnas.

Proyecto personal para conectar experiencia de 5+ años en bases de datos relacionales (PL/SQL / Oracle / SQL Server) con desarrollo práctico de aplicaciones basadas en LLMs.

---

## Por qué este proyecto

Uno de los mayores cuellos de botella al llevar LLMs a empresas reales no es entrenar modelos, sino conectarlos de forma segura y precisa con datos estructurados ya existentes (SQL, ERPs, pipelines de datos). Este proyecto es un ejemplo end-to-end de ese problema, resuelto con herramientas propias:

- **LLM local** vía Ollama (GPU-acelerado, CUDA) — sin depender de APIs pagas ni filtrar datos a la nube.
- **RAG sobre el esquema**: embeddings de tablas, columnas, relaciones y ejemplos de queries, para que el modelo genere SQL con contexto real.
- **Capa de seguridad**: solo `SELECT`, validación AST con `sqlglot` (sin DDL/DML), límites de filas y timeout de ejecución.

---

## Estado del proyecto

✅ **Implementado y validado end-to-end** — desarrollo personal, listo para demostración técnica.

- [x] Fase 1 — Base de datos de práctica (dominio: facturación/cobranza)
- [x] Fase 2 — Indexado del esquema (embeddings + pgvector)
- [x] Fase 3 — Generación de SQL con Ollama
- [x] Fase 4 — Capa de validación y seguridad AST (`sqlglot`)
- [x] Fase 5 — API mínima (FastAPI) + Suite de tests (pytest)

---

## Stack Tecnológico

| Componente | Herramienta |
|---|---|
| **Base de datos** | PostgreSQL + extensión `pgvector` |
| **LLM Local** | Ollama (CUDA, GPU RTX 4060) |
| **Embeddings** | `sentence-transformers` / modelo local |
| **Backend / API** | Python 3.12 + FastAPI + Pydantic |
| **Validación de Seguridad** | `sqlglot` (Cortafuegos Semántico AST: lista blanca de tablas, funciones bloqueadas y LIMIT clamp) |
| **Testing** | `pytest` (24/24 tests unitarios de seguridad y caching pasando) |

---

## Estructura del Repositorio

```text
text-to-sql-rag/
├── app/
│   ├── api/
│   │   └── routes.py      # Endpoints FastAPI (/query, /health)
│   ├── core/
│   │   ├── db.py          # Conexión y ejecución segura en Postgres
│   │   ├── embeddings.py  # Generación de vectores de esquema
│   │   ├── retrieval.py   # Búsqueda semántica en pgvector
│   │   ├── safety.py      # Cortafuegos Semántico AST con sqlglot (SELECT/UNION, whitelist, blacklist, LIMIT)
│   │   └── sql_generator.py # Prompt contextualizado y cliente Ollama
│   ├── config.py          # Variables de entorno y configuración
│   └── main.py            # Punto de entrada de FastAPI
├── db/
│   ├── schema.sql         # Esquema DDL de práctica (facturación)
│   └── seed.sql           # Datos de prueba
├── data/
│   └── schema_docs/       # Documentación semántica de tablas/columnas para RAG
├── scripts/
│   └── index_schema.py    # Genera embeddings del esquema y los persiste
├── tests/
│   ├── test_caching.py    # Tests de cacheo de esquemas y queries
│   └── test_safety.py     # Suite de validación de seguridad (20/20 pasando)
├── requirements.txt
├── .env.example
├── LICENSE
├── NOTES.md               # Bitácora técnica y justificación de decisiones
└── README.md
```


---

## Setup Rápido

### Opción A: Docker Compose

Requisitos: Docker y Ollama ejecutándose en el host, con el modelo `sqlcoder` disponible:

```bash
ollama pull sqlcoder
docker compose up
```

La primera vez se descarga el modelo de embeddings. Cuando la API esté lista, prueba una consulta:

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Which customers have overdue invoices?"}'
```

La primera pregunta después de arrancar puede tardar unos 40 segundos mientras Ollama carga el modelo (medido en una RTX 4060); las siguientes suelen responder en segundos. Si el LLM no está disponible, la API responde `503`.

> **Ollama desde Docker:** En Docker Desktop para Windows y macOS, `host.docker.internal` permite llegar al Ollama del host. En Linux nativo, inicia Ollama en todas las interfaces con `OLLAMA_HOST=0.0.0.0 ollama serve`, o usa el perfil opcional de Compose: `docker compose --profile ollama up -d` y `docker compose exec ollama ollama pull sqlcoder`; con ese perfil, configura `OLLAMA_HOST=http://ollama:11434`. Docker Compose lee `OLLAMA_HOST` del entorno.

### Opción B: Configuración manual

#### 1. Clonar y configurar el entorno
```bash
git clone https://github.com/andresaragon/text-to-sql-rag.git
cd text-to-sql-rag

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. Levantar PostgreSQL con pgvector
```bash
docker run --name pg-vector -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d pgvector/pgvector:pg16
```

#### 3. Cargar esquema y datos de ejemplo
```bash
psql -h localhost -U postgres -f db/schema.sql
psql -h localhost -U postgres -f db/seed.sql
```

#### 4. Indexar esquema en pgvector
```bash
python -m scripts.index_schema
```

#### 5. Iniciar la API FastAPI
```bash
uvicorn app.main:app --reload
```

---

## ⚙️ Configuración y Variables de Entorno

La aplicación se configura mediante variables de entorno (o archivo `.env`):

| Variable | Default | Descripción |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/postgres` | Cadena de conexión a PostgreSQL. |
| `DB_POOL_SIZE` | `5` | Tamaño del pool de conexiones de SQLAlchemy. |
| `DB_MAX_OVERFLOW` | `10` | Conexiones adicionales permitidas sobre el pool antes de encolar. |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | Segundos de espera para obtener una conexión del pool antes de error. |
| `DB_CONNECT_TIMEOUT_SECONDS` | `3` | Timeout de conexión TCP en segundos para psycopg2, fallando rápido si Postgres no responde. |
| `MAX_QUESTION_CHARS` | `500` | Longitud máxima en caracteres permitida para la pregunta normalizada (422 si se supera). |
| `MAX_SCHEMA_DISTANCE` | `0.7` | Distancia coseno máxima en pgvector para aceptar el esquema; preguntas fuera de dominio se rechazan con 422 antes de llamar al LLM. |
| `WARMUP_ON_STARTUP` | `True` | Precarga el modelo de embeddings en el lifespan de FastAPI para eliminar latencia en el primer request (`"false"` o `"0"` para desactivar). |
| `OLLAMA_HOST` | `http://localhost:11434` | URL del servicio Ollama local. |
| `OLLAMA_MODEL` | `sqlcoder` | Modelo LLM utilizado para generación de SQL. |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Modelo SentenceTransformer para embeddings de esquema. |
| `MAX_ROWS_RETURNED` | `100` | Límite máximo de filas permitidas por consulta (forzado por guardrail AST). |
| `ALLOWED_SCHEMA` | `public` | Único esquema permitido para tablas calificadas (`esquema.tabla`); los nombres sin calificar no se ven afectados. No distingue mayúsculas. |
| `TARGET_DIALECT` | `postgres` | Dialecto SQL del cortafuegos: `postgres` u `oracle` (sin distinguir mayúsculas). Con `oracle` solo se valida el SQL; la ejecución contra Oracle aún no está implementada. Ver [docs/oracle-firewall.md](docs/oracle-firewall.md). |
| `QUERY_TIMEOUT_SECONDS` | `5` | Timeout de ejecución de la query en Postgres (segundos). |

---

## Ejemplo de Consulta

```http
POST /query
Content-Type: application/json

{
  "question": "¿Cuántos clientes tienen facturas vencidas hace más de 30 días?"
}
```

**Respuesta JSON:**
```json
{
  "sql": "SELECT COUNT(DISTINCT customer_id) FROM invoices WHERE due_date < NOW() - INTERVAL '30 days' AND status = 'overdue' LIMIT 100;",
  "rows": [{"count": 4}],
  "row_count": 1
}
```

---

## Arquitectura de Seguridad (Guardrails AST)

Este proyecto no utiliza filtros de texto por expresiones regulares (`regex`), ya que son trivialmente vulnerables a inyecciones complejas, comentarios o sentencias múltiples.
En su lugar, **`app/core/safety.py` descompone la consulta en un Árbol de Sintaxis Abstracta (AST) usando `sqlglot`**:

1. **Un solo statement permitido:** Rechaza inyecciones de queries compuestas (ej. `SELECT ...; INSERT ...`).
2. **Inspección de nodo raíz:** Garantiza que el statement sea estrictamente una expresión `exp.Select`.
3. **Clamping de filas (`LIMIT`):** Si la consulta no tiene `LIMIT`, se le inyecta automáticamente. Si solicita más filas que el máximo configurado, se recorta a dicho tope.
4. **Timeouts en motor:** Inyección de `statement_timeout` para neutralizar consultas desbocadas o scans completos en tablas masivas.
5. **Lista blanca de tablas y esquema:** Las tablas sin calificar se validan contra la lista blanca. Las tablas calificadas (`esquema.tabla`) solo se permiten si el esquema es `ALLOWED_SCHEMA` (por defecto `public`, sin distinguir mayúsculas); los nombres de 3 partes (`catálogo.esquema.tabla`) se rechazan siempre.
6. **Dialecto Oracle (`TARGET_DIALECT=oracle`):** valida SQL Oracle con reglas propias (llamadas calificadas por paquete, secuencias, funciones de información y XML, db links, funciones de tabla, hints, `FETCH` con `PERCENT`/`WITH TIES`, variables ligadas). Ver la tabla de amenazas en [docs/oracle-firewall.md](docs/oracle-firewall.md). Aviso: la ejecución contra Oracle (driver, timeouts) aún no está implementada; por ahora solo se valida el SQL.

---

## Cómo se probó

- **Suite unitaria:** 413 pruebas que no necesitan servicios externos (ni Postgres ni Ollama). Corren en CI en cada push a `main` y en cada pull request.
- **Suite adversarial del firewall:** 245 pruebas adversariales contra los guardrails AST de `sqlglot`.
- **Benchmark con infraestructura real:** primera corrida contra Postgres + pgvector y Ollama reales (`sqlcoder`, RTX 4060). Informe completo: [`docs/benchmarks/2026-10-15.md`](docs/benchmarks/2026-10-15.md).

| Métrica | Antes | Después |
|---|---|---|
| Base inalcanzable (IP que no responde) | **HTTP 500 en 138.5 s** | **HTTP 503 en 4.0 s** |
| Preguntas fuera del dominio (3) | 2 × 200 con SQL inventado, 1 × 400; p50 1000 ms | 3 × 422 sin llamar al LLM; p50 16 ms |
| Pregunta válida del dominio, en frío (p50, 9 corridas) | 1188 ms | 1122 ms — sin cambio; cerca del 98 % del tiempo es el LLM |

> Medido en un portátil con RTX 4060 (8 GB VRAM) bajo WSL2, no en un servidor. Estas cifras salen de esa única corrida; el informe tiene el entorno completo y el resto de resultados.

---

## Cómo Escalar este Proyecto a Producción

Ver detalle completo y reflexiones técnicas en [`NOTES.md`](./NOTES.md). En esquemas corporativos de cientos de tablas se implementaría:
1. **Retrieval Estructural de Claves Foráneas (FK Graph):** Combinar la similitud semántica con un grafo de relaciones extraído de `information_schema.key_column_usage`, inyectando al LLM el camino explícito de `JOIN`.
2. **Validación con `EXPLAIN ANALYZE`:** Validar el costo estimado de ejecución antes de lanzar la query a producción.

---

## Autor

**Santiago Andrés Aragón Guzmán**  
*Senior Backend Engineer (Oracle PL/SQL, SQL Server) en transición a AI Engineer.*  
- **LinkedIn:** [linkedin.com/in/santiagoaragonguzman](https://www.linkedin.com/in/santiagoaragonguzman)  
- **GitHub:** [github.com/andresaragon](https://github.com/andresaragon)  
- **Email:** [santiagoaragon.sistemas@gmail.com](mailto:santiagoaragon.sistemas@gmail.com)
