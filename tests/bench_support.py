"""Apoyo de las pruebas del benchmark: normalización de referencia (independiente de scripts.bench_ab)."""

import datetime as dt
from decimal import Decimal


def norm(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return round(float(value), 2)
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time(0) else value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def normalize(rows):
    return [tuple(norm(v) for v in (r.values() if isinstance(r, dict) else r)) for r in rows]


def same(a, b, ordered):
    a, b = normalize(a), normalize(b)
    return a == b if ordered else sorted(map(repr, a)) == sorted(map(repr, b))
