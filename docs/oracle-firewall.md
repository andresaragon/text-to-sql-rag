# Oracle dialect for the SQL firewall

The firewall in [`app/core/safety.py`](../app/core/safety.py) can validate SQL written in the Oracle dialect. Select it with:

```bash
TARGET_DIALECT=oracle   # default: postgres (case-insensitive; any other value is rejected)
```

`validate_and_prepare`, `validate_ast` and `enforce_limit` also take a `dialect` argument. When it is `None`, the value of `settings.target_dialect` is used at call time. With `postgres` the behaviour is the same as before the Oracle rules were added.

> **Status:** Oracle SQL validation and execution are supported. Queries validated by the firewall are executed against the target Oracle database using `oracledb` in thin mode with strict read-only transactions, timeouts, and error mapping.

## Threat table

Each row describes how the construct reaches the AST (sqlglot 25.24.0, `dialect="oracle"`), the rule that rejects or normalizes it, and the test that covers it. Test names are in [`tests/test_safety_oracle.py`](../tests/test_safety_oracle.py).

| Threat | How it arrives in the AST | Rule | Test |
|---|---|---|---|
| Package or schema-qualified calls (`UTL_HTTP.REQUEST`, `DBMS_LOCK.SLEEP`, `DBMS_PIPE`, `DBMS_XMLGEN`, `SYS.DBMS_LOCK.SLEEP`) | `exp.Dot` whose `expression` is a function; the function name loses its package | Any qualified call is rejected (`DangerousFunctionError`). Quoted identifiers, comments or spaces between the parts do not change this. Chained calls such as `HTTPURITYPE(..).GETCLOB()` are rejected too. | `test_reject_package_and_schema_qualified_calls` |
| Package functions called without parentheses (`UTL_INADDR.GET_HOST_NAME`) | `exp.Column` with a qualifier | The qualifier must be a table or alias declared in the query; otherwise it is treated as a package and rejected. Column aliases do not count as declarations. | `test_reject_qualifiers_that_are_not_declared_tables_or_aliases`; declared qualifiers are accepted by `test_accept_qualifiers_that_are_declared_tables_or_aliases` |
| Sequences (`seq.NEXTVAL`, `seq.CURRVAL`) | `exp.Column` named `nextval` / `currval`, with or without a qualifier | Rejected regardless of qualifier | `test_reject_sequences_and_information_functions` |
| Information functions (`SYS_CONTEXT`, `USERENV`) | `exp.Func` with the name `sys_context` / `userenv` | Blocked by name | `test_reject_sequences_and_information_functions` |
| Session identity pseudocolumns (`USER`, `UID`) | `exp.Column` named `user` / `uid` without a qualifier | Rejected when unqualified. A qualified column such as `t.user` is a normal column and is not blocked. | `test_reject_sequences_and_information_functions` |
| XML functions (`XMLTYPE`, `EXTRACTVALUE`, `XMLQUERY`, `XMLSEQUENCE`) | `exp.Func` with those names | Blocked by name | `test_reject_sequences_and_information_functions` |
| URI functions (`HTTPURITYPE`, `URITYPE`, `DBURITYPE`, `XDBURITYPE`) | `exp.Func` with those names | Blocked by name | `test_reject_package_and_schema_qualified_calls` (`HTTPURITYPE(..).GETCLOB()`) and `test_reject_sequences_and_information_functions` |
| Table functions (`TABLE()`, `XMLTABLE`, `JSON_TABLE`) | `exp.Table` whose `.this` is not an `exp.Identifier` | Rejected | `test_reject_table_valued_functions` |
| DB links (`customers@remote`, `invoices@`) | Table name containing `@` | Never matches the table whitelist, so rejected as `TableNotAllowedError` | `test_reject_dictionary_views_dual_and_db_links` |
| Optimizer hints (`/*+ PARALLEL */`) | `exp.Hint` in `args["hint"]` of each `Select` | Removed from the returned SQL | `test_optimizer_hints_are_stripped` |
| `FETCH ... PERCENT` and `FETCH ... WITH TIES` | `exp.Fetch` in `args["limit"]` with `percent` / `with_ties` | `PERCENT` does not bound the row count, so it is replaced by `FETCH FIRST <max> ROWS ONLY`. `WITH TIES` becomes `ROWS ONLY` with the same count. | `test_percent_fetch_is_replaced_by_an_absolute_cap`, `test_with_ties_is_replaced_by_rows_only` |
| `FETCH` with a count above the cap or not a literal | `exp.Fetch` whose `count` is not an integer literal, or is greater than `max_rows` | The count is set to `max_rows`. A missing `FETCH` gets `FETCH FIRST <max> ROWS ONLY`. A literal at or below the cap is kept. | `test_fetch_first_is_added_when_missing`, `test_literal_fetch_within_the_cap_is_kept`, `test_fetch_above_the_cap_cannot_bypass_it` |
| `CAST(... AS XMLTYPE)` | `exp.DataType` named `XMLTYPE` | Rejected (`DangerousFunctionError`), like the `XMLTYPE()` constructor | `test_reject_sequences_and_information_functions` |
| Event attribute functions without parentheses (`ORA_DATABASE_NAME`, `ORA_LOGIN_USER`, `ORA_INSTANCE_NUM`, `ORA_CLIENT_IP_ADDRESS`) | Unqualified `exp.Column` | Rejected like `USER` / `UID` | `test_reject_sequences_and_information_functions` |
| Row generators (`CONNECT BY LEVEL <= N`) and hierarchical queries | `exp.Connect` | Rejected: no whitelisted table is hierarchical | `test_reject_hierarchical_queries` |
| Bind variables (`:n`) | `exp.Placeholder` (or `exp.Parameter`) | Rejected | `test_reject_bind_variables` |
| Dictionary views (`ALL_*`, `DBA_*`, `V$*`, `GV$*`) | Table names that are not in the whitelist | Rejected by the table whitelist (`TableNotAllowedError`). There is no separate rule for these names. | `test_reject_dictionary_views_dual_and_db_links` |
| `DUAL` | Table name `dual` | Rejected by the whitelist unless it is passed explicitly in `allowed_tables` | `test_reject_dictionary_views_dual_and_db_links`; `test_dual_can_be_allowed_explicitly` |

