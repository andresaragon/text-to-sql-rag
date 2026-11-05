"""
Invalidación de la caché de `retrieve_relevant_schema` cuando se reindexa el esquema.

Hasta ahora, tras `scripts/index_schema.py` las respuestas cacheadas quedaban viejas hasta reiniciar Uvicorn
(NOTES.md, "Política de invalidación"). La guardia compara una huella barata de `schema_embeddings`
(`count(*)` y `max(id)`, que cambian en cada reindexado porque el indexador borra y reinserta) y, si cambió,
limpia SOLO la caché de retrieval (`generate_sql` va por (pregunta, contexto): un contexto nuevo es un fallo de caché).

Es OPT-IN: `SCHEMA_CHECK_INTERVAL_SECONDS` = 0 (por defecto) la desactiva y no toca la base; > 0 comprueba como
máximo una vez cada tantos segundos. Nunca lanza: si no puede consultar, no hace nada.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api import routes
from app.config import settings
from app.core import retrieval
from app.main import app


@pytest.fixture(autouse=True)
def estado_limpio(monkeypatch):
    """Cada prueba arranca sin huella previa y con la caché vacía; la guardia vuelve a estar apagada."""
    monkeypatch.setattr(retrieval, "_last_fingerprint", None, raising=False)
    monkeypatch.setattr(retrieval, "_last_check_at", None, raising=False)
    monkeypatch.setattr(settings, "schema_check_interval_seconds", 0.0, raising=False)
    retrieval.retrieve_relevant_schema.cache_clear()
    yield
    retrieval.retrieve_relevant_schema.cache_clear()


def activar(monkeypatch, intervalo=30.0):
    monkeypatch.setattr(settings, "schema_check_interval_seconds", intervalo, raising=False)


class Huellas:
    """Sustituye a schema_fingerprint: devuelve una huella por llamada y cuenta cuántas veces se consultó."""

    def __init__(self, *valores, error=None):
        self.valores = list(valores)
        self.llamadas = 0
        self.error = error

    def __call__(self):
        self.llamadas += 1
        if self.error is not None:
            raise self.error
        return self.valores[min(self.llamadas, len(self.valores)) - 1]


class FalsaCaché:
    def __init__(self):
        self.limpiezas = 0

    def cache_clear(self):
        self.limpiezas += 1


@pytest.fixture
def cache_falsa(monkeypatch):
    falsa = FalsaCaché()
    monkeypatch.setattr(retrieval, "retrieve_relevant_schema", falsa)
    return falsa


# ----------------------------------------------------------------------------------- schema_fingerprint

class MotorFalso:
    """Motor mínimo: `connect()` es un context manager; `execute` distingue la consulta de la huella de la de retrieval."""

    def __init__(self, huella=(4, 17), filas=None):
        self.huella = huella
        self.filas = filas or []
        self.sql_ejecutados = []
        self.connects = 0

    def connect(self):
        self.connects += 1
        motor = self

        class Conexion:
            def __enter__(self_):
                return self_

            def __exit__(self_, *a):
                return False

            def execute(self_, stmt, *a, **k):
                sql = str(stmt).lower()
                motor.sql_ejecutados.append(sql)
                resultado = MagicMock()
                if "count(" in sql:
                    resultado.one.return_value = motor.huella
                    resultado.first.return_value = motor.huella
                else:
                    resultado.mappings.return_value.all.return_value = motor.filas
                return resultado

        return Conexion()


def test_schema_fingerprint_hace_una_consulta_y_une_conteo_y_maximo_id(monkeypatch):
    motor = MotorFalso(huella=(4, 17))
    monkeypatch.setattr(retrieval, "_engine", motor)
    assert retrieval.schema_fingerprint() == "4:17"
    assert motor.connects == 1
    assert len(motor.sql_ejecutados) == 1
    assert "schema_embeddings" in motor.sql_ejecutados[0]


def test_schema_fingerprint_cambia_cuando_cambia_el_maximo_id(monkeypatch):
    motor = MotorFalso(huella=(4, 17))
    monkeypatch.setattr(retrieval, "_engine", motor)
    antes = retrieval.schema_fingerprint()
    motor.huella = (4, 21)  # mismo conteo, reindexado: los ids nuevos son mayores
    assert retrieval.schema_fingerprint() != antes


def test_schema_fingerprint_con_tabla_vacia_no_falla(monkeypatch):
    monkeypatch.setattr(retrieval, "_engine", MotorFalso(huella=(0, 0)))
    assert retrieval.schema_fingerprint() == "0:0"


# ----------------------------------------------------------------------------------- invalidate_if_reindexed

def test_apagada_por_defecto_no_consulta_ni_limpia(monkeypatch, cache_falsa):
    huellas = Huellas("a", "b")
    monkeypatch.setattr(retrieval, "schema_fingerprint", huellas)
    assert retrieval.invalidate_if_reindexed() is False
    assert retrieval.invalidate_if_reindexed() is False
    assert huellas.llamadas == 0
    assert cache_falsa.limpiezas == 0


def test_la_primera_vez_solo_registra_la_huella(monkeypatch, cache_falsa):
    activar(monkeypatch)
    huellas = Huellas("4:17")
    monkeypatch.setattr(retrieval, "schema_fingerprint", huellas)
    assert retrieval.invalidate_if_reindexed(now=0.0) is False
    assert huellas.llamadas == 1
    assert cache_falsa.limpiezas == 0
    assert retrieval._last_fingerprint == "4:17"


def test_misma_huella_no_limpia(monkeypatch, cache_falsa):
    activar(monkeypatch, intervalo=10.0)
    monkeypatch.setattr(retrieval, "schema_fingerprint", Huellas("4:17", "4:17", "4:17"))
    for t in (0.0, 11.0, 22.0):
        assert retrieval.invalidate_if_reindexed(now=t) is False
    assert cache_falsa.limpiezas == 0


def test_huella_distinta_limpia_una_vez_y_devuelve_true(monkeypatch, cache_falsa):
    activar(monkeypatch, intervalo=10.0)
    monkeypatch.setattr(retrieval, "schema_fingerprint", Huellas("4:17", "4:21", "4:21"))
    assert retrieval.invalidate_if_reindexed(now=0.0) is False
    assert retrieval.invalidate_if_reindexed(now=11.0) is True
    assert cache_falsa.limpiezas == 1
    assert retrieval.invalidate_if_reindexed(now=22.0) is False  # ya vista: no vuelve a limpiar
    assert cache_falsa.limpiezas == 1
    assert retrieval._last_fingerprint == "4:21"


def test_no_consulta_mas_de_una_vez_por_intervalo(monkeypatch, cache_falsa):
    activar(monkeypatch, intervalo=30.0)
    huellas = Huellas("a", "b", "c")
    monkeypatch.setattr(retrieval, "schema_fingerprint", huellas)
    retrieval.invalidate_if_reindexed(now=0.0)
    assert retrieval.invalidate_if_reindexed(now=29.9) is False
    assert huellas.llamadas == 1  # dentro del intervalo: ni consulta ni limpia
    assert retrieval.invalidate_if_reindexed(now=30.0) is True  # justo al cumplirse, sí consulta
    assert huellas.llamadas == 2
    assert cache_falsa.limpiezas == 1


def test_un_error_al_consultar_no_propaga_ni_limpia_ni_cambia_el_estado(monkeypatch, cache_falsa):
    activar(monkeypatch, intervalo=10.0)
    monkeypatch.setattr(retrieval, "schema_fingerprint", Huellas("4:17", "4:17"))
    retrieval.invalidate_if_reindexed(now=0.0)
    monkeypatch.setattr(retrieval, "schema_fingerprint", Huellas(error=OperationalError("SELECT 1", {}, Exception("base caída"))))
    assert retrieval.invalidate_if_reindexed(now=11.0) is False
    assert cache_falsa.limpiezas == 0
    assert retrieval._last_fingerprint == "4:17"
    assert retrieval._last_check_at == 0.0  # un chequeo fallido no cuenta: el siguiente vuelve a intentarlo
    # y cuando la base vuelve con otra huella, limpia
    monkeypatch.setattr(retrieval, "schema_fingerprint", Huellas("4:21"))
    assert retrieval.invalidate_if_reindexed(now=12.0) is True
    assert cache_falsa.limpiezas == 1


@pytest.mark.parametrize("error", [ValueError("fila rara"), TypeError("fila None"), OSError("socket cerrado")])
def test_otros_errores_esperables_tampoco_propagan(monkeypatch, cache_falsa, error):
    activar(monkeypatch)
    monkeypatch.setattr(retrieval, "schema_fingerprint", Huellas(error=error))
    assert retrieval.invalidate_if_reindexed(now=0.0) is False
    assert cache_falsa.limpiezas == 0


def test_usa_el_reloj_monotonico_cuando_no_se_pasa_now(monkeypatch, cache_falsa):
    activar(monkeypatch, intervalo=3600.0)
    huellas = Huellas("a", "b")
    monkeypatch.setattr(retrieval, "schema_fingerprint", huellas)
    retrieval.invalidate_if_reindexed()
    retrieval.invalidate_if_reindexed()  # segunda inmediata: dentro del intervalo
    assert huellas.llamadas == 1


# ----------------------------------------------------------------------------------- extremo a extremo

def test_tras_reindexar_la_siguiente_pregunta_recalcula_el_contexto(monkeypatch):
    """Con la caché REAL: sin la guardia, la segunda respuesta saldría vieja; con ella, se recalcula una sola vez."""
    activar(monkeypatch, intervalo=10.0)
    motor = MotorFalso(
        huella=(2, 2),
        filas=[{"object_name": "invoices", "object_type": "table", "description": "Facturas", "distance": 0.3}],
    )
    monkeypatch.setattr(retrieval, "_engine", motor)
    embeds = []
    monkeypatch.setattr(retrieval, "embed_text", lambda q: embeds.append(q) or [0.0] * 384)

    pregunta = "¿cuántas facturas hay?"
    retrieval.invalidate_if_reindexed(now=0.0)          # registra la huella (2, 2)
    retrieval.retrieve_relevant_schema(pregunta)
    retrieval.retrieve_relevant_schema(pregunta)
    assert len(embeds) == 1                              # cacheado

    motor.huella = (2, 9)                                # reindexado
    assert retrieval.invalidate_if_reindexed(now=11.0) is True
    retrieval.retrieve_relevant_schema(pregunta)
    assert len(embeds) == 2                              # recalculado con el índice nuevo
    retrieval.retrieve_relevant_schema(pregunta)
    assert len(embeds) == 2                              # y vuelve a cachearse


# ----------------------------------------------------------------------------------- ruta /query

def test_query_llama_a_la_guardia_antes_del_retrieval(monkeypatch):
    orden = []
    monkeypatch.setattr(routes, "invalidate_if_reindexed", lambda: orden.append("guardia") or False)

    def retrieve_falso(question, *a, **k):
        orden.append("retrieval")
        return retrieval.RetrievedSchema(context="", best_distance=None)  # índice vacío -> 503

    monkeypatch.setattr(routes, "retrieve_relevant_schema", retrieve_falso)
    cliente = TestClient(app)
    for _ in range(2):
        assert cliente.post("/query", json={"question": "¿cuántas facturas hay?"}).status_code == 503
    assert orden == ["guardia", "retrieval", "guardia", "retrieval"]


def _intervalo_en_proceso_limpio(valor_env):
    """Lee Settings en un proceso nuevo, con la variable SCHEMA_CHECK_INTERVAL_SECONDS puesta o ausente."""
    import os
    import subprocess
    import sys

    entorno = {k: v for k, v in os.environ.items() if k != "SCHEMA_CHECK_INTERVAL_SECONDS"}
    if valor_env is not None:
        entorno["SCHEMA_CHECK_INTERVAL_SECONDS"] = valor_env
    r = subprocess.run(
        [sys.executable, "-c", "from app.config import settings; print(repr(settings.schema_check_interval_seconds))"],
        capture_output=True, text=True, env=entorno, check=False,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_la_guardia_viene_apagada_por_defecto_y_se_activa_con_la_variable():
    assert _intervalo_en_proceso_limpio(None) == "0.0"
    assert _intervalo_en_proceso_limpio("45") == "45.0"
