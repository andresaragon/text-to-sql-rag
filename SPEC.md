# SPEC — Oracle como base objetivo de `POST /query`

(Sustituye al SPEC.md de la tarea anterior —optimización de `/query`—, que sigue en el historial de git.) Delegado con `/delegar`; Claude es el checker.

Base: `main` en `fab3d4e` (el firewall ya valida SQL Oracle con `TARGET_DIALECT=oracle`; **no ejecuta** nada contra Oracle).

## Objetivo
Ejecutar el SQL ya validado contra una **base objetivo** Oracle, manteniendo el almacén de embeddings (pgvector) en Postgres. Hoy un solo engine hace de almacén de embeddings y de base objetivo.

## Hechos medidos (Oracle Free 23.26.3 real, `oracledb` 26.0.1 thin, SQLAlchemy 2.0.35)
- URL de conexión: `oracle+oracledb://USUARIO:CLAVE@HOST:1521/?service_name=FREEPDB1`.
- `call_timeout` (ms) en la conexión DBAPI → `DPY-4024` exactamente al vencer; la conexión sigue usable.
- `SET TRANSACTION READ ONLY` + escritura → `ORA-01456`. Se ejecuta con `conn.exec_driver_sql(...)`.
- `ORA-01466` ("table definition has changed") aparece al leer en READ ONLY una tabla creada hace **segundos**; desaparece en ~1 min. Es transitorio.
- `ALTER SESSION SET CURRENT_SCHEMA = SALES` permite nombres sin calificar con una cuenta que solo tiene `SELECT`.
- SQLAlchemy devuelve las columnas Oracle en minúsculas. `text()` admite `:` dentro de literales.
- Códigos: tabla `ORA-00942`, columna `ORA-00904`, sintaxis `ORA-00900`/`ORA-00933`/`ORA-03047`, `/0` `ORA-01476`, conversión `ORA-01722`, clave `ORA-01017`, puerto cerrado o servicio inexistente `DPY-6005`.
- Los scripts de `/container-entrypoint-initdb.d` se ejecutan en **`CDB$ROOT`**, no en el PDB (medido: `select sys_context('USERENV','CON_NAME')` da `CDB$ROOT`). Sin cambiar de contenedor, `CREATE USER` crea usuarios *comunes* y sus privilegios quedan solo en la raíz: en `FREEPDB1` el login da `ORA-01045`. **Cada script debe empezar por `ALTER SESSION SET CONTAINER = FREEPDB1;`** (cada archivo es una sesión distinta).
- La imagen `gvenzl/oracle-free:23.26.3-slim-faststart` **no declara healthcheck** (trae `healthcheck.sh`, sale 0 cuando está lista). Ocupa ~4 GB de RAM y 6,5 GB de disco; arranca desde cero en ~12 s.

## Alcance
1. Configuración: `TARGET_DATABASE_URL` y la dependencia `oracledb==26.0.1`.
2. Capa de datos (`app/core/db.py`): engine objetivo por dialecto, ejecución Oracle, mapeo de errores.
3. Prompt y documentos de esquema por dialecto; el indexado elige los documentos.
4. Scripts SQL de Oracle (`db/oracle/`) con propietario y cuenta de solo lectura.
5. `docker-compose.oracle.yml` (override) con healthcheck y README «Run against Oracle».
6. Workflow manual de integración y documentación.

## Fuera de alcance
La prueba A/B y el generador de datos (PR D). Tocar `app/core/safety.py` (el firewall ya está hecho). Cambiar el comportamiento con `TARGET_DIALECT=postgres`. Cualquier push o despliegue.

## Interfaces (contrato; los tests lo verifican)
**`app/config.py`**: `settings.target_database_url` = `TARGET_DATABASE_URL` si está definido y no vacío; si no, `settings.database_url`.

