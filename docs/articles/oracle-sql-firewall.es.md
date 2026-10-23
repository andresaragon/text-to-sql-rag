# Qué debe detectar un firewall AST para Oracle (medido, no supuesto)

*[English](oracle-sql-firewall.md)*

Añadí Oracle como base objetivo de [text-to-sql-rag](https://github.com/andresaragon/text-to-sql-rag), un servicio que convierte preguntas en español en SQL, valida ese SQL con un firewall AST y lo ejecuta en solo lectura. El firewall ya funcionaba para Postgres. Para Oracle quería saber tres cosas con números y no con opiniones: qué puede hacer todavía una cuenta de solo lectura, qué debe rechazar el firewall además de eso y cuánto cuesta dejar que el modelo escriba Postgres y transpilar.

Todo lo que sigue se ejecutó contra Oracle Free 23ai (`gvenzl/oracle-free:23.26.3-slim-faststart`), `sqlglot` 25.24.0 y `oracledb` en modo thin.

## 1. Una cuenta de solo lectura no es un sandbox

Creé una cuenta con `CREATE SESSION` y `SELECT` sobre tres tablas, y ejecuté las construcciones peligrosas sin firewall delante.

| Consulta | Resultado |
|---|---|
| `SYS_CONTEXT('USERENV','IP_ADDRESS')` | **ejecuta**, devuelve la dirección del cliente |
| `SYS_CONTEXT(... 'DB_NAME')`, `ORA_DATABASE_NAME`, `USER` | **ejecutan** |
| `DBMS_XMLGEN.GETXML('select username from all_users …')` | **ejecuta el SQL anidado y devuelve datos**, así que esquiva cualquier lista blanca de tablas aplicada a la consulta externa |
| `all_tables`, `all_users` | **legibles** |
| `XMLTYPE('<a/>')`, `FETCH FIRST 10 PERCENT` | ejecutan |
| `UTL_HTTP.REQUEST`, `UTL_INADDR.GET_HOST_NAME` | bloqueadas por la ACL de red (`ORA-24247`); mi servidor no recibió nada |
| `DBMS_LOCK.SLEEP`, `v$session`, funciones de otros esquemas, secuencias | bloqueadas por privilegios |

Yo suponía que `UTL_HTTP` ejecutaría. No fue así: la ACL lo frena. Es una corrección a mis propias notas anteriores y la razón para medir. La lectura honesta es que endurecer la cuenta neutraliza mucho, pero no `SYS_CONTEXT`, `GETXML` ni el diccionario de datos. Eso necesita una segunda capa.

## 2. Lo que añade el firewall

El firewall analiza la consulta con `sqlglot` (`dialect="oracle"`) y recorre el árbol. La tabla completa de amenazas, con la prueba de cada fila, está en [`docs/oracle-firewall.md`](../oracle-firewall.md). Vale la pena contar tres hallazgos.

**Las llamadas calificadas llegan como nodos `Dot`.** `UTL_HTTP.REQUEST(...)` y `DBMS_XMLGEN.GETXML(...)` se parsean como un `Dot` cuyo lado derecho es una función, y el nombre del paquete desaparece de la función. Rechazar toda llamada calificada cierra de golpe toda la familia, incluida `GETXML`.

**Las funciones de paquete sin paréntesis parecen columnas.** En Oracle `UTL_INADDR.GET_HOST_NAME` no necesita paréntesis, así que llega al AST como una columna con calificador. La regla: el calificador de una columna debe ser una tabla o alias declarado en la consulta. Cualquier otro se trata como paquete y se rechaza.

**La primera versión se dejó cosas.** Un ejercicio de equipo rojo antes del PR encontró `CAST(x AS XMLTYPE)`, las pseudocolumnas de eventos (`ORA_DATABASE_NAME` y compañía) y los generadores de filas con `CONNECT BY`. Las tres se rechazan ahora y tienen prueba.

Lo que no detiene también está documentado: las funciones de usuario sin calificar (sqlglot no las distingue de unas 25 funciones estándar de Oracle que no modela) y las bombas de recursos que no necesitan ninguna construcción prohibida. Una CTE recursiva con un `call_timeout` de 2 segundos terminó a los 4 s aproximadamente con `DPY-4011`, que el servicio reporta como 503 y no como 504. Un timeout es una red de seguridad, no una garantía de cuándo se detiene la consulta.

La ejecución añade las capas que un parser no puede dar: `SET TRANSACTION READ ONLY` (un `INSERT` falla con `ORA-01456`), un `call_timeout` en el driver y un reintento para `ORA-01466`, que aparece al leer en una transacción de solo lectura una tabla creada hace unos segundos.

## 3. Dejar que el modelo escriba Postgres y transpilar

Medí tres estrategias con 30 preguntas y datos sintéticos idénticos en ambas bases (300 clientes, 2000 facturas, 1486 pagos, 1117 acciones de cobro): el modelo escribe Postgres y se ejecuta en Postgres; el modelo escribe Oracle y se ejecuta en Oracle; el modelo escribe Postgres, `sqlglot` transpila y se ejecuta en Oracle. Una consulta es correcta si su resultado es igual al de la consulta de referencia en la misma base.

Primero, el propio arnés. Alimentado con el SQL de referencia saca 30/30 en las dos estrategias directas y **27/30 transpilada**: ese es el techo del transpilador en este conjunto de preguntas, con SQL perfecto. Alimentado con `SELECT 1` saca cero. Las tres pérdidas:

- `DATE_TRUNC` pasa a `TIMESTAMP_TRUNC`, que Oracle no tiene (`ORA-00904`). Falla con ruido.
- `STRING_AGG` pasa a `GROUP_CONCAT` (`ORA-00904`). También con ruido.
- `CAST(x AS DATE)` se ejecuta, conserva la hora del día y devuelve un **número equivocado sin ningún error**. Esta es la razón para medir en vez de confiar en el transpilador.

Luego dos modelos locales, temperatura 0, una corrida cada uno:

| Modelo | Postgres directo | Oracle directo | Postgres transpilado |
|---|---|---|---|
| qwen2.5-coder:7b | 22/30 | 21/30 | 19/30 |
| sqlcoder | 8/30 | 8/30 | 7/30 |

El modelo pesa mucho más que el dialecto. Postgres directo y Oracle directo no se distinguen con esta muestra (los intervalos de Wilson al 95 % de 22/30 y 21/30 se solapan casi por completo). Transpilar le costó tres preguntas al modelo más fuerte y no le dio ninguna, todas de fechas, lo que coincide con el mecanismo de arriba. Tres preguntas están dentro del ruido con n = 30; el mecanismo no.

## Qué afirmaría y qué no

Afirmaría los mecanismos: qué construcciones ejecuta todavía una cuenta de solo lectura en Oracle, por qué las llamadas calificadas y los calificadores no declarados son lo correcto que rechazar, y que el transpilador tiene un techo medido con un fallo silencioso.

No afirmaría un ranking. n = 30, las preguntas y el SQL de referencia los escribí yo (con trampas de dialecto a propósito), cada celda es una sola corrida, el esquema tiene cuatro tablas y los modelos son dos locales pequeños. El informe completo, con la taxonomía de errores y los resultados crudos, está en [`docs/benchmarks/2026-10-23-ab.es.md`](../benchmarks/2026-10-23-ab.es.md), y `python -m scripts.bench_ab` lo reproduce.
