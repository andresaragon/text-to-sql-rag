"""
Script de indexado: lee data/schema_docs/*.md, parte el contenido en
fragmentos (por tabla / por ejemplo), genera embeddings para cada uno,
y los guarda en la tabla schema_embeddings.

Granularidad actual: solo "table" y "example_query" (sin fragmentos por
columna — el esquema es chico y las columnas ya están descritas en prosa
dentro de cada fragmento de tabla; queda como mejora futura documentada).

Uso previsto:
    python scripts/index_schema.py
"""

import re
from pathlib import Path

from app.core.embeddings import embed_batch
from app.core.db import execute_select, save_schema_embedding

SCHEMA_DOCS_DIR = Path(__file__).parent.parent / "data" / "schema_docs"

_TABLE_HEADING_PREFIX = "Tabla: "
_EXAMPLES_HEADING_PREFIX = "Ejemplo de pregunta"


def load_schema_fragments() -> list[dict]:
    """
    Lee data/schema_docs/tables.md y lo parte en fragmentos indexables.

    Cada heading "## Tabla: X" es un fragmento (object_type "table"). El
    heading de ejemplos few-shot se sub-parte por cada "Pregunta:" en
    fragmentos individuales (object_type "example_query").
    """
    text = (SCHEMA_DOCS_DIR / "tables.md").read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)[1:]  # descarta el título "# ..." inicial

    fragments = []
    for section in sections:
        heading, _, body = section.partition("\n")
        heading = heading.strip()
        body = body.strip()

        if heading.startswith(_TABLE_HEADING_PREFIX):
            fragments.append(
                {
                    "object_name": heading[len(_TABLE_HEADING_PREFIX):].strip(),
                    "object_type": "table",
                    "description": body,
                }
            )
        elif heading.startswith(_EXAMPLES_HEADING_PREFIX):
            fragments.extend(_split_examples(body))
        else:
            raise ValueError(f"Heading no reconocido en tables.md: {heading!r}")

    return fragments


def _split_examples(body: str) -> list[dict]:
    """Parte el bloque de ejemplos few-shot en un fragmento por cada 'Pregunta: ... SQL: ...'."""
    raw_examples = re.split(r"(?m)^Pregunta:", body)[1:]
    return [
        {
            "object_name": f"example_{i}",
            "object_type": "example_query",
            "description": f"Pregunta: {raw.strip()}",
        }
        for i, raw in enumerate(raw_examples, start=1)
    ]


def main():
    fragments = load_schema_fragments()
    descriptions = [f["description"] for f in fragments]
    embeddings = embed_batch(descriptions)

    deleted = execute_select("DELETE FROM schema_embeddings RETURNING id")
    print(f"Borrados {len(deleted)} fragmentos previos de schema_embeddings.")

    for fragment, embedding in zip(fragments, embeddings):
        save_schema_embedding(
            object_name=fragment["object_name"],
            object_type=fragment["object_type"],
            description=fragment["description"],
            embedding=embedding,
        )

    print(f"Indexados {len(fragments)} fragmentos de esquema.")


if __name__ == "__main__":
    main()