**`app/core/db.py`** (nombres exactos):
- `_target_engine()`: devuelve el engine donde se ejecuta el SQL generado, cacheado. Con dialecto `postgres` y `target_database_url == database_url` devuelve exactamente `_engine` (los tests existentes parchean `app.core.db._engine`). Con `oracle` crea un engine con la URL objetivo, `pool_pre_ping=True`, los tamaños de pool de `settings`, `connect_args={"tcp_connect_timeout": settings.db_connect_timeout_seconds}` y un evento `connect` que fija `call_timeout = settings.query_timeout_seconds * 1000` y, solo si `settings.allowed_schema` no es `public` (sin distinguir mayúsculas), `ALTER SESSION SET CURRENT_SCHEMA = <esquema>` (el esquema debe cumplir `^[A-Za-z][A-Za-z0-9_$#]*$`, si no `ValueError`).
- `reset_target_engine()`: descarta el engine cacheado (y lo cierra con `dispose()`).
- `map_oracle_error(exc) -> Exception`: acepta una excepción de SQLAlchemy (`DBAPIError`, usa `.orig`) o la de `oracledb`; lee el código en `orig.args[0].full_code`. Devuelve (no lanza): `QueryTimeoutError("La consulta tardó demasiado, intenta ser más específico.")` para `DPY-4024`; `DatabaseUnavailableError("Base de datos no disponible.")` para `ORA-01017`, `ORA-01033`, `ORA-01034`, `ORA-01089`, `ORA-03113`, `ORA-03114`, `ORA-03135`, `ORA-12154`, `ORA-12170`, `ORA-12514`, `ORA-12516`, `ORA-12519`, `ORA-12537`, `ORA-12541` y cualquier `DPY-6xxx`, `DPY-4011`; `QueryExecutionError(f"No se pudo ejecutar la consulta: {mensaje}")` para cualquier otro código (incluido uno desconocido o ausente).
- `clear_schema_embeddings() -> int`: borra todas las filas de `schema_embeddings` usando **siempre el engine de metadatos `_engine`** (Postgres) y devuelve cuántas borró (`rowcount`). Motivo: `scripts/index_schema.py` borraba con `execute_select("DELETE FROM schema_embeddings …")`; con Oracle como base objetivo ese `DELETE` iría a Oracle y el indexado fallaría siempre. `execute_select` queda solo para el SELECT del usuario sobre la base objetivo.
- `execute_select(sql)` con dialecto `oracle`: abre una conexión del engine objetivo y una transacción, ejecuta **primero** `conn.exec_driver_sql("SET TRANSACTION READ ONLY")` y luego `conn.execute(text(sql))`; devuelve `list[dict]` con claves en minúsculas. No emite `statement_timeout`. Cualquier `DBAPIError` (también al conectar) se convierte con `map_oracle_error` y se lanza con `from exc`. `ORA-01466` se reintenta hasta 5 veces con `time.sleep(1)` (módulo `time` importado en `db.py`, nueva conexión en cada intento); agotados los intentos, `QueryExecutionError`. Con `postgres` el comportamiento es idéntico al actual.

**`app/core/sql_generator.py`**: `build_prompt(question, schema_context, dialect=None) -> str` y `generate_sql(question, schema_context, dialect=None)` (sigue siendo `lru_cache`; `None` = `settings.target_dialect`). Con `postgres` el prompt es **idéntico** al actual (`PROMPT_TEMPLATE`). Con `oracle`: menciona Oracle, exige `FETCH FIRST n ROWS ONLY` (nunca `LIMIT`), `SYSDATE`/`TRUNC(fecha,'MM')`/`LISTAGG`, nada de `::`, `ILIKE`, `NOW()`, `GROUP BY` posicional, `;` final, variables ligadas ni hints, y mantiene la regla de solo `SELECT` y la de no copiar literales de los ejemplos. `app/api/routes.py` llama `generate_sql(question, contexto, settings.target_dialect)`.

**`data/schema_docs/tables_oracle.md`** y **`scripts/index_schema.py`**: `load_schema_fragments(dialect=None)` (`None` = `settings.target_dialect`) lee `tables.md` para `postgres` y `tables_oracle.md` para `oracle`; `main()` pasa el dialecto de `settings`, borra con `clear_schema_embeddings()` (importada por nombre desde `app.core.db`) y **no** usa `execute_select`. `tables_oracle.md` conserva la estructura de `tables.md` (4 tablas y al menos 6 ejemplos `Pregunta:`/`SQL:`), sin construcciones de Postgres (`::`, `ILIKE`, `NOW()`, `INTERVAL '… days'`, `LIMIT`, `GROUP BY 1`, `STRING_AGG`, `date_trunc`), y **cada SQL de ejemplo pasa el firewall Oracle** y se ejecuta sin error contra la base de ejemplo.

**`db/oracle/`** (se monta en `/container-entrypoint-initdb.d`): `01_users.sql`, `02_schema.sql`, `03_seed.sql`. Los tres empiezan por `ALTER SESSION SET CONTAINER = FREEPDB1;` y los nombres de objetos van calificados con `sales.` (se ejecutan como SYS).
- Propietario `SALES` (clave de demo `sales-demo-pw`, `QUOTA UNLIMITED ON users`, privilegios solo `CREATE SESSION`, `CREATE TABLE`, `CREATE SEQUENCE`) y cuenta de lectura `APP_RO` (clave de demo `app-ro-demo-pw`) con **solo** `CREATE SESSION` y `SELECT` sobre las 4 tablas. Prohibido: `TO PUBLIC`, `EXECUTE`, `INSERT`/`UPDATE`/`DELETE`/`DBA`/`RESOURCE`/`CONNECT`.
- Tablas `customers`, `invoices`, `payments`, `collection_actions` equivalentes a `db/schema.sql` (identidad, `VARCHAR2`, `NUMBER`, `CHECK` de `status`) **sin** `schema_embeddings` ni `vector`; datos equivalentes a `db/seed.sql` (3 clientes, 4 facturas, 1 pago, 3 acciones).

