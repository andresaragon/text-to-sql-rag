"""
Benchmark de POST /query contra un servidor ya levantado (con Postgres,
pgvector y Ollama reales). Complementa scripts/load_test.py (Locust): este
mide latencia por pregunta y por etapa; Locust mide throughput bajo carga.

Qué mide, en este orden (el orden importa por el cache en memoria):
  1. primer request tras arrancar el server (incluye cargas perezosas,
     como el modelo de embeddings si no hubo warm-up),
  2. cada pregunta de dominio en frío (cache miss),
  3. las mismas preguntas otra vez (cache hit de retrieval + LLM),
  4. preguntas fuera del dominio.

Si la respuesta trae el header Server-Timing, se desglosa por etapa.

Uso (desde la raíz del repo, con el server en marcha):

    python -m scripts.bench_query --host http://localhost:8000 --out bench.json
"""

import argparse
import json
import re
import statistics
import time

import httpx

from scripts.questions import QUESTIONS

OFF_DOMAIN_QUESTIONS = [
    "¿Cuál es la capital de Francia?",
    "Escribe un poema sobre el mar",
    "¿Quién ganó el mundial de fútbol de 2014?",
]

_TIMING_RE = re.compile(r"(\w+);dur=([\d.]+)")


def _ask(client: httpx.Client, question: str) -> dict:
    t0 = time.perf_counter()
    res = client.post("/query", json={"question": question})
    total_ms = (time.perf_counter() - t0) * 1000
    body = res.json() if res.headers.get("content-type", "").startswith(
        "application/json"
    ) else {}
    return {
        "question": question,
        "status": res.status_code,
        "total_ms": round(total_ms, 1),
        "stages_ms": {
            name: float(dur)
            for name, dur in _TIMING_RE.findall(res.headers.get("server-timing", ""))
        },
        "sql": body.get("sql"),
        "row_count": body.get("row_count"),
        "detail": body.get("detail"),
    }


def _summary(results: list[dict]) -> dict:
    times = [r["total_ms"] for r in results]
    statuses: dict[str, int] = {}
    for r in results:
        statuses[str(r["status"])] = statuses.get(str(r["status"]), 0) + 1
    return {
        "n": len(times),
        "p50_ms": round(statistics.median(times), 1),
        "max_ms": round(max(times), 1),
        "mean_ms": round(statistics.mean(times), 1),
        "statuses": statuses,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--out", help="archivo JSON con el detalle")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    with httpx.Client(base_url=args.host, timeout=args.timeout) as client:
        first = _ask(client, QUESTIONS[0])
        cold = [first] + [_ask(client, q) for q in QUESTIONS[1:]]
        cached = [_ask(client, q) for q in QUESTIONS]
        off_domain = [_ask(client, q) for q in OFF_DOMAIN_QUESTIONS]

    report = {
        "host": args.host,
        "first_request_ms": first["total_ms"],
        "cold": _summary(cold[1:]),
        "cached": _summary(cached),
        "off_domain": _summary(off_domain),
        "detail": {"cold": cold, "cached": cached, "off_domain": off_domain},
    }
    print(json.dumps({k: v for k, v in report.items() if k != "detail"}, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
