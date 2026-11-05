## Contexto técnico
Asistente Text-to-SQL con RAG y un cortafuegos AST de SQL (`README.es.md`). Repo **público**.
- Estructura: `app/` (API, `app/core/`: `safety.py` = cortafuegos, `retrieval.py`, `sql_generator.py`, `db.py`), `tests/`, `scripts/`, `benchmarks/`, `db/`, `docs/`. Comportamiento y límites declarados: `SPEC.md` y `NOTES.md`.
- Comandos (con el venv compartido de abajo; son los mismos que corre el CI):
  - Lint: `ruff check .` (ruff 0.17.0 fijado en `requirements-dev.txt`).
  - Pruebas: `pytest -q`.
  - Pruebas del cortafuegos con sqlglot 30 (job `firewall-sqlglot-30` del CI): instala `sqlglot==30.18.0` y corre `EXPECT_SQLGLOT=30.18.0 pytest -q`. Sin esa variable, `tests/test_firewall_sqlglot_compat.py` se salta. El job usa el mismo `requirements.txt` + `sqlglot==30.18.0`: **no** lo instales en el venv compartido (lo cambiaría para todos); si necesitas esa prueba, déjala al CI.
- CI (`.github/workflows/ci.yml`): `test` (ruff + pytest), `firewall-sqlglot-30` y `docker`. `oracle-integration.yml` es manual (`workflow_dispatch`).
- Reglas de estilo que **verifica un test** (`tests/test_estilo_ruff.py`): `ruff check app tests scripts` limpio; **no** añadir `ruff.toml`, `.ruff.toml` ni `[tool.ruff]` (no se debilita la configuración); **un solo `# noqa`** en todo el repo, el que ya existe en `app/core/safety.py` (`noqa: BLE001` con motivo): captura excepciones concretas, nunca `except Exception`; y los payloads de `tests/test_safety_adversarial.py` tienen un hash fijo: cambiarlos rompe la prueba a propósito.
- Los tests del cortafuegos usan `sqlglot`; el comportamiento debe ser el mismo con 25.24 y 30.x.

## Repo público: identidad y secretos
- Los commits van con el correo noreply de GitHub, no con el personal. El git local de esta máquina usa uno personal: antes de commitear exporta `GIT_AUTHOR_NAME`/`GIT_COMMITTER_NAME` y `GIT_AUTHOR_EMAIL`/`GIT_COMMITTER_EMAIL` con `16310427+andresaragon@users.noreply.github.com` (el commit no se puede reescribir después sin permiso).
- `.env` es local y está ignorado; no lo subas ni pegues su contenido. Solo `.env.example` va al repo.

## Entorno Python (IMPORTANTE — leer antes de instalar nada)
Este proyecto usa git worktrees (Orca) para correr varios agentes en paralelo sobre
distintas ramas. **NO crear un venv nuevo por worktree** (duplica torch/sentence-transformers,
~2GB+ cada vez) **ni usar el `python3`/`pip3` por defecto del PATH** (puede resolver al venv
de OTRO proyecto sin relación, contaminándolo).

Usar siempre el venv compartido ya creado para este proyecto:
```
/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/python
/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/pip
/home/santiago/orca/workspaces/text-to-sql-rag/venv-shared/bin/pytest
```
Python 3.12 (no 3.14 -- `pydantic-core`/`pyo3` todavía no tiene wheels precompilados para 3.14
y falla el build). Ya tiene instalado `requirements.txt` completo + `locust`/`pytest`/`httpx`
de desarrollo. Si falta algo, instalarlo AHÍ (`.../venv-shared/bin/pip install ...`), nunca
crear un venv local nuevo dentro del worktree.

## Notas
Para contexto de negocio y próximos pasos, ver la nota del proyecto en el vault de Obsidian:
`/mnt/d/Claude/Santi's Claude/03 - Proyectos/text-to-sql-rag/text-to-sql-rag.md`
