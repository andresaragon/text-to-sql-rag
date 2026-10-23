# What an AST firewall for Oracle has to catch (measured, not assumed)

*[Español](oracle-sql-firewall.es.md)*

I added Oracle as a target database to [text-to-sql-rag](https://github.com/andresaragon/text-to-sql-rag), a service that turns Spanish questions into SQL, validates the SQL with an AST firewall, and runs it read-only. The firewall already worked for Postgres. For Oracle I wanted to know three things with numbers instead of opinions: what a read-only account can still do, what the firewall must reject on top of that, and what it costs to let the model write Postgres and transpile it.

Everything below was run against Oracle Free 23ai (`gvenzl/oracle-free:23.26.3-slim-faststart`), `sqlglot` 25.24.0 and `oracledb` in thin mode.

## 1. A read-only account is not a sandbox

I created an account with `CREATE SESSION` and `SELECT` on three tables, and ran the dangerous constructs with no firewall in front.

| Query | Result |
|---|---|
| `SYS_CONTEXT('USERENV','IP_ADDRESS')` | **runs**, returns the client address |
| `SYS_CONTEXT(... 'DB_NAME')`, `ORA_DATABASE_NAME`, `USER` | **run** |
| `DBMS_XMLGEN.GETXML('select username from all_users …')` | **runs the nested SQL and returns data**, so it sidesteps any table whitelist applied to the outer query |
| `all_tables`, `all_users` | **readable** |
| `XMLTYPE('<a/>')`, `FETCH FIRST 10 PERCENT` | run |
| `UTL_HTTP.REQUEST`, `UTL_INADDR.GET_HOST_NAME` | blocked by the network ACL (`ORA-24247`); my listener received nothing |
| `DBMS_LOCK.SLEEP`, `v$session`, other schemas' functions, sequences | blocked by privileges |

I had assumed `UTL_HTTP` would execute. It did not: the ACL stops it. That is a correction to my own earlier notes, and the reason to measure. The honest reading is that hardening the account neutralizes a lot, but not `SYS_CONTEXT`, `GETXML` or the data dictionary. Those need a second layer.

## 2. What the firewall adds

The firewall parses the query with `sqlglot` (`dialect="oracle"`) and walks the tree. The full threat table, with the test for each row, is in [`docs/oracle-firewall.md`](../oracle-firewall.md). Three findings are worth telling.

**Qualified calls arrive as `Dot` nodes.** `UTL_HTTP.REQUEST(...)` and `DBMS_XMLGEN.GETXML(...)` parse as a `Dot` whose right side is a function, and the package name disappears from the function. Rejecting every qualified call closes the whole family at once, including `GETXML`.

**Package functions without parentheses look like columns.** `UTL_INADDR.GET_HOST_NAME` in Oracle needs no parentheses, so it reaches the AST as a column with a qualifier. The rule: a column qualifier must be a table or alias declared in the query. Anything else is treated as a package and rejected.

**The first version missed things.** A red-team pass before the PR found `CAST(x AS XMLTYPE)`, the event pseudocolumns (`ORA_DATABASE_NAME` and friends) and `CONNECT BY` row generators. All three are now rejected and tested.

What it does not stop is documented too: unqualified user-defined functions (sqlglot cannot tell them from the roughly 25 standard Oracle functions it does not model), and resource bombs that need no banned construct. A recursive CTE under a 2-second `call_timeout` ended after about 4 seconds with `DPY-4011`, which the service reports as 503 rather than 504. A timeout is a safety net, not a guarantee of when the query stops.

Execution adds the layers a parser cannot: `SET TRANSACTION READ ONLY` (an `INSERT` fails with `ORA-01456`), a driver-level `call_timeout`, and a retry for `ORA-01466`, which appears when a table created seconds earlier is read in a read-only transaction.

## 3. Letting the model write Postgres and transpiling it

I measured three strategies on 30 questions with identical synthetic data in both databases (300 customers, 2000 invoices, 1486 payments, 1117 collection actions): the model writes Postgres and it runs on Postgres; the model writes Oracle and it runs on Oracle; the model writes Postgres, `sqlglot` transpiles, and it runs on Oracle. A query is correct if its result equals the reference query's result on the same database.

First, the harness itself. Fed the reference SQL it scores 30/30 on both direct strategies and **27/30 transpiled**: that is the ceiling of the transpiler on this question set, with perfect SQL. Fed `SELECT 1` it scores zero. The three losses:

- `DATE_TRUNC` becomes `TIMESTAMP_TRUNC`, which Oracle does not have (`ORA-00904`). It fails loudly.
- `STRING_AGG` becomes `GROUP_CONCAT` (`ORA-00904`). Also loud.
- `CAST(x AS DATE)` runs, keeps the time of day, and returns a **wrong number with no error**. This one is the reason to measure instead of trusting the transpiler.

Then two local models, temperature 0, one run each:

| Model | Postgres direct | Oracle direct | Postgres transpiled |
|---|---|---|---|
| qwen2.5-coder:7b | 22/30 | 21/30 | 19/30 |
| sqlcoder | 8/30 | 8/30 | 7/30 |

The model matters far more than the dialect. Postgres direct and Oracle direct cannot be told apart at this sample size (the 95 % Wilson intervals for 22/30 and 21/30 overlap almost entirely). Transpiling cost the stronger model three questions and gained none, all of them date questions, which matches the mechanism above. Three questions is within noise for n = 30; the mechanism is not.

## What I would and would not claim

I would claim the mechanisms: which constructs a read-only Oracle account still executes, why qualified calls and undeclared qualifiers are the right things to reject, and that the transpiler has a measured ceiling with one silent failure.

I would not claim a ranking. n = 30, I wrote the questions and the reference SQL (with dialect traps on purpose), each cell is a single run, the schema has four tables, and the models are two small local ones. The full report, with the error taxonomy and the raw results, is in [`docs/benchmarks/2026-10-23-ab.md`](../benchmarks/2026-10-23-ab.md), and `python -m scripts.bench_ab` reproduces it.
