"""Scoring y normalización para el benchmark A/B."""

from __future__ import annotations

import datetime as dt
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Comparison:
    strict: bool
    relaxed: bool


def normalize_value(v: Any) -> Any:
    """Normaliza un valor escalar para comparación entre Postgres y Oracle."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        return round(float(v), 2)
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) else v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def normalize_rows(rows: Sequence[Any]) -> list[tuple[Any, ...]]:
    """Convierte cada fila (dict, tupla o lista) en tupla normalizada."""
    result = []
    for r in rows:
        values = r.values() if isinstance(r, dict) else r
        result.append(tuple(normalize_value(v) for v in values))
    return result


def compare(gold_rows: Sequence[Any], got_rows: Sequence[Any], ordered: bool) -> Comparison:
    """
    Compara filas de referencia (gold) contra filas obtenidas (got).
    Calcula igualdad estricta e igualdad relajada (proyección/permutación de columnas).
    """
    gold_norm = normalize_rows(gold_rows)
    got_norm = normalize_rows(got_rows)

    if len(gold_norm) != len(got_norm):
        return Comparison(strict=False, relaxed=False)

    if len(gold_norm) == 0:
        return Comparison(strict=True, relaxed=True)

    if ordered:
        strict = (gold_norm == got_norm)
    else:
        strict = (sorted(map(repr, gold_norm)) == sorted(map(repr, got_norm)))

    if strict:
        return Comparison(strict=True, relaxed=True)

    c_gold = len(gold_norm[0])
    c_got = len(got_norm[0])

    if c_got < c_gold:
        return Comparison(strict=False, relaxed=False)

    if any(len(r) != c_gold for r in gold_norm) or any(len(r) != c_got for r in got_norm):
        return Comparison(strict=False, relaxed=False)

    gold_target = gold_norm if ordered else sorted(map(repr, gold_norm))

    relaxed = False
    for perm in itertools.permutations(range(c_got), c_gold):
        projected = [tuple(row[i] for i in perm) for row in got_norm]
        if ordered:
            if projected == gold_target:
                relaxed = True
                break
        else:
            if sorted(map(repr, projected)) == gold_target:
                relaxed = True
                break

    return Comparison(strict=False, relaxed=relaxed)


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Calcula el intervalo de confianza de Wilson para una proporción."""
    if total == 0:
        return (0.0, 0.0)

    p_hat = successes / total
    denom = 1.0 + (z * z) / total
    center = (p_hat + (z * z) / (2.0 * total)) / denom
    margin = (z * math.sqrt((p_hat * (1.0 - p_hat)) / total + (z * z) / (4.0 * total * total))) / denom

    low = center - margin
    high = center + margin

    low = max(0.0, min(1.0, low))
    high = max(0.0, min(1.0, high))

    if successes == 0:
        low = 0.0
    if successes == total:
        high = 1.0

    return (low, high)
