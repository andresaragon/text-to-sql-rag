# Asistente Text-to-SQL con RAG y Guardrails AST

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
| **Validación de Seguridad** | `sqlglot` (parseo de AST y verificación estricta de solo SELECT) |
| **Testing** | `pytest` (8/8 tests unitarios de seguridad pasando) |

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
│   │   ├── safety.py      # Guardrails AST con sqlglot (SELECT-only, LIMIT clamp)
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
│   └── test_safety.py     # Suite de validación de seguridad (8/8 pasando)
├── requirements.txt
├── .env.example
├── LICENSE
├── NOTES.md               # Bitácora técnica y justificación de decisiones
└── README.md
```

---

## Setup Rápido

```bash
# 1. Clonar entorno
git clone https://github.com/andresaragon/text-to-sql-rag.git
cd text-to-sql-rag

# 2. Configurar entorno virtual e instalar dependencias
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Levantar Postgres con pgvector (Docker)
docker run --name pg-vector -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d ankane/pgvector

# 4. Cargar esquema y datos de ejemplo
psql -h localhost -U postgres -f db/schema.sql
psql -h localhost -U postgres -f db/seed.sql

# 5. Indexar esquema en pgvector
python scripts/index_schema.py

# 6. Ejecutar tests de seguridad
pytest tests/

# 7. Iniciar la API
uvicorn app.main:app --reload
```

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