Other rules apply to both dialects: single statement, root must be `SELECT`/`UNION`, table whitelist, and the `OFFSET` limit (`test_huge_offset_is_rejected`).

## Schema qualifiers (`ALLOWED_SCHEMA`)

In Oracle, `ALLOWED_SCHEMA` must be the **owner of the tables** (the schema that contains them). Qualified names such as `SALES.CUSTOMERS` are accepted only when the schema matches it (`test_oracle_allowed_schema_is_accepted`). Other schemas are rejected (`test_oracle_other_schemas_are_rejected`).

With the default value `public`, no Oracle schema-qualified name matches, so only unqualified table names are accepted (`test_oracle_qualified_names_need_an_explicit_schema`). Set `ALLOWED_SCHEMA` to the owner before you use qualified names.

## Execution

When `TARGET_DIALECT=oracle`, the query is executed against the target Oracle database using the `oracledb` driver in thin mode.

- **Session date formats**: Every new connection sets `NLS_DATE_FORMAT='YYYY-MM-DD'` and `NLS_TIMESTAMP_FORMAT='YYYY-MM-DD HH24:MI:SS.FF'` (`ORACLE_SESSION_FORMATS` in `app/core/db.py`). Without them, the Oracle defaults (`DD-MON-RR`) fail on the SQL the firewall produces: `TIMESTAMP '2026-01-01 00:00:00'` is rewritten by sqlglot as `CAST('2026-01-01 00:00:00' AS TIMESTAMP)`, which raises `ORA-01843`, and a comparison such as `issued_date >= '2026-07-01'` raises `ORA-01861`.
- **Read-only transactions**: Before running the validated `SELECT`, the database connection explicitly runs `SET TRANSACTION READ ONLY` via `conn.exec_driver_sql(...)`. This guarantees that even if a connected account has write privileges, modification statements are rejected by Oracle with `ORA-01456`.
- **Query timeouts via call_timeout**: Controlled via `call_timeout` (in milliseconds) on the DBAPI connection. When a query exceeds `settings.query_timeout_seconds`, Oracle terminates the call with `DPY-4024`, which is caught and mapped to `QueryTimeoutError`. The connection pool recovers cleanly and remains usable.
- **Transitory errors (ORA-01466)**: In Oracle, reading tables in `SET TRANSACTION READ ONLY` that were created or modified seconds earlier may transiently raise `ORA-01466` ("table definition has changed"). `execute_select` automatically retries up to 5 times with `time.sleep(1)` before raising `QueryExecutionError`.
- **Error mapping**: Oracle driver errors are parsed by `map_oracle_error`. Connection failures (`DPY-6xxx`, `DPY-4011`, `ORA-01017`, `ORA-12541`, etc.) map to `DatabaseUnavailableError` (sanitizing hosts, ports, and credentials). Query timeouts (`DPY-4024`) map to `QueryTimeoutError`. `DPY-4011` is the exception: when the call ran for at least `query_timeout_seconds` and a fresh connection still works, `execute_select` reports it as `QueryTimeoutError` (504); otherwise it stays `DatabaseUnavailableError` (503). All other execution failures (`ORA-00942`, `ORA-00904`, etc.) map to `QueryExecutionError`.

## Limitations

The firewall rejects SQL that the parser does not understand (fail-closed). These constructs fail to parse and are therefore rejected (`test_reject_non_select_and_unparseable`):

- `AS OF` (flashback queries)
- `q'[...]'` alternative quoting
- `WITH FUNCTION` (inline PL/SQL functions)
- `LOCK TABLE`
- `VERSIONS BETWEEN` (flashback version queries)
- Substitution variables such as `&1`

Rejecting them is deliberate. A query that does not parse cannot be checked, so it is never executed.

### What the firewall does not stop

These were checked against the integrated code and are **allowed** today. Do not rely on the firewall alone for them:

- **Unqualified user-defined functions** (`SELECT my_func(1) FROM customers`). sqlglot cannot tell them apart from about 25 standard Oracle functions it does not model (`REPLACE`, `INSTR`, `RANK`, `DENSE_RANK`, `MEDIAN`, `REGEXP_*`, `TRANSLATE`...). Both reach the AST as `exp.Anonymous`, so an allowlist would be long and would reject legitimate queries. A PL/SQL function in the connected schema can have side effects (for example `PRAGMA AUTONOMOUS_TRANSACTION`). Run the API with a **read-only account that owns no custom functions or packages and has no `EXECUTE` privileges**.
- **Resource bombs that do not need a banned construct**: recursive CTEs, large Cartesian joins (`FROM customers a, customers b, customers c`). The driver's `call_timeout` ends them, but not always cleanly: with a 2 s timeout a recursive CTE ended after about 4 s with `DPY-4011` (the driver closed the connection; this used to answer 503, "Base de datos no disponible.", and now answers 504 because the database still accepts a new connection); with a 10 s timeout it ended with `DPY-4024` after about 11.5 s.
- **`exp.Parameter` nodes** are rejected next to bind variables, but no test produces one with the Oracle dialect, so that line is not covered by a test.
- Names that sqlglot spells differently from Oracle (for example whether a given built-in is parsed as a typed function or as `Anonymous`) can change between sqlglot versions. The suite pins `sqlglot==25.24.0`.

