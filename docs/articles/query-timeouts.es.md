# Un timeout es una red de seguridad, no una garantía (medido en Postgres y Oracle)

*[English](query-timeouts.md)*

[text-to-sql-rag](https://github.com/andresaragon/text-to-sql-rag) ejecuta SQL que escribió un modelo de lenguaje, así que «¿qué pasa si la base está caída, o la consulta no termina nunca?» no es un caso raro. Lo medí en vez de leer la documentación del driver y confiar en ella. Dos cosas que daba por ciertas eran falsas, y una que no pude reproducir queda documentada como tal.

Todo corrió en un portátil con WSL2 (RTX 4060, Docker), Postgres 16 con pgvector, Oracle Free 23ai (`gvenzl/oracle-free:23.26.3-slim-faststart`) y `oracledb` en modo thin. Las corridas de Oracle se reproducen con `python -m scripts.bench_timeouts` y están guardadas en [`docs/benchmarks/2026-10-24/timeouts.json`](../benchmarks/2026-10-24/timeouts.json).

## 1. La base es inalcanzable

El 2026-10-15 apunté el servicio a una IP que no responde (`10.255.255.1`) y mandé un `POST /query`:

| | Respuesta | Tiempo |
|---|---|---|
| Antes del arreglo | HTTP 500 | **138,5 s** |
| Después (`connect_timeout`, error mapeado a 503) | HTTP 503 | **4,0 s** |

Los 138 segundos son el timeout de conexión TCP del sistema operativo: ningún ajuste de la aplicación intervenía, así que nada lo detenía. El arreglo es un timeout de conexión más un mapeo del error del driver a «base no disponible», que es la respuesta honesta (503) y no un fallo del servidor (500).

El 2026-10-24 lo repetí contra Oracle: **3,04 a 3,06 s**, `DatabaseUnavailableError`, con `tcp_connect_timeout=3`. También le pregunté directamente al driver de Oracle qué hace sin ese ajuste, contra un puerto que descarta paquetes: esperó **20,0 s** antes de fallar con `DPY-6005`. Un valor por defecto tan largo es demasiado para una API de petición y respuesta.

Un detalle de mi entorno, no del servicio: un puerto cerrado en `127.0.0.1` no rechazó la conexión, también agotó el tiempo (la prueba con un socket tardó 5 s y lanzó `TimeoutError`). En WSL2 con Docker, los paquetes a un puerto sin nadie escuchando pueden descartarse en vez de rechazarse. Si pruebas «conexión rechazada» en un montaje así, comprueba que no estés probando «inalcanzable».

## 2. La consulta no termina

El cortafuegos deja pasar una CTE recursiva, porque no usa ninguna construcción prohibida. Con un timeout configurado de 2 s y de 10 s corrí tres formas por todo el pipeline (cortafuegos y luego `execute_select`):

| Consulta | Timeout 2 s | Timeout 10 s |
|---|---|---|
| CTE recursiva, `ORDER BY n DESC` | 2,06 s, `QueryTimeoutError` (504) | 10,21 s, `QueryTimeoutError` |
| CTE recursiva, `COUNT(*)` | 2,06 s, `QueryTimeoutError` | 10,08 s, `QueryTimeoutError` |
| CTE recursiva, `SELECT n` simple | 0,03 s, 100 filas | 0,03 s, 100 filas |

La tercera fila no es el timeout funcionando: el cortafuegos añade `FETCH FIRST 100 ROWS ONLY`, y los 0,03 s muestran que Oracle deja de generar filas al llegar a 100. Las dos primeras tienen que materializar o agregar todo, así que ningún tope de filas ayuda y solo las detiene el timeout.

En todas mis corridas por el pipeline, el corte con un timeout de 2 s cayó entre 2,02 y 2,07 s. Con 10 s cayó entre **10,05 y 11,73 s** (ocho observaciones: 10,05, 10,08, 10,09, 10,14, 10,21, 10,24, 11,07 y 11,73). El timeout es lo más pronto que se puede cortar la llamada, no cuándo se corta. Un cliente que ponga su propio plazo con ese mismo valor se rendirá antes.

## 3. El hallazgo que fue un error mío

Mi primera medición llamó a `execute_select` directamente con la misma CTE que devuelve filas. Con un timeout de 2 s tardó **19,8 s** y terminó con `ORA-01013` (la llamada fue cancelada), que el servicio mapeaba a «no se pudo ejecutar» (400) en vez de «demasiado lenta» (504). Con 10 s seguía ejecutándose después de más de siete minutos y la maté.

Parecía que «el timeout no funciona». No era así: en el pipeline la misma consulta termina en 0,03 s por el tope de filas. Pero el mecanismo es real y conviene conocerlo: el `call_timeout` del driver se aplica a **cada viaje de ida y vuelta** a la base, no a la sentencia. Una sentencia que entrega filas tan rápido que cada lectura termina dentro del timeout nunca se corta, por larga que sea la secuencia completa. En este servicio lo que acota es el tope de filas, no el timeout, así que quien reutilice `execute_select` fuera del cortafuegos hereda una llamada sin límite. El servicio ahora mapea también `ORA-01013` a 504, porque lo único que cancela llamadas aquí es el timeout, y la documentación lo dice.

## 4. El código de error que significa dos cosas

`DPY-4011` («la conexión se cerró») es lo que lanzó el driver de Oracle en una corrida anterior cuando una CTE recursiva sobrepasó un timeout de 2 s, y también es el aspecto de una caída real. El servicio respondía 503 en ambos casos. Decirle al usuario «base no disponible» cuando la causa real era «tu consulta era demasiado pesada» lo manda al sitio equivocado.

La regla que implementé: reportar `DPY-4011` como timeout solo si la llamada duró al menos el timeout configurado **y** una conexión nueva a la base todavía funciona. Si no, sigue siendo 503.

No pude reproducir `DPY-4011` el 2026-10-24 en ninguna de las corridas de arriba, así que esa rama está cubierta por pruebas con errores simulados y no por un fallo real. Queda documentado exactamente así. El punto ciego que queda es estrecho: una base que se cae justo después del timeout y vuelve a responder antes de la sonda se reportaría como timeout.

## Qué afirmaría y qué no

Afirmaría: el valor por defecto del sistema operativo para un host inalcanzable son minutos, el del driver son 20 s, y ambos son demasiado largos para una API, así que el timeout de conexión hay que fijarlo explícitamente; un timeout acota lo más pronto que se corta y no lo más tarde; y `call_timeout` no acota una sentencia que entrega filas, así que el tope de filas es parte del diseño del timeout.

No afirmaría cifras fuera de esta máquina. Cada celda es una sola corrida, el conjunto de datos tiene tres clientes (la recursión no depende de los datos, pero el sobrepaso sí podría depender de la carga), es WSL2 y no un servidor, y no volví a medir la ruta `statement_timeout` de Postgres el 2026-10-24. Las cifras de Postgres de la sección 1 vienen de la corrida documentada en [`docs/benchmarks/2026-10-15.md`](../benchmarks/2026-10-15.md).
