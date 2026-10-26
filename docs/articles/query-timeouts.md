# A timeout is a safety net, not a guarantee (measured on Postgres and Oracle)

*[Español](query-timeouts.es.md)*

[text-to-sql-rag](https://github.com/andresaragon/text-to-sql-rag) runs SQL that a language model wrote, so "what happens when the database is down, or the query never ends?" is not an edge case. I measured it instead of taking the defaults on trust. Two things I assumed were wrong, and one thing I could not reproduce is documented as such.

Everything below ran on a laptop under WSL2 (RTX 4060, Docker), Postgres 16 with pgvector, Oracle Free 23ai (`gvenzl/oracle-free:23.26.3-slim-faststart`), `oracledb` in thin mode. The Oracle runs are reproducible with `python -m scripts.bench_timeouts` and are saved in [`docs/benchmarks/2026-10-24/timeouts.json`](../benchmarks/2026-10-24/timeouts.json).

## 1. The database is unreachable

On 2026-10-15 I pointed the service, running on Postgres, at an IP that does not answer (`10.255.255.1`) and sent one `POST /query`:

| | Response | Time |
|---|---|---|
| Before the fix | HTTP 500 | **138.5 s** |
| After (`connect_timeout`, error mapped to 503) | HTTP 503 | **4.0 s** |

The 138 seconds are the operating system's TCP connect timeout: no application setting was involved, so nothing stopped it. The fix is a connect timeout plus a mapping from the driver error to "database unavailable", which is the honest answer (503), not a server bug (500).

On 2026-10-24 I repeated it against Oracle: **3.04–3.06 s**, `DatabaseUnavailableError`, with `tcp_connect_timeout=3`. I also asked the Oracle driver directly what it does without that setting, against a port that drops packets: it waited **20.0 s** before failing with `DPY-6005`. A default that long is far too much for a request/response API.

One detail that is about my environment, not the service: a closed port on `127.0.0.1` did not refuse the connection, it timed out as well (the socket test took 5 s and raised `TimeoutError`). Under WSL2 plus Docker, packets to a port nobody listens on can be dropped instead of rejected. If you test "connection refused" on such a setup, check that you are not testing "unreachable".

## 2. The query never ends

The firewall lets a recursive CTE through, because it uses no banned construct. Under a configured timeout of 2 s and of 10 s I ran three shapes through the whole pipeline (firewall, then `execute_select`):

| Query | Timeout 2 s | Timeout 10 s |
|---|---|---|
| Recursive CTE, `ORDER BY n DESC` | 2.06 s, `QueryTimeoutError` (504) | 10.21 s, `QueryTimeoutError` |
| Recursive CTE, `COUNT(*)` | 2.06 s, `QueryTimeoutError` | 10.08 s, `QueryTimeoutError` |
| Recursive CTE, plain `SELECT n` | 0.04 s, 100 rows | 0.04 s, 100 rows |

The third row is not the timeout working: the firewall appends `FETCH FIRST 100 ROWS ONLY`, and the 0.04 s is consistent with Oracle stopping once it has 100 rows. The first two have to materialize or aggregate everything, so no row cap helps, and only the timeout stops them.

Across all my runs with the pipeline, the cut for a 2 s timeout landed between 2.02 and 2.07 s. For a 10 s timeout it landed between **10.05 and 11.73 s** (eight observations: 10.05, 10.08, 10.09, 10.14, 10.21, 10.24, 11.07, 11.73). The saved `timeouts.json` holds one run of these; the rest come from earlier runs that are not in the repository. The timeout is the earliest the call can be cut, not the time it will be cut. A client that sets its own deadline at the same value will give up first.

## 3. The finding that was my own mistake

My first measurement called `execute_select` directly with the same CTE returning rows. With a 2 s timeout it ran **19.8 s** and ended with `ORA-01013` (the call was cancelled), which the service mapped to "could not execute" (400) rather than "too slow" (504). With a 10 s timeout it was still running after more than seven minutes and I killed it.

That looked like "the timeout does not work". It was not: in the pipeline the same query ends in 0.04 s because of the row cap. But the mechanism is real, and it is worth knowing: the driver's `call_timeout` applies to **each round trip** to the database, not to the statement. A statement that streams rows fast enough that every fetch finishes inside the timeout is never cut, however long the whole stream takes. In this service the row cap is what bounds it, not the timeout, so anyone who reuses `execute_select` outside the firewall inherits an unbounded call. The service now maps `ORA-01013` to 504 as well, since the only thing configured to cancel calls here is the timeout, and the documentation says so.

## 4. The error code that means two things

`DPY-4011` ("the connection was closed") is what the Oracle driver raised in an earlier run when a recursive CTE overran a 2 s timeout, and it is also what a real outage looks like. The service answered 503 for both. Telling a user "database unavailable" when the real cause was "your query was too heavy" sends them to the wrong place.

The rule I implemented: report `DPY-4011` as a timeout only when the call ran at least as long as the configured timeout **and** a fresh connection to the database still works. Otherwise it stays a 503.

I could not reproduce `DPY-4011` on 2026-10-24 in any of the runs above, so that branch is covered by tests with simulated errors and not by a real failure. It is documented as exactly that. The remaining blind spot is narrow: a database that dies just after the timeout and answers again before the probe would be reported as a timeout.

## What I would and would not claim

I would claim: the OS default for an unreachable host is minutes, the driver default is 20 s, and both are too long for an API, so the connect timeout must be set explicitly; a timeout bounds the earliest cut and not the latest; and `call_timeout` does not bound a statement that streams, so a row cap is part of the timeout design.

I would not claim numbers beyond this machine. Each cell is a single run, the dataset has three customers (the recursion does not depend on the data, but the overshoot may depend on load), it is WSL2 rather than a server, and I did not re-measure the Postgres `statement_timeout` path on 2026-10-24. The Postgres figures in section 1 come from the run documented in [`docs/benchmarks/2026-10-15.md`](../benchmarks/2026-10-15.md).
