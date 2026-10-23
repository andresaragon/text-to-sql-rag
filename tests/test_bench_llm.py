"""Generadores y ejecutores del benchmark A/B (SPEC.md, CA7). Escritas antes de implementar; no se editan."""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import settings


def llm():
    return importlib.import_module("scripts.bench_ab.llm")


def executors():
    return importlib.import_module("scripts.bench_ab.executors")


QUESTIONS = [{"question": "¿Cuántos?", "sql": {"postgres": "SELECT 1 -- pg", "oracle": "SELECT 1 -- ora"}}]


def test_the_gold_generator_returns_the_reference_of_the_dialect():
    gold = llm().GoldGenerator(QUESTIONS)
    assert gold("cualquiera", "postgres", "¿Cuántos?") == "SELECT 1 -- pg"
    assert gold("cualquiera", "oracle", "¿Cuántos?") == "SELECT 1 -- ora"


def test_the_wrong_generator_never_matches():
    assert llm().WrongGenerator()("m", "oracle", "¿Cuántos?") == "SELECT 1"


def _patched(monkeypatch, distance):
    module = llm()
    seen = {}

    def fake_generate(question, context, dialect):
        seen.update(model=settings.ollama_model, dialect=dialect, context=context, question=question)
        return "SELECT 1"

    fake_generate.cache_clear = MagicMock()
    fake_retrieve = MagicMock(return_value=SimpleNamespace(context="CTX", best_distance=distance))
    fake_retrieve.cache_clear = MagicMock()
    monkeypatch.setattr(module, "generate_sql", fake_generate)
    monkeypatch.setattr(module, "retrieve_relevant_schema", fake_retrieve)
    return module, seen, fake_generate, fake_retrieve


def test_the_ollama_generator_sets_the_model_clears_the_caches_and_passes_the_dialect(monkeypatch):
    module, seen, fake_generate, fake_retrieve = _patched(monkeypatch, 0.1)
    before = settings.ollama_model
    assert module.OllamaGenerator()("qwen2.5-coder:7b", "oracle", "¿Cuántos?") == "SELECT 1"
    assert seen == {"model": "qwen2.5-coder:7b", "dialect": "oracle", "context": "CTX", "question": "¿Cuántos?"}
    fake_generate.cache_clear.assert_called()
    fake_retrieve.cache_clear.assert_called()
    assert settings.ollama_model == before  # restaurado tras la llamada


def test_an_out_of_domain_question_yields_no_sql(monkeypatch):
    module, _, fake_generate, _ = _patched(monkeypatch, 0.99)
    assert module.OllamaGenerator()("qwen2.5-coder:7b", "postgres", "¿Capital de Francia?") is None
    fake_generate.cache_clear.assert_not_called()


def test_the_executor_switches_the_app_settings_per_dialect_and_restores_them(monkeypatch):
    module = executors()
    seen = []

    def fake_execute_select(sql):
        seen.append((sql, settings.target_dialect, settings.target_database_url, settings.allowed_schema))
        return [{"n": 1}]

    monkeypatch.setattr(module, "execute_select", fake_execute_select)
    before = (settings.target_dialect, settings.target_database_url, settings.allowed_schema)
    execute = module.make_executor()
    assert execute("postgres", "SELECT 1") == [{"n": 1}]
    assert execute("oracle", "SELECT 2") == [{"n": 1}]
    (_, pg_dialect, _, _), (_, oracle_dialect, oracle_url, oracle_schema) = seen
    assert pg_dialect == "postgres"
    assert oracle_dialect == "oracle" and oracle_url.startswith("oracle+oracledb://app_ro:") and oracle_schema == "SALES"
    assert (settings.target_dialect, settings.target_database_url, settings.allowed_schema) == before
