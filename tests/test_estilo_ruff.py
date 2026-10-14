"""Tests de aceptación de la limpieza de ruff (ver SPEC.md). Los escribió el checker; el maker no los modifica."""

import hashlib
import importlib
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HASH_PAYLOADS = "637a996348a11a8e2f15d43dd3c14c6c24197ac46860a5f241e19d4f1e4c50b0"


def _fuentes():
    for carpeta in ("app", "tests"):
        yield from (RAIZ / carpeta).rglob("*.py")


def test_ruff_check_app_y_tests_sin_hallazgos():
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "app", "tests"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_se_debilita_la_configuracion_de_ruff():
    assert not (RAIZ / "ruff.toml").exists()
    assert not (RAIZ / ".ruff.toml").exists()
    pyproject = RAIZ / "pyproject.toml"
    if pyproject.exists():
        assert "[tool.ruff" not in pyproject.read_text(encoding="utf-8")


def test_solo_un_noqa_permitido_y_con_motivo():
    encontrados = []
    for f in _fuentes():
        if f.name == Path(__file__).name:
            continue
        for n, linea in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            assert not re.search(r"ruff:\s*noqa", linea), f"{f}:{n}"
            if re.search(r"#\s*noqa", linea):
                encontrados.append((f.relative_to(RAIZ).as_posix(), linea))
    assert len(encontrados) <= 1, encontrados
    for ruta, linea in encontrados:
        assert ruta == "app/core/safety.py", ruta
        assert re.search(r"noqa:\s*BLE001\b", linea), linea
        assert len(linea.split("BLE001", 1)[1].strip(" -—:#")) >= 15, f"falta el motivo: {linea}"


def test_payloads_adversariales_no_cambian_de_valor():
    m = importlib.import_module("tests.test_safety_adversarial")
    items = sorted(
        (k, repr(v)) for k, v in vars(m).items()
        if k.isupper() and isinstance(v, (list, tuple, dict, set, frozenset, str, int))
    )
    digest = hashlib.sha256("\n".join(f"{k}={v}" for k, v in items).encode()).hexdigest()
    assert digest == HASH_PAYLOADS
