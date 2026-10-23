# Text-to-SQL Assistant with Schema RAG & AST Safety Guardrails

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL + pgvector](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![sqlglot AST](https://img.shields.io/badge/Security-sqlglot%20AST%20Parser-FF6F00)](https://github.com/tobymao/sqlglot)
[![CI](https://github.com/andresaragon/text-to-sql-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/andresaragon/text-to-sql-rag/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **[🇪🇸 Leer versión en Español](README.es.md)**

An end-to-end AI system that converts natural language business queries into secure, syntactically verified, and performant SQL queries. 

Designed and built to bridge **5+ years of production experience with Oracle PL/SQL and SQL** with modern **AI Engineering (LLMs, RAG, and Agentic workflows)**.

---

## 🏗️ Architecture Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client as User / Client App
    participant API as FastAPI (/query)
    participant RAG as Retrieval Engine (pgvector)
    participant LLM as Local LLM (Ollama / CUDA)
    participant Guard as Safety Engine (sqlglot AST)
    participant DB as PostgreSQL Sandbox

    Client->>API: POST /query {"question": "How many customers have overdue invoices?"}
    API->>RAG: Embed query & search relevant schema
    RAG-->>API: Returns relevant table DDLs & semantic column descriptions
    API->>LLM: Augmented Prompt (Contextual Schema + Question + Dialect rules)
    LLM-->>API: Generated SQL query candidate
    API->>Guard: Parse Abstract Syntax Tree (AST) validation
    alt Malicious or Non-SELECT query
        Guard-->>API: Raises UnsafeQueryError (blocked)
        API-->>Client: 400 Bad Request (Detailed safety rejection)
    else Safe query
        Guard-->>API: Sanitized SQL with enforced LIMIT and timeouts
        API->>DB: Execute query in isolated read-only transaction
        DB-->>API: Query result rows
        API-->>Client: 200 OK {sql, rows, row_count}
    end
```

---

## 🎯 Why This Project Matters

One of the greatest challenges in deploying generative AI in enterprise environments is connecting LLMs to structured corporate databases without risking:
1. **Schema Hallucinations:** Asking the LLM to write queries against a 50+ table schema often causes it to invent non-existent column names or faulty join conditions.
2. **Security Vulnerabilities:** Naive regex filters fail against obfuscated SQL injections, multi-statement payloads (`SELECT ...; DROP TABLE`), or comments disguised as DDL.
3. **Runaway Queries:** Slow full-table scans that exhaust production memory and database connection pools.

This project delivers a production-pattern solution:
- **Schema-Pruned RAG:** Embeds database entities (tables, columns, business definitions) into `pgvector`. Only the top relevant schema slice is dynamically injected into the prompt.
- **Zero-Regex AST Validation (`sqlglot`):** Inspects the query's Abstract Syntax Tree to ensure by design that **only a single `SELECT`** is executed, backed by 245 adversarial tests.
- **Privacy-First Local Inference:** Fully runnable via **Ollama (GPU CUDA-accelerated)**, ensuring sensitive company schema details never leave on-premise infrastructure.

---

## 🛡️ AST-Level Safety Guardrails (The Core Engine)

Rather than fragile regex pattern matching, [`app/core/safety.py`](app/core/safety.py) uses `sqlglot` to parse and validate incoming SQL against an enterprise Semantic AST Firewall:

* **Strict Single Statement Check:** Rejects multiple semicolons and stacked statements (e.g., `SELECT 1; DROP TABLE users;`).
* **Root Expression Verification:** Confirms the root node is strictly `exp.Select` or `exp.Union`. Any `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, or `TRUNCATE` operations trigger an immediate `NonSelectQueryError`.
* **Table Whitelist Enforcement:** Restricts execution strictly to authorized business domain tables (`customers`, `invoices`, `payments`, `collection_actions`). Rejects attempts to access system catalogs (`pg_shadow`, `pg_authid`, `information_schema`) or internal RAG metadata (`schema_embeddings`) with `TableNotAllowedError`. The schema is validated too: unqualified table names pass, schema-qualified names (`schema.table`) pass only when the schema equals `ALLOWED_SCHEMA` (default `public`, case-insensitive), and three-part names (`catalog.schema.table`) are always rejected.
* **CTE Resolution:** Accurately discounts Common Table Expression names (`WITH ... AS (...)`) from physical table checks to allow advanced analytics without false positives.
* **Dangerous Function Blacklist:** Blocks time-based blind SQLi (`pg_sleep`), server-side exfiltration (`pg_read_file`, `query_to_xml`), and lateral movement (`dblink`) with `DangerousFunctionError`.
* **Row-Count Clamping:** Inspects the AST for existing `LIMIT` clauses:
  - If omitted, injects a default `LIMIT 100`.
  - If present but exceeds safety thresholds, clamps it to the maximum allowable limit.
  - Safely handles non-integer or malformed limits (`LIMIT ALL`, expressions) by falling back to safe limits.
* **Engine-Level Timeouts:** Automatically sets `statement_timeout = 5000` (5s) per session to eliminate unindexed full-table runaway queries.
* **Oracle dialect (`TARGET_DIALECT=oracle`, validation only):** the same firewall applies Oracle-specific rules (package-qualified calls, sequences, information/XML functions, db links, table functions, hints, `FETCH PERCENT`/`WITH TIES`, bind variables). See the threat table in [docs/oracle-firewall.md](docs/oracle-firewall.md). Executing queries against Oracle (driver, timeouts) is not implemented yet; for now only Oracle SQL is validated.

---

## 🧪 Test Suite

Unit tests cover critical security edge cases, ensuring injection bypasses are caught before hitting the database:

```bash
# Run tests inside the virtual environment
pytest tests/ -v
```

```text
======================= 413 passed, 1 warning in 52.84s ========================
```


---

## 🚀 Quickstart

### Option A: Docker Compose

Requirements: Docker and Ollama running on the host, with the `sqlcoder` model available:

```bash
ollama pull sqlcoder
docker compose up
```

The first startup downloads the embedding model. Once the API is ready, try a query:

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "Which customers have overdue invoices?"}'
```

The first question after startup can take about 40 seconds while Ollama loads the model (measured on an RTX 4060); later questions usually respond in seconds. If the LLM is unavailable, the API returns `503`.

> **Ollama from Docker:** On Docker Desktop for Windows and macOS, `host.docker.internal` reaches Ollama on the host. On native Linux, start host Ollama listening on all interfaces with `OLLAMA_HOST=0.0.0.0 ollama serve`, or use the optional Compose profile: `docker compose --profile ollama up -d` and `docker compose exec ollama ollama pull sqlcoder`; with that profile, set `OLLAMA_HOST=http://ollama:11434`. Docker Compose reads `OLLAMA_HOST` from the environment.

### Option B: Manual setup

#### 1. Clone & Set Up Environment
```bash
git clone https://github.com/andresaragon/text-to-sql-rag.git
cd text-to-sql-rag

python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

#### 2. Launch PostgreSQL with pgvector
```bash
docker run --name pg-vector \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

#### 3. Initialize Database & Seed Sample Data
```bash
psql -h localhost -U postgres -f db/schema.sql
psql -h localhost -U postgres -f db/seed.sql
```

#### 4. Index Schema into pgvector
```bash
python -m scripts.index_schema
```

#### 5. Launch FastAPI Backend
```bash
uvicorn app.main:app --reload --port 8000
```

---

## ⚙️ Configuration & Environment Variables

The application is configured using environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/postgres` | PostgreSQL connection string. |
| `DB_POOL_SIZE` | `5` | SQLAlchemy connection pool size. |
| `DB_MAX_OVERFLOW` | `10` | Maximum overflow connections allowed beyond pool size. |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | Timeout in seconds to wait when retrieving a connection from the pool. |
| `DB_CONNECT_TIMEOUT_SECONDS` | `3` | Connection timeout in seconds passed to psycopg2 driver to fail fast if database is unreachable. |
| `MAX_QUESTION_CHARS` | `500` | Maximum character length allowed for user questions after whitespace normalization (rejects with 422 if exceeded). |
| `MAX_SCHEMA_DISTANCE` | `0.7` | Maximum cosine distance threshold for schema retrieval; off-domain queries exceeding this are rejected early with 422. |
| `WARMUP_ON_STARTUP` | `True` | Pre-load the embedding model during application startup to avoid first-request latency (`"false"` or `"0"` to disable). |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama service endpoint URL. |
| `OLLAMA_MODEL` | `sqlcoder` | LLM model name used for SQL generation. |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | SentenceTransformer model used for embeddings. |
| `MAX_ROWS_RETURNED` | `100` | Maximum rows allowed in SELECT queries (clamped by AST safety guardrails). |
| `ALLOWED_SCHEMA` | `public` | Only schema allowed for schema-qualified table names (`schema.table`); unqualified names are not affected. Case-insensitive. |
| `TARGET_DIALECT` | `postgres` | SQL dialect used by the firewall: `postgres` or `oracle` (case-insensitive). With `oracle` only SQL is validated; executing queries against Oracle (driver, timeouts) is not implemented yet. See [docs/oracle-firewall.md](docs/oracle-firewall.md). |
| `QUERY_TIMEOUT_SECONDS` | `5` | Query execution timeout in seconds. |

---

## 📡 API Usage

### `POST /query`
Translates a natural language question into safe SQL and executes it:

```bash
curl -X POST "http://localhost:8000/query" \
     -H "Content-Type: application/json" \
     -d '{"question": "Which customers have overdue invoices older than 30 days?"}'
```

**Response (200 OK):**
```json
{
  "sql": "SELECT COUNT(DISTINCT customer_id) FROM invoices WHERE due_date < NOW() - INTERVAL '30 days' AND status = 'overdue' LIMIT 100;",
  "rows": [
    {
      "count": 4
    }
  ],
  "row_count": 1
}
```

---

## 🔬 How it was tested

- **Unit suite:** 413 tests that need no external services (no Postgres, no Ollama). They run in CI on pushes to `main` and on every pull request.
- **Adversarial firewall suite:** 245 adversarial tests against the `sqlglot` AST guardrails.
- **Benchmark with real infrastructure:** first run against real Postgres + pgvector and Ollama (`sqlcoder`, RTX 4060). Full report: [`docs/benchmarks/2026-10-15.md`](docs/benchmarks/2026-10-15.md).

| Metric | Before | After |
|---|---|---|
| Unreachable database (IP that does not respond) | **HTTP 500 in 138.5 s** | **HTTP 503 in 4.0 s** |
| Out-of-domain questions (3) | 2 × 200 with invented SQL, 1 × 400; p50 1000 ms | 3 × 422 without calling the LLM; p50 16 ms |
| Valid in-domain question, cold (p50, 9 runs) | 1188 ms | 1122 ms — unchanged; about 98 % of the time is the LLM |

> Measured on a laptop with an RTX 4060 (8 GB VRAM) under WSL2, not on a server. These numbers come from that single run; the report has the full environment and the rest of the results.

---

## 📈 Production Scaling Blueprint (Insights from 5+ Years in DBs)

Full technical deliberations and trade-offs are documented in [`NOTES.md`](./NOTES.md). When transitioning this architecture to 100+ table schemas:

1. **Foreign Key Graph Retrieval (Structural + Semantic Hybrid):**
   Pure semantic similarity fails when queries require multi-hop joins across tables with unrelated names. A production RAG system must query `information_schema.key_column_usage` to traverse the foreign-key graph and inject the explicit join path (`invoices.customer_id → customers.customer_id`) into the prompt.
2. **`EXPLAIN ANALYZE` Cost Validation:**
   LLMs generate plausible text, not optimal execution plans. Integrating an automated `EXPLAIN (FORMAT JSON)` pre-flight step allows rejecting queries whose estimated cost exceeds a strict budget before actual execution.
3. **FK Index Enforcement:**
   PostgreSQL does not automatically index foreign keys. Automated schema audits ensure indexes exist on joined columns to prevent table locks and slow joins under LLM load.

---

## 👤 Author

**Santiago Andrés Aragón Guzmán**  
*Backend Developer (Oracle PL/SQL) transitioning to AI Engineering.*  

- 💼 **LinkedIn:** [linkedin.com/in/santiagoaragonguzman](https://www.linkedin.com/in/santiagoaragonguzman)  
- 🐙 **GitHub:** [@andresaragon](https://github.com/andresaragon)  
- 📧 **Email:** [santiagoaragon.sistemas@gmail.com](mailto:santiagoaragon.sistemas@gmail.com)
