# Asistente Text-to-SQL con RAG de Esquema y Guardrails de Seguridad AST

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL 16](https://img.shields.io/badge/Motor-PostgreSQL%2016-336791?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Oracle 23c Free](https://img.shields.io/badge/Motor-Oracle%2023c%20Free-F80000?logo=oracle&logoColor=white)](#ejecutar-contra-oracle)
[![sqlglot AST](https://img.shields.io/badge/Seguridad-sqlglot%20AST%20Parser-FF6F00)](https://github.com/tobymao/sqlglot)
[![Tests: 1085 pasando](https://img.shields.io/badge/Tests-1085%20pasando-success?logo=pytest&logoColor=white)](#cómo-se-probó)
[![CI](https://github.com/andresaragon/text-to-sql-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/andresaragon/text-to-sql-rag/actions/workflows/ci.yml)
[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-yellow.svg)](LICENSE)

> **[🇬🇧 Read in English](README.md)**

Motor Text-to-SQL de grado empresarial que traduce preguntas de negocio en lenguaje natural a consultas SQL seguras, sintácticamente validadas y optimizadas para **PostgreSQL 16** y **Oracle Database 23c**.

Construido por un **Senior Database Engineer (5+ años en Oracle PL/SQL y PostgreSQL)** para unir la rigurosidad de bases de datos relacionales con **AI Engineering moderno (RAG de esquema podado, LLMs locales y Guardrails de seguridad por AST)**.

---

### ⚡ Capacidades Clave a Simple Vista

| Pilar | Implementación Empresarial |
|---|---|
| 🛡️ **Cortafuegos AST Zero-Regex** | Inspección estricta del Árbol de Sintaxis Abstracta con `sqlglot`. Valida nodo raíz `SELECT`/`UNION`, listas blancas de esquemas, CTEs, lista negra de funciones y recorta límites de filas. **245+ ataques adversariales bloqueados.** |
| 🗄️ **Doble Dialecto Empresarial** | Ejecución nativa tanto en **PostgreSQL 16** (con embeddings de esquema en `pgvector`) como en **Oracle Database 23c Free** (llamadas calificadas por paquete, hints, `FETCH FIRST` y sandboxing de solo lectura). |
| ⚡ **Resiliencia Fail-Fast Medida** | Reducción de latencia ante base inalcanzable de **138.5s (HTTP 500)** a **4.0s (HTTP 503)**; consultas fuera de dominio rechazadas en **16ms (HTTP 422)** antes de tocar el LLM. |
| 🔒 **Privacidad 100% On-Premise** | Inferencia GPU local mediante Ollama (`sqlcoder` / `qwen2.5-coder`). Cero definiciones de esquemas corporativos o datos sensibles expuestos a APIs externas. |

---

## 🏗️ Arquitectura del Sistema y Flujo de Datos

```mermaid
flowchart TD
    User(["👤 Usuario de Negocio / Cliente<br/><i>'¿Cuáles clientes tienen facturas vencidas?'</i>"]) --> API["⚡ Endpoint FastAPI<br/><code>POST /query</code>"]

    subgraph Capa1 ["1. RAG Semántico de Esquema Podado (pgvector)"]
        API --> Embed["Genera Embedding de Consulta<br/><i>paraphrase-multilingual-MiniLM</i>"]
        Embed --> CosineGate{"Filtro de Distancia Coseno<br/><code>MAX_SCHEMA_DISTANCE=0.7</code>"}
        CosineGate -- "Consulta fuera de dominio (>0.7)" --> RejDomain["❌ HTTP 422 Unprocessable<br/><i>Rechazo sin invocar LLM en 16ms</i>"]
        CosineGate -- "Consulta en dominio" --> RetDDL["Recupera DDLs Relevantes<br/><i>Tablas, Columnas y Reglas</i>"]
    end

    subgraph Capa2 ["2. Generación con LLM Local (GPU CUDA)"]
        RetDDL --> Prompt["Prompt con Contexto de Esquema<br/><i>Reglas de dialecto + DDLs podados + Pregunta</i>"]
        Prompt --> Ollama["Motor Local Ollama<br/><code>sqlcoder</code> | <code>qwen2.5-coder</code>"]
        Ollama --> RawSQL["SQL Candidato Generado"]
    end

    subgraph Capa3 ["3. Cortafuegos AST Empresarial (sqlglot)"]
        RawSQL --> ASTParse["Parsea Árbol de Sintaxis Abstracta"]
        ASTParse --> ASTCheck{"Validación Semántica AST<br/>• Solo nodo exp.Select / Union<br/>• Lista blanca de tablas (ALLOWED_SCHEMA)<br/>• Lista negra de funciones (pg_sleep, utl_http)<br/>• Recorte de filas (LIMIT 100)"}
        ASTCheck -- "Malicioso / No SELECT" --> RejSec["❌ HTTP 400 Bad Request<br/><code>UnsafeQueryError</code>"]
    end

    subgraph Capa4 ["4. Sandbox de Doble Ejecución"]
        ASTCheck -- "SQL Sanitizado" --> Router{"Enrutador<br/>TARGET_DIALECT"}
        Router -- "postgres" --> PG[("🐘 PostgreSQL 16<br/>Transacción de Solo Lectura<br/><code>statement_timeout = 5000</code>")]
        Router -- "oracle" --> ORA[("🔴 Oracle 23c Free<br/>Sesión de Solo Lectura<br/><code>call_timeout = 5s</code>")]
    end

    PG --> Response["✅ HTTP 200 OK<br/><code>{sql, rows, row_count}</code>"]
    ORA --> Response
    Response --> User
```

### 🖥️ Demostración en Consola

```bash
# 1. Traducción y ejecución de consulta legítima de negocio
$ curl -s -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "¿Cuáles clientes tienen facturas vencidas?"}' | jq
{
  "sql": "SELECT COUNT(DISTINCT customer_id) FROM invoices WHERE status = 'overdue' LIMIT 100;",
  "rows": [{"count": 4}],
  "row_count": 1
}

# 2. Intento de inyección SQL bloqueado por el Cortafuegos AST
$ curl -s -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Mostrar clientes; DROP TABLE customers; --"}' | jq
{
  "detail": "UnsafeQueryError: Multiple statements or non-SELECT expressions are strictly prohibited by the AST firewall."
}
```

### 🔄 Secuencia de Protocolo Detallada

```mermaid
sequenceDiagram
    autonumber
    actor Client as Usuario / Cliente
    participant API as FastAPI (/query)
    participant RAG as Motor de Recuperación (pgvector)
    participant LLM as LLM Local (Ollama / CUDA)
    participant Guard as Cortafuegos de Seguridad (sqlglot AST)
    participant DB as Sandbox PostgreSQL / Oracle

    Client->>API: POST /query {"question": "¿Cuáles clientes tienen facturas vencidas?"}
    API->>RAG: Vectoriza consulta y busca esquema relevante
    RAG-->>API: Retorna DDLs de tablas y descripciones de columnas
    API->>LLM: Prompt aumentado (Esquema contextual + Pregunta + Reglas)
    LLM-->>API: SQL candidato generado
    API->>Guard: Validación por Árbol de Sintaxis Abstracta (AST)
    alt Consulta maliciosa o No-SELECT
        Guard-->>API: Lanza UnsafeQueryError (bloqueada)
        API-->>Client: 400 Bad Request (Detalle del rechazo de seguridad)
    else Consulta segura
        Guard-->>API: SQL sanitizado con LIMIT y timeouts forzados
        API->>DB: Ejecución en transacción aislada de solo lectura
        DB-->>API: Filas resultantes
        API-->>Client: 200 OK {sql, rows, row_count}
    end
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

### Ejecutar contra Oracle

Para ejecutar la aplicación utilizando una base de datos Oracle Free 23.26.3 como base objetivo de ejecución (manteniendo PostgreSQL para los embeddings de RAG):

> **Requisitos de recursos y licencia:** La imagen de contenedor de Oracle Free (`gvenzl/oracle-free:23.26.3-slim-faststart`) requiere aproximadamente **4 GB** de memoria RAM y ~6.5 GB de espacio en disco. Ten en cuenta que la descarga de la imagen de Oracle está sujeta a los términos y condiciones de licencia de Oracle Free.

Inicia el entorno usando el archivo de override de Docker Compose:

```bash
docker compose -f docker-compose.yml -f docker-compose.oracle.yml up -d
```

Esto inicia:
- PostgreSQL + pgvector para los embeddings del esquema.
- Oracle Free 23.26.3 con el esquema `SALES` (propietario) y la cuenta de solo lectura `APP_RO`.
- El indexador de esquemas cargando la documentación de Oracle.
- La API de FastAPI configurada con `TARGET_DIALECT=oracle` y `TARGET_DATABASE_URL` apuntando a Oracle.

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
| `SCHEMA_CHECK_INTERVAL_SECONDS` | `0` | Opt-in. `0` = apagada. Con `> 0`, `/query` comprueba como máximo una vez por intervalo si se reindexó `schema_embeddings` (`count(*)` + `max(id)`) y, si cambió, limpia la caché de retrieval: las respuestas no quedan viejas hasta reiniciar Uvicorn. Nunca lanza: si la comprobación falla, no hace nada. Cada worker comprueba por su cuenta. |
| `FUNCTION_POLICY` | `denylist` | `denylist` (por defecto, sin cambios) o `allowlist`. Con `allowlist` el cortafuegos solo acepta las funciones de `ALLOWED_FUNCTIONS` (`app/core/safety.py`) más `ALLOWED_FUNCTIONS_EXTRA`; la lista negra sigue corriendo primero. Cualquier otro valor rechaza todas las consultas (fail-closed). |
| `ALLOWED_FUNCTIONS_EXTRA` | _(vacía)_ | Nombres de funciones, separados por comas, que se suman a la lista blanca con `FUNCTION_POLICY=allowlist` (p. ej. las propias de Oracle). Nunca reabre una función que la lista negra bloquea. |

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
6. **Dialecto Oracle (`TARGET_DIALECT=oracle`):** el cortafuegos aplica reglas específicas de Oracle (llamadas calificadas por paquete, secuencias, funciones de información y XML, db links, funciones de tabla, hints, `FETCH PERCENT`/`WITH TIES`, variables ligadas) y ejecuta con seguridad consultas validadas contra la base de datos Oracle objetivo en transacciones de solo lectura con `call_timeout` forzado. Ver [docs/oracle-firewall.md](docs/oracle-firewall.md).

---

## Cómo se probó

- **Suite de pruebas:** **1,085 pruebas automatizadas pasando** en CI (unitarias, compatibilidad de dialectos, invalidación de caché y mocks de timeouts). No necesitan servicios externos ni infraestructura pesada para ejecutarse.
- **Suite adversarial del firewall:** 245 pruebas adversariales contra los guardrails AST de `sqlglot`.
- **Benchmark con infraestructura real:** primera corrida contra Postgres + pgvector y Ollama reales (`sqlcoder`, RTX 4060). Informe completo: [`docs/benchmarks/2026-10-15.md`](docs/benchmarks/2026-10-15.md).
- **Benchmark A/B, Postgres vs Oracle vs SQL transpilado:** 30 preguntas, dos modelos locales, los mismos datos en ambas bases; el modelo pesa mucho más que el dialecto y transpilar cuesta en las preguntas de fechas. Informe: [`docs/benchmarks/2026-10-23-ab.es.md`](docs/benchmarks/2026-10-23-ab.es.md).

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
