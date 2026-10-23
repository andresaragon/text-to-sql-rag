"""Punto de entrada de línea de comandos para scripts.bench_ab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import gen_dataset
from scripts.bench_ab.executors import make_executor
from scripts.bench_ab.llm import GoldGenerator, OllamaGenerator, WrongGenerator, reindex
from scripts.bench_ab.report import render_markdown, results_to_json
from scripts.bench_ab.runner import load_gold, run_benchmark
from scripts.bench_ab.strategies import STRATEGIES


def main() -> None:
    parser = argparse.ArgumentParser(description="Arnés de benchmark A/B")
    parser.add_argument(
        "--llm",
        choices=["ollama", "gold", "wrong"],
        default="ollama",
        help="Generador LLM a utilizar",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["sqlcoder", "qwen2.5-coder:7b"],
        help="Modelos a evaluar",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=list(STRATEGIES),
        help="Estrategias a evaluar o 'all'",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=None,
        help="Ruta al archivo gold.json",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Límite de preguntas a evaluar",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Ruta donde guardar los resultados en JSON",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Ruta donde guardar el informe en Markdown",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="Benchmark A/B",
        help="Título del informe Markdown",
    )

    args = parser.parse_args()

    all_questions = load_gold(args.gold)
    questions = all_questions[: args.limit] if args.limit is not None else all_questions

    if "all" in args.strategies:
        strategies = list(STRATEGIES)
    else:
        strategies = list(args.strategies)
        unknown = [s for s in strategies if s not in STRATEGIES]
        if unknown:
            parser.error(f"estrategias desconocidas: {', '.join(unknown)}")

    if args.llm == "ollama":
        generator = OllamaGenerator()
        prepare = reindex
    elif args.llm == "gold":
        generator = GoldGenerator(all_questions)
        prepare = None
    elif args.llm == "wrong":
        generator = WrongGenerator()
        prepare = None
    else:
        raise ValueError(f"Generador no soportado: {args.llm}")

    executor = make_executor()

    results = run_benchmark(
        questions=questions,
        models=args.models,
        strategies=strategies,
        generate=generator,
        execute=executor,
        prepare=prepare,
    )

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        json_data = results_to_json(results)
        args.out_json.write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    checksums = gen_dataset.checksums(gen_dataset.generate())
    md_report = render_markdown(results, title=args.title, checksums=checksums)

    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md_report, encoding="utf-8")
    else:
        print(md_report)


if __name__ == "__main__":
    main()
