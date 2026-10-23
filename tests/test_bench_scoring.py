"""Scoring del benchmark A/B (SPEC.md, CA3). Escritas antes de implementar; no se editan."""

import datetime as dt
import importlib
from decimal import Decimal

import pytest

from tests.bench_support import norm


def scoring():
    return importlib.import_module("scripts.bench_ab.scoring")


VALUES = [
    (Decimal("12.30"), 12.3),
    (Decimal("3.333333"), 3.33),
    (7, 7.0),
    (1.0, 1.0),
    ("x", "x"),
    (None, None),
    (True, True),
    (dt.date(2026, 1, 1), "2026-01-01"),
    (dt.datetime(2026, 1, 1), "2026-01-01"),
    (dt.datetime(2026, 8, 10, 10, 15), "2026-08-10 10:15:00"),
]


@pytest.mark.parametrize(("raw", "expected"), VALUES)
def test_normalize_value(raw, expected):
    got = scoring().normalize_value(raw)
    assert got == expected
    assert type(got) is type(expected)


def test_normalize_value_agrees_with_the_reference_helper():
    for raw, _ in VALUES:
        assert scoring().normalize_value(raw) == norm(raw)


def test_normalize_rows_turns_dicts_and_sequences_into_tuples():
    assert scoring().normalize_rows([{"n": Decimal(3)}, (4,), [5]]) == [(3.0,), (4.0,), (5.0,)]


CASES = [
    # (gold, got, ordered, strict, relaxed)
    ([("a", 1), ("b", 2)], [("a", 1), ("b", 2)], False, True, True),
    ([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], False, True, True),
    ([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], True, False, False),
    ([("credit_card",)], [("credit_card", 515)], False, False, True),
    ([("credit_card", 515)], [(515, "credit_card")], False, False, True),
    ([(1, 2)], [(2, 1, 5)], False, False, True),
    ([("a", 1), ("b", 2)], [("a", 1, 9), ("b", 2, 8)], True, False, True),
    ([("a", 1), ("b", 2)], [("b", 2, 8), ("a", 1, 9)], True, False, False),
    ([("a", 1)], [("a", 2)], False, False, False),
    ([(1, 1)], [(1, 2)], False, False, False),
    ([(1, 2)], [(1,)], False, False, False),
    ([("a",), ("b",)], [("a",)], False, False, False),
    ([("a",)], [("a",), ("a",)], False, False, False),
    ([], [], False, True, True),
    ([], [("a",)], False, False, False),
    ([("a",)], [], False, False, False),
    ([(Decimal("10.50"),)], [(10.5,)], False, True, True),
    ([(3,)], [{"n": 3}], False, True, True),
    ([(dt.date(2026, 1, 1), 5)], [(dt.datetime(2026, 1, 1), 5)], False, True, True),
    ([(None, 1)], [(None, 1)], False, True, True),
    ([(None, 1)], [(0, 1)], False, False, False),
]


@pytest.mark.parametrize(("gold", "got", "ordered", "strict", "relaxed"), CASES)
def test_compare(gold, got, ordered, strict, relaxed):
    result = scoring().compare(gold, got, ordered)
    assert (result.strict, result.relaxed) == (strict, relaxed)


def test_a_strict_match_is_always_a_relaxed_match():
    for gold, got, ordered, *_ in CASES:
        result = scoring().compare(gold, got, ordered)
        assert result.relaxed or not result.strict


def test_wilson_interval_matches_known_values():
    wilson = scoring().wilson_interval
    assert wilson(0, 0) == (0.0, 0.0)
    low, high = wilson(5, 10)
    assert (round(low, 3), round(high, 3)) == (0.237, 0.763)
    low, high = wilson(30, 30)
    assert round(low, 3) == 0.886 and round(high, 3) == 1.0
    low, high = wilson(0, 30)
    assert low == 0.0 and round(high, 3) == 0.114


def test_wilson_interval_stays_inside_zero_and_one_and_is_ordered():
    wilson = scoring().wilson_interval
    for total in (1, 5, 30, 90):
        for successes in range(total + 1):
            low, high = wilson(successes, total)
            assert 0.0 <= low <= successes / total <= high <= 1.0