**`docker-compose.oracle.yml`** (override; se usa con `-f docker-compose.yml -f docker-compose.oracle.yml`): servicio `oracle` con la imagen `gvenzl/oracle-free:23.26.3-slim-faststart`, `ORACLE_PASSWORD=oracle-demo-admin-pw`, `./db/oracle` montado solo lectura en `/container-entrypoint-initdb.d`, volumen de datos, puerto `127.0.0.1:1521:1521` y `healthcheck` con `healthcheck.sh`; `api` e `indexer` con `TARGET_DIALECT=oracle` y `ALLOWED_SCHEMA=SALES`; `api` con `TARGET_DATABASE_URL=oracle+oracledb://app_ro:app-ro-demo-pw@oracle:1521/?service_name=FREEPDB1` y `depends_on` del `oracle` en `service_healthy`. `docker-compose.yml` no cambia.

**`.github/workflows/oracle-integration.yml`**: solo `workflow_dispatch` (nunca `push` ni `pull_request`); instala dependencias como `ci.yml` (torch CPU incluido), levanta Oracle con el override y ejecuta `ORACLE_INTEGRATION=1 pytest tests/integration`.

**Documentación**: `README.md` («Run against Oracle», con el aviso de ~4 GB de RAM y que la imagen Oracle se descarga con su propia licencia) y `README.es.md` («Ejecutar contra Oracle»); `.env.example` documenta `TARGET_DATABASE_URL`; `docs/oracle-firewall.md` gana una sección «Execution» (qué se ejecuta, solo lectura, `call_timeout`, mapeo de errores) y actualiza «Limitations» (ya hay timeout; lo demás sigue igual).

## Criterios de aceptación
| # | Criterio | Cómo se verifica |
|---|---|---|
| CA1 | `settings.target_database_url` cae a `database_url` y respeta `TARGET_DATABASE_URL` | `tests/test_oracle_target.py` (subproceso) |
| CA2 | `map_oracle_error` devuelve la clase y el mensaje exactos para cada código de la lista | `tests/test_oracle_target.py` (tabla) |
| CA3 | En Oracle, `exec_driver_sql("SET TRANSACTION READ ONLY")` va antes del SELECT, no hay `statement_timeout`, `ORA-01466` se reintenta 5 veces con `sleep(1)` y luego falla | `tests/test_oracle_target.py` (mocks) |
| CA4 | `build_prompt`/`generate_sql`/`routes` respetan el dialecto; el prompt Postgres no cambia | `tests/test_oracle_target.py` |
| CA5 | `load_schema_fragments` por dialecto; los ejemplos Oracle no tienen construcciones de Postgres y pasan el firewall; el indexado borra por el engine de metadatos y no usa `execute_select` | `tests/test_oracle_target.py` |
| CA6 | `db/oracle/*.sql`, `docker-compose.oracle.yml`, workflow, README y `.env.example` cumplen el contrato (privilegios mínimos, healthcheck, puertos locales, `workflow_dispatch`) | `tests/test_oracle_assets.py` |
| CA7 | Contra Oracle real: consulta con y sin calificar, timeout `QueryTimeoutError` y conexión reutilizable, solo lectura incluso con el propietario, errores 400/503, ejemplos del RAG ejecutables, matriz de ataques (el firewall los rechaza y, sin firewall, tres de ellos sí ejecutan) | `tests/integration/test_oracle_execution.py` con Oracle levantado por `tests/run_acceptance.sh` |
| CA8 | Sin regresiones: toda la suite anterior (628 pruebas) sigue verde y `ruff check .` limpio | `tests/run_acceptance.sh` |

## Comandos
- Pruebas y aceptación completa (levanta y baja Oracle sola): `bash tests/run_acceptance.sh`
- Solo unidad y estática (sin Docker): `python -m pytest -q --ignore=tests/integration`
- Lint: `python -m ruff check .`
- Entorno: Python 3.12 con `requirements.txt` y `requirements-dev.txt`; `oracledb==26.0.1` es una dependencia fijada.

## Notas para el maker
- No edites `SPEC.md` ni los tests (solo lectura). Si un test te parece mal, dilo en el HANDOFF, no lo cambies.
- `app/core/safety.py` está fuera de alcance. No hagas push.
- Las claves de las cuentas de demo son públicas y locales a propósito (igual que `postgres/postgres`).
