"""Dataset sintético del benchmark A/B (SPEC.md, CA1). Pruebas de aceptación: no se editan."""

import subprocess
import sys
from pathlib import Path

from scripts import gen_dataset

ROOT = Path(__file__).resolve().parents[1]
# Sumas de control fijadas con la semilla 42: si cambian, el benchmark deja de ser comparable.
EXPECTED = {
    "customers": "300:d17c8a7c268b6c47aa6d1bffd8a711c0f8febd8b88137ed37dfe8cb7a6c3f5c3",
    "invoices": "2000:71795155d30f416801d6de25791ee4047cbc858d7af9c7285adb4c4bf4b13fad",
    "payments": "1486:e9bf19365c52e1ee0f6d69b417a59b7fbfc63dee465cf923cfcba798072d2b04",
    "collection_actions": "1117:3685f4d96859763d689f246ce0fd789cca21246fa5d69d29710da58c41d76250",
}


def test_the_default_seed_produces_the_pinned_dataset():
    assert gen_dataset.checksums(gen_dataset.generate()) == EXPECTED


def test_the_dataset_is_deterministic_and_the_seed_matters():
    assert gen_dataset.checksums(gen_dataset.generate(42)) == gen_dataset.checksums(gen_dataset.generate(42))
    assert gen_dataset.checksums(gen_dataset.generate(7)) != EXPECTED


def test_the_row_counts_are_the_documented_ones():
    dataset = gen_dataset.generate()
    assert [len(dataset.table(t)) for t in gen_dataset.TABLES] == [300, 2000, 1486, 1117]


def test_the_data_has_the_variety_the_questions_need():
    dataset = gen_dataset.generate()
    statuses = {row[6] for row in dataset.invoices}
    assert statuses == {"paid", "overdue", "pending"}
    assert {row[3] for row in dataset.customers} >= {"Colombia", "Mexico", "Italy", "Spain", "Chile", "Peru", "Argentina"}
    assert {row[3] for row in dataset.invoices} == {"USD", "COP", "EUR"}
    assert {row[4] for row in dataset.payments} == {"bank_transfer", "credit_card", "cash", "paypal"}
    with_invoices = {row[1] for row in dataset.invoices}
    assert len(with_invoices) < len(dataset.customers)  # hay clientes sin facturas
    assert len({row[1] for row in dataset.payments}) < len(dataset.invoices)  # y facturas sin pagos


def test_the_reference_date_separates_overdue_from_pending():
    for _, _, _, _, _, due, status in gen_dataset.generate().invoices:
        if status == "overdue":
            assert due < gen_dataset.REFERENCE_DATE
        if status == "pending":
            assert due >= gen_dataset.REFERENCE_DATE


def test_the_cli_prints_the_four_checksums():
    out = subprocess.run([sys.executable, "-m", "scripts.gen_dataset", "--checksums"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    printed = dict(line.split(": ") for line in out.stdout.splitlines() if ": " in line)
    assert printed == EXPECTED
