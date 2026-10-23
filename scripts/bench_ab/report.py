"""Generación de informes y exportación de resultados para el benchmark A/B."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from scripts.bench_ab.runner import Result
from scripts.bench_ab.scoring import wilson_interval


def summarize(results: Sequence[Result]) -> dict[tuple[str, str], dict[str, Any]]:
    """Calcula métricas agregadas por (modelo, estrategia)."""
    groups: dict[tuple[str, str], list[Result]] = {}
    for r in results:
        groups.setdefault((r.model, r.strategy), []).append(r)

    summary: dict[tuple[str, str], dict[str, Any]] = {}
    for key, items in groups.items():
        n = len(items)
        strict = sum(1 for r in items if r.evaluation.strict)
        relaxed = sum(1 for r in items if r.evaluation.relaxed)
        executable = sum(1 for r in items if r.evaluation.status in ("correct", "wrong"))
        firewall_rejected = sum(1 for r in items if r.evaluation.status == "firewall_rejected")
        execution_error = sum(1 for r in items if r.evaluation.status == "execution_error")
        generation_error = sum(1 for r in items if r.evaluation.status == "generation_error")

        error_codes = Counter(
            r.evaluation.error_code for r in items if r.evaluation.error_code is not None
        )

        strict_ci = wilson_interval(strict, n)
        relaxed_ci = wilson_interval(relaxed, n)

        summary[key] = {
            "n": n,
            "strict": strict,
            "relaxed": relaxed,
            "executable": executable,
            "firewall_rejected": firewall_rejected,
            "execution_error": execution_error,
            "generation_error": generation_error,
            "error_codes": dict(error_codes),
            "strict_ci": strict_ci,
            "relaxed_ci": relaxed_ci,
        }

    return summary


def results_to_json(results: Sequence[Result]) -> list[dict[str, Any]]:
    """Convierte la lista de resultados en objetos serializables en JSON."""
    return [
        {
            "model": r.model,
            "strategy": r.strategy,
            "question_id": r.question_id,
            "category": r.category,
            "difficulty": r.difficulty,
            "original_question": r.original_question,
            "status": r.evaluation.status,
            "strict": r.evaluation.strict,
            "relaxed": r.evaluation.relaxed,
            "raw_sql": r.raw_sql,
            "final_sql": r.evaluation.final_sql,
            "error": r.evaluation.error,
            "error_code": r.evaluation.error_code,
            "timings_ms": r.timings_ms,
        }
        for r in results
    ]


def render_markdown(
    results: Sequence[Result],
    *,
    title: str = "Benchmark A/B",
    checksums: dict[str, str] | None = None,
) -> str:
    """Genera un informe completo en Markdown a partir de los resultados."""
    summary = summarize(results)
    lines: list[str] = [f"# {title}", ""]

    # Sección 1: Resumen por modelo y estrategia
    lines.append("## Resumen por modelo y estrategia")
    lines.append("")
    lines.append(
        "| Modelo | Estrategia | Exactitud estricta (k/n) | IC 95 % estricto | "
        "Exactitud relajada (k/n) | IC 95 % relajado | Ejecutables | Rechazadas cortafuegos | "
        "Error ejecución | Error generación |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    for (model, strategy), s in summary.items():
        s_ci = f"[{s['strict_ci'][0]:.3f}, {s['strict_ci'][1]:.3f}]"
        r_ci = f"[{s['relaxed_ci'][0]:.3f}, {s['relaxed_ci'][1]:.3f}]"
        lines.append(
            f"| {model} | {strategy} | {s['strict']}/{s['n']} | {s_ci} | "
            f"{s['relaxed']}/{s['n']} | {r_ci} | {s['executable']} | "
            f"{s['firewall_rejected']} | {s['execution_error']} | {s['generation_error']} |"
        )
    lines.append("")

    # Sección 2: Por categoría
    lines.append("## Por categoría")
    lines.append("")
    categories = sorted({r.category for r in results})
    lines.append("| Categoría | Modelo | Estrategia | Estricta (k/n) | Relajada (k/n) |")
    lines.append("|---|---|---|---|---|")
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        cat_summary = summarize(cat_results)
        for (model, strategy), cs in cat_summary.items():
            lines.append(
                f"| {cat} | {model} | {strategy} | {cs['strict']}/{cs['n']} | {cs['relaxed']}/{cs['n']} |"
            )
    lines.append("")

    # Sección 3: Preguntas originales
    lines.append("## Preguntas originales")
    lines.append("")
    orig_results = [r for r in results if r.original_question is not None]
    if orig_results:
        lines.append("| Original # | ID | Modelo | Estrategia | Estado | Estricta | Relajada |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in orig_results:
            lines.append(
                f"| {r.original_question} | {r.question_id} | {r.model} | {r.strategy} | "
                f"{r.evaluation.status} | {r.evaluation.strict} | {r.evaluation.relaxed} |"
            )
    else:
        lines.append("No se evaluaron preguntas correspondientes a las originales.")
    lines.append("")

    # Sección 4: Taxonomía de errores
    lines.append("## Taxonomía de errores")
    lines.append("")
    error_counter: Counter[str] = Counter()
    for s in summary.values():
        error_counter.update(s["error_codes"])

    if error_counter:
        lines.append("| Código de error | Ocurrencias |")
        lines.append("|---|---|")
        for code, count in error_counter.most_common():
            lines.append(f"| {code} | {count} |")
    else:
        lines.append("No se registraron errores de ejecución clasificados con código.")
    lines.append("")

    # Sección 5: Datos
    if checksums is not None:
        lines.append("## Datos")
        lines.append("")
        lines.append("Sumas de control SHA-256 del dataset sintético determinista:")
        for table, chk in checksums.items():
            lines.append(f"- {table}: {chk}")
        lines.append("")

    # Sección 6: Limitaciones
    lines.append("## Limitaciones")
    lines.append("")
    lines.append(
        "- El tamaño de muestra es de n = 30 preguntas, por lo que diferencias "
        "menores de unos 15 puntos porcentuales no son concluyentes al 95 % de confianza."
    )
    lines.append(
        "- Las 30 preguntas y su SQL de referencia las redactó el autor del proyecto."
    )
    lines.append("")

    return "\n".join(lines)
