## Contexto técnico
- (Completa aquí: comandos de build/test, convenciones de código, estructura de carpetas.)

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
